"""
ContextGC: the two things most callers need.

    from contextgc import compile_messages, compile_transcript

``compile_messages``  OpenAI-format message list  -> compiled context + telemetry
``compile_transcript``  pasted plain-text chat log  -> compiled context + telemetry

Both are pure functions: same input, same output, no network, no model calls,
no global state.
"""

import functools
from typing import Any, Dict, List, Optional, Tuple

from .gc_engine import ContextGCEngine
from .transcript import parse_transcript

__all__ = [
    "compile_messages",
    "compile_transcript",
    "patch_openai",
    "ContextGCEngine",
]


def compile_messages(
    messages: List[Dict[str, Any]],
    mode: str = "compact",
    invariants: Optional[List[str]] = None,
    recall_query: Optional[str] = None,
    session_id: Optional[str] = None,
    teach_protocol: bool = False,
    schema: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Compile an OpenAI-format message history.

    Args:
        messages: ``[{"role": ..., "content": ...}, ...]``
        mode: ``"compact"`` (retire superseded turns, inline state at head) or
            ``"cache_friendly"`` (leave the prefix byte-identical, append the
            state register at the tail).
        invariants: rules to pin into the compiled context.
        recall_query: if set, search retired turns and re-inject the best match.
        teach_protocol: prepend the state-protocol instruction so the agent
            declares its own state changes. See :mod:`contextgc.state_protocol`.
        schema: entity patterns to enable. Empty by default -- the read path has
            no built-in domain, because the default it used to ship was measured
            producing nonsense on real transcripts.

    Returns:
        ``(compiled_messages, telemetry)``. Every telemetry field is measured at
        runtime; see :meth:`ContextGCEngine.process_session`.
    """
    engine = ContextGCEngine(
        session_id=session_id or "contextgc", invariants=invariants, schema=schema
    )
    result = engine.process_session(
        messages, query_for_jit=recall_query, mode=mode, teach_protocol=teach_protocol
    )
    return result["cleaned_messages"], result["telemetry"]


def compile_transcript(
    text: str,
    mode: str = "compact",
    invariants: Optional[List[str]] = None,
    recall_query: Optional[str] = None,
    teach_protocol: bool = False,
    schema: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[str]]:
    """
    Compile a pasted plain-text transcript.

    Accepts either JSON (an OpenAI message array) or the line-oriented form::

        user: deliver to Tower B, Flat 402. Severe peanut allergy.
        assistant: Confirmed.
        tool: TOOL_OUTPUT [inventory] {"items": [...]}

    Returns ``(compiled_messages, telemetry, parse_warnings)``.
    """
    messages, warnings = parse_transcript(text)
    if not messages:
        return [], {
            "error": "no messages parsed",
            "parse_warnings": warnings,
        }, warnings

    compiled, telemetry = compile_messages(
        messages, mode=mode, invariants=invariants, recall_query=recall_query,
        teach_protocol=teach_protocol, schema=schema,
    )
    return compiled, telemetry, warnings


def patch_openai(
    client: Any,
    mode: str = "compact",
    invariants: Optional[List[str]] = None,
    teach_protocol: bool = False,
) -> Any:
    """
    Wrap ``client.chat.completions.create`` so outgoing message histories are
    compiled first. The response carries the telemetry as ``.context_gc``.

    Set ``teach_protocol=True`` to have the agent declare its own state changes.
    The declared facts are authoritative and carry provenance, which is what
    lets the compiler retire a superseded turn without stranding a value the
    turn uniquely held.

    Works with both ``openai.OpenAI`` and ``openai.AsyncOpenAI``.

    .. warning::
       This rewrites the messages actually sent upstream. Compile in a dry run
       first (``compile_messages``) and read ``telemetry`` before you trust it
       on a live agent -- the state tracker is regex-based and will miss
       assertions it cannot pattern-match. See the README's Limitations section.
    """
    original_create = client.chat.completions.create

    def _compile(messages):
        return compile_messages(
            messages, mode=mode, invariants=invariants, teach_protocol=teach_protocol
        )

    @functools.wraps(original_create)
    def wrapped_create(*args, **kwargs):
        messages = kwargs.get("messages")
        if messages:
            kwargs["messages"], telemetry = _compile(messages)
            response = original_create(*args, **kwargs)
            try:
                response.context_gc = telemetry
            except Exception:
                pass
            return response
        return original_create(*args, **kwargs)

    @functools.wraps(original_create)
    async def async_wrapped_create(*args, **kwargs):
        messages = kwargs.get("messages")
        if messages:
            kwargs["messages"], telemetry = _compile(messages)
            response = await original_create(*args, **kwargs)
            try:
                response.context_gc = telemetry
            except Exception:
                pass
            return response
        return await original_create(*args, **kwargs)

    import inspect
    if inspect.iscoroutinefunction(original_create):
        client.chat.completions.create = async_wrapped_create
    else:
        client.chat.completions.create = wrapped_create
    return client
