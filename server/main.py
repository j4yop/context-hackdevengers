"""
contextgc HTTP server.

Two surfaces, deliberately unequal in importance:

* ``POST /api/compile`` -- the real product. Compiles a transcript you supply
  and returns the compiled context plus measured telemetry. Stateless, no API
  key, no model call, nothing persisted.

* ``POST /v1/chat/completions`` -- an optional OpenAI-shaped pass-through proxy.
  It **requires** a server-side ``CONTEXTGC_UPSTREAM_KEY`` and **refuses** to
  invent a response when one is absent. It never accepts a caller's key: a
  public endpoint that forwards caller-supplied credentials, or silently spends
  the operator's key for anonymous callers, is not a feature.

There is no endpoint that fabricates an "LLM response" to make a demo look
busy. The previous version of this file had one; it is the reason this project
could not be taken seriously.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from contextgc import __version__
from contextgc.client import compile_messages, compile_transcript
from contextgc.state_protocol import render_instruction

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

#: Hard cap on a submitted transcript. Bounds memory and parse time.
MAX_BODY_BYTES = 256 * 1024

#: Comma-separated allowed origins. Defaults to same-origin only -- the previous
#: value was `allow_origins=["*"]` together with `allow_credentials=True`, which
#: is both broken and an invitation to abuse.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CONTEXTGC_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]

#: Present only if the operator explicitly configured a real upstream.
UPSTREAM_KEY = os.environ.get("CONTEXTGC_UPSTREAM_KEY", "").strip()
UPSTREAM_BASE = os.environ.get(
    "CONTEXTGC_UPSTREAM_BASE", "https://api.openai.com/v1"
).rstrip("/")
UPSTREAM_MODEL = os.environ.get("CONTEXTGC_UPSTREAM_MODEL", "gpt-4o-mini")

#: Simple fixed-window rate limit, per client IP.
RATE_LIMIT = int(os.environ.get("CONTEXTGC_RATE_LIMIT", "60"))
RATE_WINDOW_S = 60.0
_hits: Dict[str, List[float]] = {}


def _rate_limited(client: str) -> bool:
    now = time.time()
    window = [t for t in _hits.get(client, []) if now - t < RATE_WINDOW_S]
    if len(window) >= RATE_LIMIT:
        _hits[client] = window
        return True
    window.append(now)
    _hits[client] = window
    # Opportunistic cleanup so the dict cannot grow without bound.
    if len(_hits) > 4096:
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW_S]:
            _hits.pop(k, None)
    return False


app = FastAPI(
    title="contextgc",
    version=__version__,
    description="Deterministic context compiler for AI agent transcripts.",
)

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class CompileRequest(BaseModel):
    transcript: str = Field(..., description="Plain-text transcript or JSON message array")
    mode: str = Field("compact", pattern="^(compact|cache_friendly)$")
    invariants: List[str] = Field(default_factory=list)
    recall_query: Optional[str] = None
    teach_protocol: bool = Field(
        False, description="Inject the state-protocol instruction so the agent declares its state"
    )


class MessagesRequest(BaseModel):
    messages: List[Dict[str, Any]]
    mode: str = Field("compact", pattern="^(compact|cache_friendly)$")
    invariants: List[str] = Field(default_factory=list)
    recall_query: Optional[str] = None
    teach_protocol: bool = False


# --------------------------------------------------------------------------
# The product
# --------------------------------------------------------------------------


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "contextgc",
        "version": __version__,
        "proxy_configured": bool(UPSTREAM_KEY),
    }


@app.post("/api/compile")
async def api_compile(req: CompileRequest, request: Request) -> JSONResponse:
    """Compile a transcript. Stateless: nothing is stored, no key required."""
    if _rate_limited(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="rate limit exceeded")

    if len(req.transcript.encode("utf-8")) > MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"transcript exceeds {MAX_BODY_BYTES // 1024} KiB",
        )

    compiled, telemetry, warnings = compile_transcript(
        req.transcript,
        mode=req.mode,
        invariants=req.invariants or None,
        recall_query=req.recall_query,
        teach_protocol=req.teach_protocol,
    )

    if "error" in telemetry:
        return JSONResponse(
            status_code=422,
            content={"error": telemetry["error"], "parse_warnings": warnings},
            headers={"Cache-Control": "no-store"},
        )

    return JSONResponse(
        content={
            "compiled_messages": compiled,
            "telemetry": telemetry,
            "parse_warnings": warnings,
        },
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/compile/messages")
async def api_compile_messages(req: MessagesRequest, request: Request) -> JSONResponse:
    """Same as /api/compile but takes a JSON message array directly."""
    if _rate_limited(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    if not req.messages:
        raise HTTPException(status_code=422, detail="messages must not be empty")

    compiled, telemetry = compile_messages(
        req.messages,
        mode=req.mode,
        invariants=req.invariants or None,
        recall_query=req.recall_query,
        teach_protocol=req.teach_protocol,
    )
    return JSONResponse(
        content={"compiled_messages": compiled, "telemetry": telemetry},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/example")
def example() -> Dict[str, Any]:
    """A short transcript that actually exercises supersession."""
    return {
        "transcript": "\n".join([
            "system: You are a delivery support agent.",
            "user: Please deliver order ORD-9941 to Tower B, Flat 402. I have a severe peanut allergy.",
            'tool [inventory]: {"items": [{"name": "Toned Milk 500ml", "price": 28}, {"name": "Whole Milk 1L", "price": 34}, {"name": "Paneer 200g", "price": 95}, {"name": "Biscuits", "price": 40}, {"name": "Tea 250g", "price": 120}, {"name": "Coffee 100g", "price": 250}, {"name": "Peanut Butter 500g", "price": 199, "warning": "PEANUT_ALLERGEN"}, {"name": "Rice 1kg", "price": 60}, {"name": "Dal 1kg", "price": 140}, {"name": "Sugar 1kg", "price": 45}, {"name": "Salt 1kg", "price": 28}, {"name": "Oil 1L", "price": 130}, {"name": "Soap", "price": 55}, {"name": "Shampoo", "price": 210}, {"name": "Toothpaste", "price": 95}]}',
            "assistant: Confirmed order ORD-9941, routing to Tower B, Flat 402. Peanut allergy noted.",
            "user: Actually the elevator in Tower B is broken. Deliver to the Clubhouse security desk instead.",
            "assistant: Updated. Delivery is now routed to the Clubhouse security desk.",
            "user: Wait, my friend is at Gate 2 security entrance right now. Reroute there. Entry code 4921.",
            "assistant: Rerouted to Gate 2 security entrance, code 4921.",
            "user: Thanks.",
        ]),
        "write_path_example": "\n".join([
            "system: You are a delivery support agent.",
            "user: Deliver ORD-9941 to Tower B, Flat 402. Severe peanut allergy.",
            "assistant: Confirmed, routing to Tower B.\n<contextgc-state>{\"assert\":{\"order_id\":\"ORD-9941\",\"destination_address\":\"Tower B, Flat 402\"},\"pin\":{\"dietary_allergy\":\"peanut\"}}</contextgc-state>",
            "user: The elevator is broken. Send it to the new place instead.",
            "assistant: Moved to the Clubhouse security desk.\n<contextgc-state>{\"assert\":{\"destination_address\":\"Clubhouse security desk\"}}</contextgc-state>",
            "user: Actually my friend is at Gate 2. Reroute there, code 4921.",
            "assistant: Rerouted.\n<contextgc-state>{\"assert\":{\"destination_address\":\"Gate 2\",\"gate_code\":\"4921\"}}</contextgc-state>",
            "user: Wait, the order was cancelled.",
            "assistant: Cancelled.\n<contextgc-state>{\"revoke\":[\"gate_code\",\"order_id\"]}</contextgc-state>",
            "user: OK.",
        ]),
        "protocol_help": render_instruction([
            "destination_address", "gate_code", "order_id", "dietary_allergy",
        ]),
    }


# --------------------------------------------------------------------------
# Optional proxy
# --------------------------------------------------------------------------


@app.get("/v1/models")
def models() -> Dict[str, Any]:
    if not UPSTREAM_KEY:
        raise HTTPException(
            status_code=503,
            detail="proxy not configured. Set CONTEXTGC_UPSTREAM_KEY on the server, "
                   "or use POST /api/compile which needs no key.",
        )
    return {"object": "list", "data": [{"id": UPSTREAM_MODEL, "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat_completions(req: Request) -> Any:
    """
    Compile the incoming history, then forward to a real upstream model.

    Refuses rather than fabricating. If you are integrating an agent against
    this endpoint, a 503 means the operator has not configured a key -- it does
    not mean you received a model response.
    """
    if not UPSTREAM_KEY:
        raise HTTPException(
            status_code=503,
            detail="No upstream model configured. This endpoint proxies to a real LLM and "
                   "will not synthesise a response. Use POST /api/compile instead.",
        )

    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="body must be JSON")

    messages = body.get("messages") or []
    if not messages:
        raise HTTPException(status_code=422, detail="'messages' is required")

    stream = bool(body.get("stream"))
    mode = body.get("mode", "compact")

    compiled, telemetry = compile_messages(messages, mode=mode)
    payload = {
        "model": body.get("model") or UPSTREAM_MODEL,
        "messages": compiled,
        "stream": stream,
    }
    for passthrough in ("temperature", "max_tokens", "top_p", "stop"):
        if body.get(passthrough) is not None:
            payload[passthrough] = body[passthrough]

    headers = {
        "Authorization": f"Bearer {UPSTREAM_KEY}",
        "Content-Type": "application/json",
    }
    telemetry_header = (
        f"raw={telemetry['raw_token_count']}; compiled={telemetry['compiled_token_count']}; "
        f"saved={telemetry['compression_ratio_pct']}%; "
        f"compile_ms={telemetry['compile_time_ms']}"
    )

    try:
        if not stream:
            import httpx

            async with httpx.AsyncClient(timeout=120.0) as client:
                upstream = await client.post(
                    f"{UPSTREAM_BASE}/chat/completions",
                    json=payload,
                    headers=headers,
                )
            return JSONResponse(
                content=upstream.json(),
                status_code=upstream.status_code,
                headers={"X-ContextGC-Telemetry": telemetry_header},
            )

        async def relay() -> Any:
            import httpx

            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    f"{UPSTREAM_BASE}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as upstream:
                    async for chunk in upstream.aiter_bytes():
                        yield chunk

        return StreamingResponse(
            relay(),
            media_type="text/event-stream",
            headers={"X-ContextGC-Telemetry": telemetry_header, "Cache-Control": "no-store"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"upstream request failed: {exc}")


# --------------------------------------------------------------------------
# Static site
# --------------------------------------------------------------------------


@app.get("/")
def index() -> Any:
    path = os.path.join(WEB_DIR, "index.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="web/index.html not found")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico")
def favicon() -> Any:
    return JSONResponse(status_code=204, content=None)
