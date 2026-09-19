"""
ContextGC: Zero-Overhead Python Client SDK & OpenAI Monkey-Patcher
Enables 1-line client-side context defragmentation without running a local proxy server.

Usage:
    from core.client import defrag_context, patch_openai
    import openai

    # 1. Direct Functional Defrag
    clean_messages, telemetry = defrag_context(messages)

    # 2. Transparent OpenAI SDK Auto-Patcher
    client = openai.OpenAI()
    patch_openai(client)
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
"""

from typing import List, Dict, Any, Tuple, Optional
import functools
from .gc_engine import ContextGCEngine

def defrag_context(
    messages: List[Dict[str, Any]],
    mode: str = "compact",
    session_id: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Directly defragments a multi-turn message history in Python memory.
    
    Args:
        messages: List of message dictionaries (OpenAI format: role, content, name, tool_calls)
        mode: "compact" (max token reduction) or "cache_friendly" (preserves KV-cache prefixes)
        session_id: Optional session identifier for episodic tracking
        
    Returns:
        (cleaned_messages, telemetry)
    """
    engine = ContextGCEngine(session_id=session_id or "CLIENT-SDK-01")
    res = engine.process_session(messages, mode=mode)
    return res["cleaned_messages"], res["telemetry"]

def patch_openai(client: Any, mode: str = "compact") -> Any:
    """
    Transparently patches an openai.OpenAI or AsyncOpenAI client instance
    so that client.chat.completions.create(...) automatically defragments context.
    Attaches `response.context_gc` containing token savings telemetry.
    """
    original_create = client.chat.completions.create

    @functools.wraps(original_create)
    def wrapped_create(*args, **kwargs):
        messages = kwargs.get("messages", [])
        if messages:
            cleaned_messages, telemetry = defrag_context(messages, mode=mode)
            kwargs["messages"] = cleaned_messages
            response = original_create(*args, **kwargs)
            # Attach defrag telemetry if response is an object
            try:
                setattr(response, "context_gc", telemetry)
            except Exception:
                pass
            return response
        return original_create(*args, **kwargs)

    @functools.wraps(original_create)
    async def async_wrapped_create(*args, **kwargs):
        messages = kwargs.get("messages", [])
        if messages:
            cleaned_messages, telemetry = defrag_context(messages, mode=mode)
            kwargs["messages"] = cleaned_messages
            response = await original_create(*args, **kwargs)
            try:
                setattr(response, "context_gc", telemetry)
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
