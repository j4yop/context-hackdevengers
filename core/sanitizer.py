"""
ContextGC: Tool-Payload Distillation & Error Traceback Sanitizer
Compresses sprawling API responses and purges handled error tracebacks to reclaim context.
"""

from typing import Dict, Any, Tuple, Optional
import json
import re

class ToolSanitizer:
    """
    Sanitizes and compacts tool execution outputs before and during LLM context assembly.
    Prevents raw JSON bloat and error traceback contamination.
    """

    MAX_COMPACT_ITEMS = 3

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
    def _compress_json(cls, data: Any, tool_name: Optional[str] = None) -> str:
        """Selectively retains essential fields for common enterprise tools."""
        if isinstance(data, list):
            sample = data[:cls.MAX_COMPACT_ITEMS]
            summary = [cls._compress_item(item) for item in sample]
            overflow = len(data) - len(sample)
            overflow_note = f", +{overflow} more items truncated" if overflow > 0 else ""
            label = tool_name or "ToolOutput"
            return f"[{label}: {len(data)} items. Top sample: {json.dumps(summary)}{overflow_note}]"

        if isinstance(data, dict):
            # Check if this is an inventory or catalog response under standard keys
            for lk in ["items", "available_skus", "skus", "products", "inventory", "catalog", "records", "data"]:
                if lk in data and isinstance(data[lk], list):
                    items = data[lk][:cls.MAX_COMPACT_ITEMS]
                    compact_items = [cls._compress_item(i) for i in items]
                    overflow = len(data[lk]) - len(items)
                    label = tool_name or "CatalogSearch"
                    overflow_note = f" (+{overflow} more items truncated)]" if overflow > 0 else "]"
                    return f"[{label}: {len(data[lk])} items found. Top matches: {json.dumps(compact_items)}{overflow_note}"

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

