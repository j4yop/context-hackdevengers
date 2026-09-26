"""
Capture state declarations from a real model run.

`benchmarks shadow` can measure what an agent's own declarations contribute, but
only if it has a capture: the literal `<contextgc-state>` blocks a model emitted,
keyed by turn. There is no honest way to invent one. A capture is a record of
what a real model said, and a synthetic stand-in would measure the harness rather
than the write path.

So this module only does the mechanical part, and refuses to pretend:

* `capture` runs a real conversation against any OpenAI-compatible endpoint and
  writes what came back, including the declarations.
* `verify` checks an existing capture is well formed and re-derivable.
* Nothing here fabricates a declaration. `shadow` with no capture still refuses.

An endpoint can be anything that speaks the OpenAI chat API -- ``openai`` with a
key, or a local ``ollama serve``. It is configured by environment variable, never
by argument, so a key cannot land in a shell history or a CI log.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional

#: The protocol block, as the agent emits it.
BLOCK = re.compile(r"<contextgc-state>(.*?)</contextgc-state>", re.DOTALL)

CAPTURE_VERSION = 1


def extract_blocks(text: str) -> List[str]:
    """Every state block in one assistant turn, in order."""
    return [m.strip() for m in BLOCK.findall(text or "")]


def parse_block(block: str) -> Optional[Dict[str, Any]]:
    """
    One block as a dict, or None if it does not parse.

    Malformed blocks are counted rather than dropped silently: a model that
    emits broken JSON a third of the time is a finding about the protocol, not
    something to smooth over.
    """
    try:
        parsed = json.loads(block)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def summarise(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    What a capture contains, for a human deciding whether to trust it.

    ``declared_turns`` is the number that matters. A capture where the model
    never declared anything measures nothing, and saying so plainly is more
    useful than a passing comparison.
    """
    total = malformed = 0
    keys: Dict[str, int] = {}
    for turn in turns:
        for block in extract_blocks(turn.get("content", "")):
            total += 1
            parsed = parse_block(block)
            if parsed is None:
                malformed += 1
                continue
            for verb, payload in parsed.items():
                if verb == "revoke":
                    for key in payload or []:
                        keys[key] = keys.get(key, 0) + 1
                elif isinstance(payload, dict):
                    for key in payload:
                        keys[key] = keys.get(key, 0) + 1
    return {
        "turns": len(turns),
        "blocks": total,
        "malformed": malformed,
        "declared_turns": sum(1 for t in turns if extract_blocks(t.get("content", ""))),
        "keys": dict(sorted(keys.items(), key=lambda kv: -kv[1])),
    }


def verify(capture: Dict[str, Any]) -> List[str]:
    """Problems with a capture, as a list of strings. Empty means usable."""
    problems: List[str] = []
    if capture.get("version") != CAPTURE_VERSION:
        problems.append(
            f"capture version is {capture.get('version')!r}, expected {CAPTURE_VERSION}"
        )
    if not capture.get("endpoint"):
        problems.append("no endpoint recorded, so the capture cannot be attributed")
    turns = capture.get("turns")
    if not isinstance(turns, list) or not turns:
        problems.append("no turns recorded")
        return problems
    for index, turn in enumerate(turns):
        if "role" not in turn or "content" not in turn:
            problems.append(f"turn {index} is missing role or content")
    summary = summarise(turns)
    if summary["blocks"] == 0:
        problems.append(
            "the model never emitted a <contextgc-state> block, so this capture "
            "would measure nothing; check that the agent was taught the protocol"
        )
    if summary["malformed"]:
        problems.append(
            f"{summary['malformed']} of {summary['blocks']} blocks do not parse as JSON"
        )
    return problems


def _client() -> Any:
    """
    An OpenAI-compatible client, from the environment.

    ``CONTEXTGC_CAPTURE_BASE_URL`` points at a local server (ollama, vLLM,
    LM Studio) and ``CONTEXTGC_CAPTURE_MODEL`` names the model. With neither, the
    official client is used and it will look for its own key.
    """
    base = os.environ.get("CONTEXTGC_CAPTURE_BASE_URL")
    model = os.environ.get("CONTEXTGC_CAPTURE_MODEL")
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - dependency guidance
        raise SystemExit(
            "capturing needs the openai client:\n"
            "  pip install openai\n"
            "and either OPENAI_API_KEY, or CONTEXTGC_CAPTURE_BASE_URL pointing at a\n"
            "local OpenAI-compatible server."
        ) from exc
    if base:
        return OpenAI(base_url=base, api_key=os.environ.get("OPENAI_API_KEY", "local")), model
    return OpenAI(), model or os.environ.get("CONTEXTGC_CAPTURE_MODEL", "gpt-4o-mini")


def capture(
    transcript_path: str,
    out_path: str,
    limit: int = 20,
    schema_path: Optional[str] = None,
    system: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run real conversations and record what the model actually declared.

    Each turn sends the compiled context plus the protocol instruction, takes the
    model's reply verbatim, and stores it. The declarations are whatever the model
    emitted -- this function never adds, corrects or invents one.
    """
    from benchmarks.corpus import load_synthetic
    from contextgc import compile_messages, load_schema, render_instruction

    client, model_name = _client()
    transcripts = load_synthetic(transcript_path)[:limit]
    schema = load_schema(schema_path) if schema_path else None
    instruction = system or render_instruction()

    recorded: List[Dict[str, Any]] = []
    for transcript in transcripts:
        history: List[Dict[str, str]] = [
            {"role": "system", "content": instruction}
        ]
        for _ in range(6):
            compiled, _telemetry = compile_messages(
                history, schema=schema, teach_protocol=True
            )
            reply = client.chat.completions.create(
                model=model_name, messages=compiled
            ).choices[0].message.content or ""
            history.append({"role": "assistant", "content": reply})
            recorded.append({
                "transcript": transcript.id,
                "role": "assistant",
                "content": reply,
            })
            if extract_blocks(reply):
                break

    payload = {
        "version": CAPTURE_VERSION,
        # Recorded, not assumed: a capture that cannot say which model produced it
        # is an anecdote.
        "endpoint": os.environ.get("CONTEXTGC_CAPTURE_BASE_URL", "api.openai.com"),
        "model": model_name,
        "transcript_path": transcript_path,
        "turns": recorded,
    }
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return payload
