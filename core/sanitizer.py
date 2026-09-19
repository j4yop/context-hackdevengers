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
            "InternalServerError",
            "500 Internal Server Error",
            "ConnectionRefusedError",
            "TimeoutError",
            "FAILED_DEPENDENCY",
            "NullPointerException",
            "\"status\": 500",
            "\"status\": 504",
            "\"error\":"
        ]
        return any(kw in content for kw in error_keywords)

    @classmethod
    def distill_tool_payload(cls, content: str, tool_name: Optional[str] = None) -> Tuple[str, int, int]:
        """
        Compresses large JSON responses into high-density semantic schemas.
        Returns: (compacted_text, original_tokens, compacted_tokens)
        """
        orig_len = max(1, len(content) // 4)  # rough token approximation

        # Try parsing as JSON
        try:
            data = json.loads(content)
            compacted = cls._compress_json(data, tool_name)
            new_len = max(1, len(compacted) // 4)
            return compacted, orig_len, new_len
        except (json.JSONDecodeError, TypeError):
            pass

        # If it is an unformatted error traceback, condense it
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
            overflow_note = f", +{overflow} more items" if overflow > 0 else ""
            return f"[Tool Output: {json.dumps(summary)}{overflow_note}]"

        if isinstance(data, dict):
            # Check if this is an inventory or catalog response
            if "items" in data and isinstance(data["items"], list):
                items = data["items"][:cls.MAX_COMPACT_ITEMS]
                compact_items = [cls._compress_item(i) for i in items]
                overflow = len(data["items"]) - len(items)
                return f"[CatalogSearch: {len(data['items'])} found. Top matches: {json.dumps(compact_items)}" + (f" (+{overflow} more)]" if overflow > 0 else "]")

            if "dark_stores" in data and isinstance(data["dark_stores"], list):
                stores = [{"store_id": s.get("store_id"), "eta": s.get("eta_mins"), "stock": s.get("stock_status")} for s in data["dark_stores"]]
                return f"[DarkStoreAvailability: {json.dumps(stores)}]"

            # Standard dictionary distillation (drop nulls, verbose IDs)
            distilled = {k: v for k, v in data.items() if k not in ["metadata", "trace_id", "headers", "debug", "raw_response"]}
            return f"[Result: {json.dumps(distilled)}]"

        return json.dumps(data)

    @classmethod
    def _compress_item(cls, item: Any) -> Any:
        """Extracts high-signal product/order attributes."""
        if isinstance(item, dict):
            return {
                "name": item.get("name") or item.get("sku_name") or item.get("title"),
                "price": item.get("price") or item.get("mrp"),
                "status": item.get("status") or item.get("in_stock") or ("in_stock" if item.get("inventory", 0) > 0 else "out_of_stock")
            }
        return item

    @classmethod
    def _compress_traceback(cls, content: str) -> str:
        """Shrinks multi-line Python/Java/HTTP stack traces into a 1-line error summary."""
        # Look for the last Exception line
        lines = content.strip().split("\n")
        err_line = lines[-1]
        for line in reversed(lines):
            if any(e in line for e in ["Error:", "Exception:", "HTTPStatusError:", "Status: 5"]):
                err_line = line.strip()
                break
        return f"[ToolError: {err_line} (Full stack trace sanitized)]"

    @staticmethod
    def create_tombstone(turn_index: int, tool_name: str, resolved_at_turn: int) -> str:
        """Generates a compact tombstone for an error that has been resolved."""
        return f"[TOMBSTONE: Tool '{tool_name}' failed at Turn {turn_index} — Successfully resolved at Turn {resolved_at_turn}]"
