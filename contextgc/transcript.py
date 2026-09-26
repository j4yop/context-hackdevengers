"""
ContextGC: parse a pasted transcript into OpenAI message format.

Accepts two shapes, because those are what people actually have:

1. **JSON** -- an OpenAI-style message array, or an object with a ``messages``
   key. Recognised by a leading ``[`` or ``{``.

2. **Line-oriented text** -- one turn per line or paragraph::

       user: deliver to Tower B, Flat 402. Severe peanut allergy.
       assistant: Confirmed, routing to Tower B.
       tool [inventory]: {"items": [{"name": "Milk"}]}

   A role prefix may be followed by a bracketed tool name. Text before the
   first recognised prefix is reported as a warning rather than silently
   dropped, so a mis-paste is visible instead of quietly losing turns.
"""

import json
import re
from typing import Any, Dict, List, Tuple

#: Roles accepted on input, mapped to canonical OpenAI role names.
_ROLE_ALIASES = {
    "user": "user",
    "human": "user",
    "you": "user",
    "assistant": "assistant",
    "ai": "assistant",
    "bot": "assistant",
    "model": "assistant",
    "system": "system",
    "tool": "tool",
    "function": "tool",
    "tool_output": "tool",
}

# `role:` or `role [name]:` at the start of a line.
_ROLE_LINE_RE = re.compile(
    r"^[ \t>*_-]*"
    r"(user|human|you|assistant|ai|bot|model|system|tool|function|tool_output)"
    r"(?:[ \t]*\[[ \t]*([A-Za-z0-9_.\-]{1,40})[ \t]*\])?"
    r"[ \t]*:[ \t]*",
    re.IGNORECASE,
)


def parse_transcript(text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse ``text`` into ``(messages, warnings)``.

    ``warnings`` is non-empty when something in the input could not be
    interpreted. Warnings are surfaced to the caller rather than swallowed, so
    a bad paste degrades visibly.
    """
    warnings: List[str] = []
    if not text or not text.strip():
        return [], ["empty input"]

    stripped = text.strip()

    # -- JSON path ---------------------------------------------------------
    if stripped[0] in "[{":
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            warnings.append(f"looks like JSON but failed to parse ({exc.msg} at line {exc.lineno}); treated as plain text")
        else:
            if isinstance(data, dict):
                data = data.get("messages", [data])
            if isinstance(data, list):
                messages = [m for m in (_normalise(m, warnings) for m in data) if m]
                return messages, warnings
            warnings.append("JSON was neither a message array nor an object with 'messages'")

    # -- line-oriented path ------------------------------------------------
    messages: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None
    buffer: List[str] = []

    def flush() -> None:
        nonlocal current, buffer
        if current is not None:
            body = "\n".join(buffer).strip()
            if body:
                current["content"] = body
                messages.append(current)
        current, buffer = None, []

    for line in text.splitlines():
        match = _ROLE_LINE_RE.match(line)
        if match:
            flush()
            role = _ROLE_ALIASES[match.group(1).lower()]
            current = {"role": role}
            if match.group(2):
                current["name"] = match.group(2)
            buffer = [line[match.end():]]
        elif current is not None:
            buffer.append(line)
        elif line.strip():
            warnings.append(f"ignored leading text before the first role marker: {line.strip()[:60]!r}")

    flush()

    if not messages:
        warnings.append(
            "no turns recognised. Use one turn per line starting with "
            "'user:', 'assistant:', 'system:' or 'tool [name]:' -- or paste a JSON message array."
        )
    return messages, warnings


def _normalise(raw: Any, warnings: List[str]) -> Dict[str, Any] | None:
    """Coerce one JSON element into a message dict, or explain why we can't."""
    if not isinstance(raw, dict):
        warnings.append(f"skipped non-object message entry: {str(raw)[:60]!r}")
        return None
    role = str(raw.get("role", "user")).lower()
    role = _ROLE_ALIASES.get(role, role)
    if role not in ("user", "assistant", "system", "tool"):
        warnings.append(f"unknown role {role!r} coerced to 'user'")
        role = "user"

    msg: Dict[str, Any] = {"role": role, "content": raw.get("content") or ""}
    for passthrough in ("name", "tool_call_id", "tool_calls"):
        if raw.get(passthrough) is not None:
            msg[passthrough] = raw[passthrough]
    return msg
