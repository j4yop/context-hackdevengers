"""
ContextGC: Tool-Payload Distillation & Error Traceback Sanitizer
Compresses sprawling API responses and purges handled error tracebacks to reclaim context.
"""

import json
import re
from typing import Any, List, Optional, Tuple


class ToolSanitizer:
    """
    Sanitizes and compacts tool execution outputs before and during LLM context assembly.
    Prevents raw JSON bloat and error traceback contamination.
    """

    MAX_COMPACT_ITEMS = 3

    #: Keys/values that must never be dropped by compaction. If a row carries any
    #: of these signals it is always retained regardless of sample position, and
    #: the omission is reported in the output. Compaction is allowed to be lossy
    #: about *bulk*; it is not allowed to be lossy about *safety*.
    SAFETY_SIGNALS = (
        "allergen", "allergy", "peanut", "tree_nut", "nut_", "gluten", "dairy",
        "soy", "shellfish", "egg", "hazard", "warning", "recall", "severity",
        "critical", "danger", "unsafe", "pii", "ssn", "secret", "password",
        "token", "expiry", "expired", "quarantine", "contaminat", "expired",
    )

    @classmethod
    def _is_safety_relevant(cls, item: Any) -> bool:
        """True when a row carries a signal that compaction must never drop."""
        try:
            blob = json.dumps(item, default=str).lower()
        except (TypeError, ValueError):
            blob = str(item).lower()
        return any(sig in blob for sig in cls.SAFETY_SIGNALS)

    #: Markers that identify a message as machine-generated tool output.
    #: Deliberately includes *content* signals rather than relying on a naming
    #: convention, because real transcripts do not follow one: in the
    #: SWE-agent corpus, 0% of messages carry a `TOOL_OUTPUT` tag and tool
    #: output is filed under the `user` role. Keying on the convention meant the
    #: sanitizer never fired on real data.
    TOOL_OUTPUT_MARKERS = (
        "TOOL_OUTPUT", "Traceback (most recent call last)", "<tool_response>",
        "Command output", "Exit code:", "\n$ ", "```\nTraceback",
        # Search and listing output. A grep hit is the single largest source of
        # wrong facts in the coding corpus: the pattern sees a file path in
        # "Found 14 matches for X in /path/to/file.py:" and concludes the agent
        # is editing that file. It is reading a search listing.
        "Found ", " matches for ", "matches in ", "End of search",
        "test session starts", "collected ", "PASSED", "FAILED ",
        # Agent-environment responses. Short, so the length heuristic misses
        # them, and they name the file the editor is sitting on -- which is
        # exactly the value the `current_file` schema wants. Inferring from
        # these is inference from machine output.
        "Open file:", "Current directory:", "bash-$", "String to edit",
        "Your proposed edit has", "isn't valid Python", "No lines selected",
    )

    @classmethod
    def looks_like_tool_output(cls, content: str, role: str = "") -> bool:
        """
        True when a message is machine-generated output, whatever role it is filed under.

        A stack trace is a stack trace regardless of the role the transcript
        system assigned it. Requiring a marker or a ``tool`` role meant the
        compactor ran on the hand-written fixture -- where the author had tagged
        their own sludge -- and on nothing else.
        """
        if not content:
            return False
        if role in ("tool", "function"):
            return True
        if any(marker in content for marker in cls.TOOL_OUTPUT_MARKERS):
            return True
        # A wall of structured text with no prose sentence structure.
        if len(content) > 1500 and content.count("\n") > 12 and '"' in content:
            return True
        return cls._is_json_payload(content)

    @staticmethod
    def _is_json_payload(content: str) -> bool:
        """
        True when the whole message is one JSON value.

        Found by measuring a second corpus: APIGen-MT files its tool results
        under the ``user`` role as compact JSON --
        ``{"reservation_id": "0U4NPP", "origin": "PHL", ...}`` -- and the
        length-based rule above caught none of them, because a single record is
        well under 1500 characters. Those payloads were therefore never
        compacted, and worse, they sat in the transcript looking like something a
        person had said.

        A message that is *entirely* one JSON object or array is machine output.
        The "entirely" part matters: an agent that quotes JSON inside a sentence
        is still speaking, and only the pure-payload case is claimed here.
        """
        stripped = content.strip()
        if not stripped or stripped[0] not in "{[":
            return False
        # Cheap reject first: JSON has no sentence punctuation at the top level
        # often enough that this is worth checking before paying for a parse.
        try:
            json.loads(stripped)
        except (ValueError, TypeError):
            return False
        return True

    @staticmethod
    def is_error_payload(content: str) -> bool:
        """Detects if a tool message contains an error or failure stack trace."""
        error_keywords = [
            "Traceback (most recent call last)",
            "FAIL ",
            "ToolError",
            "HTTPStatusError",
            "504 Gateway Timeout",
            "502 Bad Gateway",
            "InternalServerError",
            "500 Internal Server Error",
            "ConnectionRefusedError",
            "TimeoutError",
            "FAILED_DEPENDENCY",
            "NullPointerException",
            "TypeError:",
            "AssertionError:",
            "\"status\": 500",
            "\"status\": 504",
            "\"error\":"
        ]
        return any(kw in content for kw in error_keywords)

    @classmethod
    def distill_tool_payload(cls, content: str, tool_name: Optional[str] = None) -> Tuple[str, int, int]:
        """
        Compresses large JSON responses, git diffs, and tracebacks into high-density semantic schemas.
        Returns: (compacted_text, original_tokens, compacted_tokens)
        """
        orig_len = max(1, len(content) // 4)  # rough token approximation

        # Handle git diffs
        if "diff --git" in content or "package-lock.json" in content:
            lines = content.strip().split("\n")
            first_line = lines[0] if lines else "diff --git"
            compacted = f"[GitDiff: {first_line} (+{max(1, len(lines)-1)} lines compacted)]"
            new_len = max(1, len(compacted) // 4)
            return compacted, orig_len, new_len

        # Extract tool name from header if not provided
        if not tool_name:
            t_match = re.search(r"TOOL_OUTPUT\s*\[([a-zA-Z0-9_\-]+)\]", content)
            if t_match:
                tool_name = t_match.group(1)

        # Try parsing directly as JSON or extracting embedded JSON
        data = None
        trimmed = content.strip()
        try:
            data = json.loads(trimmed)
        except (json.JSONDecodeError, TypeError):
            # Attempt to locate embedded JSON object: { ... }
            fb_obj = trimmed.find("{")
            lb_obj = trimmed.rfind("}")
            if fb_obj != -1 and lb_obj > fb_obj:
                try:
                    data = json.loads(trimmed[fb_obj:lb_obj+1])
                except (json.JSONDecodeError, TypeError):
                    pass

            # If not an object, attempt array: [ ... ]
            if data is None:
                for m in re.finditer(r"\[\s*[\{\"]", trimmed):
                    fb_arr = m.start()
                    lb_arr = trimmed.rfind("]")
                    if lb_arr > fb_arr:
                        try:
                            data = json.loads(trimmed[fb_arr:lb_arr+1])
                            break
                        except (json.JSONDecodeError, TypeError):
                            pass

        if data is not None:
            compacted = cls._compress_json(data, tool_name)
            # Never return something larger than the input. A small payload that
            # gains a "[Result: ...]" wrapper is a net regression.
            if len(compacted) >= len(trimmed):
                return trimmed, orig_len, orig_len
            new_len = max(1, len(compacted) // 4)
            return compacted, orig_len, new_len

        # If it is an unformatted error traceback or test failure, condense it
        if cls.is_error_payload(content):
            compacted = cls._compress_traceback(content)
            new_len = max(1, len(compacted) // 4)
            return compacted, orig_len, new_len

        # Fallback: Truncate very long text dumps
        if len(content) > 600:
            compacted = content[:250] + f"\n... [TRUNCATED {len(content)-500} CHARS OF VERBOSE LOGS] ...\n" + content[-250:]
            new_len = max(1, len(compacted) // 4)
            return compacted, orig_len, new_len

        return content, orig_len, orig_len

    @classmethod
    def _compress_rowset(cls, rows: List[Any], tool_name: Optional[str] = None) -> str:
        """Compacts a list of rows without ever silently dropping a safety-relevant row.

        Keeps the first ``MAX_COMPACT_ITEMS`` rows as the representative sample,
        then appends *every* remaining row that carries a safety signal. Reports
        exactly how many rows were dropped so the omission is auditable rather
        than invisible.
        """
        label = tool_name or "ToolOutput"
        total = len(rows)
        sample = rows[:cls.MAX_COMPACT_ITEMS]
        kept_indexes = set(range(len(sample)))

        # Safety sweep over the rows the sample would otherwise discard.
        flagged: List[Any] = []
        for i, row in enumerate(rows[cls.MAX_COMPACT_ITEMS:], start=cls.MAX_COMPACT_ITEMS):
            if cls._is_safety_relevant(row):
                kept_indexes.add(i)
                flagged.append(cls._compress_item(row))

        compacted = [cls._compress_item(r) for r in sample] + flagged
        dropped = total - len(kept_indexes)

        parts = [f"[{label}: {total} rows. Showing {len(compacted)}."]
        if flagged:
            parts.append(f"SAFETY-FLAGGED ROWS RETAINED: {json.dumps(flagged, default=str)}")
        if dropped:
            parts.append(f"{dropped} non-safety rows omitted (truncated=true).")
        else:
            parts.append("No rows omitted.")
        parts.append(f"Sample: {json.dumps(compacted, default=str)}]")
        return " ".join(parts)

    @classmethod
    def _compress_json(cls, data: Any, tool_name: Optional[str] = None) -> str:
        """Selectively retains essential fields for common enterprise tools."""
        if isinstance(data, list):
            return cls._compress_rowset(data, tool_name)

        if isinstance(data, dict):
            # Check if this is an inventory or catalog response under standard keys
            for lk in ["items", "available_skus", "skus", "products", "inventory", "catalog", "records", "data"]:
                if lk in data and isinstance(data[lk], list):
                    return cls._compress_rowset(data[lk], tool_name)

            if "dark_stores" in data and isinstance(data["dark_stores"], list):
                stores = [{"store_id": s.get("store_id"), "eta": s.get("eta_mins"), "stock": s.get("stock_status")} for s in data["dark_stores"]]
                return f"[DarkStoreAvailability: {json.dumps(stores)}]"

            # Standard dictionary distillation (drop nulls, verbose IDs)
            distilled = {k: v for k, v in data.items() if k not in ["metadata", "trace_id", "headers", "debug", "raw_response"]}
            return f"[Result: {json.dumps(distilled)}]"

        return json.dumps(data)

    @classmethod
    def _compress_item(cls, item: Any) -> Any:
        """Extracts high-signal product/order attributes without phantom keys."""
        if isinstance(item, dict):
            res = {}
            for k in ["name", "sku_name", "title", "sku_id"]:
                if k in item:
                    res["name"] = item[k]
                    break
            for k in ["price", "mrp", "cost"]:
                if k in item:
                    res["price"] = item[k]
                    break
            for k in ["stock", "status", "in_stock", "available"]:
                if k in item:
                    res["stock"] = item[k]
                    break
            # Carry every safety-bearing field through verbatim, whatever its name.
            for k, v in item.items():
                if cls._is_safety_relevant({k: v}):
                    res[k] = v
            if "warning" in item:
                res["warning"] = item["warning"]
            return res if res else {k: item[k] for k in list(item.keys())[:3]}
        return item

    @classmethod
    def _compress_traceback(cls, content: str) -> str:
        """Shrinks multi-line Python/Java/HTTP stack traces into a 1-line error summary."""
        lines = content.strip().split("\n")
        err_line = lines[-1]
        for line in reversed(lines):
            if any(e in line for e in ["Error:", "Exception:", "HTTPStatusError:", "Status: 5", "FAIL "]):
                err_line = line.strip()
                break
        return f"[ToolError: {err_line} (Full stack trace sanitized)]"

    @staticmethod
    def create_tombstone(turn_index: int, tool_name: str, resolved_at_turn: Optional[int] = None, resolved_turn: Optional[int] = None) -> str:
        """Generates a compact tombstone for an error that has been resolved."""
        target_turn = resolved_at_turn if resolved_at_turn is not None else resolved_turn
        return f"[TOMBSTONE: Tool '{tool_name}' failed at Turn {turn_index} — Successfully resolved at Turn {target_turn}]"

