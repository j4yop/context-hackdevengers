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

import json
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from contextgc import __version__
from contextgc.client import compile_messages, compile_transcript
from contextgc.gc_engine import ContextGCEngine
from contextgc.state_protocol import render_instruction
from contextgc.transcript import parse_transcript

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

#: The only files the site is allowed to serve, by the name they are requested
#: under. A set of names rather than a directory listing, so a file added to
#: ``web/`` later is unreachable until someone decides it should not be, and a
#: path is never built from user input at all.
WEB_PAGES = {
    "index.html": "/",
    "console.html": "/console",
    "style.css": "/style.css",
}


def _web_page(name: str) -> Any:
    """Serve one named page from ``web/``, or say exactly what is missing."""
    if name not in WEB_PAGES:
        raise HTTPException(status_code=404, detail=f"{name} is not a served page")
    path = os.path.join(WEB_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail=f"web/{name} not found; the site is served from {WEB_DIR}",
        )
    media = "text/css" if name.endswith(".css") else "text/html"
    return FileResponse(
        path,
        media_type=f"{media}; charset=utf-8",
        # The pages were split after this was last set, and a cached document
        # naming a stylesheet that no longer exists is a blank page rather than
        # a stale one. HTML is revalidated; the stylesheet is not.
        headers={"Cache-Control": "no-cache"},
    )

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
    entity_schema: Optional[str] = Field(
        None, description="Name of a shipped entity schema. Required for state tracking to do anything."
    )
    declaration_policy: str = Field(
        "flag",
        pattern="^(flag|reject|off)$",
        description=(
            "What to do with a declared key the schema does not define. 'flag' "
            "keeps it and reports it in telemetry; 'reject' drops it. Only has an "
            "effect when entity_schema is set."
        ),
    )


class MessagesRequest(BaseModel):
    messages: List[Dict[str, Any]]
    mode: str = Field("compact", pattern="^(compact|cache_friendly)$")
    invariants: List[str] = Field(default_factory=list)
    recall_query: Optional[str] = None
    teach_protocol: bool = False
    entity_schema: Optional[str] = None
    declaration_policy: str = Field(
        "flag",
        pattern="^(flag|reject|off)$",
        description=(
            "What to do with a declared key the schema does not define. 'flag' "
            "keeps it and reports it in telemetry; 'reject' drops it. Only has an "
            "effect when entity_schema is set."
        ),
    )


# --------------------------------------------------------------------------
# The product
# --------------------------------------------------------------------------


#: Shipped entity schemas, loaded from the installed package at import time.
#:
#: The library's default schema is empty, so a caller who wants state tracking
#: must pick a domain. Exposing the list here is what lets the website offer the
#: choice instead of silently showing an empty state DAG.
def _load_schemas() -> Dict[str, Dict[str, Any]]:
    """Read the schemas out of the installed package.

    This used to reach into ``../benchmarks/schemas``, which meant the deployed
    site depended on the repository layout rather than on its own dependency, and
    an installed wheel had no schemas at all. The library owns them now.
    """
    from contextgc.schemas import list_schemas, schema_summary

    out: Dict[str, Dict[str, Any]] = {}
    for name in list_schemas():
        try:
            out[name] = schema_summary(name)
        except (OSError, ValueError):  # pragma: no cover - broken install
            continue
    return out


SCHEMAS = _load_schemas()


def _entities_for(name: Optional[str]) -> Optional[Dict[str, Any]]:
    """Resolve a schema name to an entities mapping, or None for the empty default."""
    if not name:
        return None
    entry = SCHEMAS.get(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown schema {name!r}; have {sorted(SCHEMAS)}")
    from contextgc.schemas import schema_path

    path = schema_path(name)
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    entities = dict(raw.get("entities", {}))
    if raw.get("__immutable__"):
        entities["__immutable__"] = tuple(raw["__immutable__"])
    return entities


@app.get("/api/schemas")
def list_schemas() -> Dict[str, Any]:
    """The domain schemas a caller can opt into. The default is empty, by design."""
    return {
        "default": None,
        "default_note": (
            "contextgc ships an empty entity schema. The default it replaced matched prose "
            "in unrelated domains; see the README. Pick one to enable state tracking."
        ),
        "schemas": list(SCHEMAS.values()),
    }


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "contextgc",
        "version": __version__,
        "proxy_configured": bool(UPSTREAM_KEY),
        "schemas": sorted(SCHEMAS),
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
        schema=_entities_for(req.entity_schema),
        declaration_policy=req.declaration_policy,
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
        schema=_entities_for(req.entity_schema),
        declaration_policy=req.declaration_policy,
    )
    return JSONResponse(
        content={"compiled_messages": compiled, "telemetry": telemetry},
        headers={"Cache-Control": "no-store"},
    )


class InstructionRequest(BaseModel):
    transcript: str
    mode: str = "compact"


@app.post("/api/protocol-instruction")
async def api_protocol_instruction(req: InstructionRequest) -> Dict[str, Any]:
    """
    The exact state-protocol instruction the engine would inject for this input.

    The website links here rather than showing a hardcoded sample, which used to
    diverge from the real string -- the same "hardcoded number that does not
    match reality" defect the audit found in the benchmarks.
    """
    messages, _ = parse_transcript(req.transcript)
    if not messages:
        return {"instruction": "", "keys": []}
    engine = ContextGCEngine()
    engine.process_session(messages, mode=req.mode)
    keys = sorted(engine.dag.active_state)[:12]
    return {"instruction": render_instruction(keys), "keys": keys}


@app.get("/api/example")
def example() -> Dict[str, Any]:
    """
    A short transcript that actually exercises supersession.

    The content lives in ``server/example.py`` because it is data rather than
    logic, and because its correctness is easy to break in a way nothing else
    notices: an example written for schemas that measurement has since replaced
    still loads, still compiles, and demonstrates nothing at all.
    """
    from .example import example as build

    payload = build()
    payload["protocol_help"] = render_instruction(["active_reservation", "cabin_class"])
    return payload


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
    return _web_page("index.html")


@app.get("/console")
def console() -> Any:
    return _web_page("console.html")


@app.get("/style.css")
def stylesheet() -> Any:
    return _web_page("style.css")


@app.get("/favicon.ico")
def favicon() -> Any:
    return JSONResponse(status_code=204, content=None)
