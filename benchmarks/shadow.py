"""
Shadow mode: run both paths and report where they disagree.

The question this exists to answer is narrow and testable:

    **When an agent declares its state, does that declaration add information the
    read path did not already have -- and does it ever contradict it?**

Shadow mode is deliberately incapable of making things worse. It never applies a
declaration to the emitted context. It compiles twice, once with the read path
alone and once with the declarations visible, and reports the difference. The
output you would send to a model is always the read-path compile.

That constraint is the point. The previous review established that a stale
declaration silently outranks a human's plain-text correction, so any measurement
loop that *trusts* declarations would be measuring a system that can be made
wrong by a cooperating model. Shadow mode measures without that exposure.
"""

from typing import Any, Callable, Dict, List, Optional

#: A declaration source takes (index, role, content) and returns a protocol
#: block string, or None. Kept as a callable so the harness does not care whether
#: declarations come from a model, a replay file, or a hand-written fixture.
DeclarationSource = Callable[[int, str, str], Optional[str]]


def replay_source(declarations: Dict[int, str]) -> DeclarationSource:
    """
    Replay declarations captured from a real run, keyed by turn index.

    This is how the harness measures a model's contribution without a model in
    the loop: capture once with a real model, replay deterministically forever.
    Captures are stored as files, so the measurement is reproducible and does not
    require the model to still be available.
    """

    def source(index: int, role: str, content: str) -> Optional[str]:
        if role != "assistant":
            return None
        return declarations.get(index)

    return source


def model_source(call_model: Callable[[str], str]) -> DeclarationSource:
    """Ask a caller-supplied callable to emit a block for a turn."""

    def source(index: int, role: str, content: str) -> Optional[str]:
        if role != "assistant":
            return None
        return call_model(content)

    return source


def shadow_compare(
    messages: List[Dict[str, Any]],
    source: DeclarationSource,
    invariants: Optional[List[str]] = None,
    schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compile ``messages`` with and without declarations, and diff the two states.

    Returns:
        ``baseline``       read-path state
        ``with_decl``      state after declarations were visible
        ``added``          keys only the declaration produced
        ``changed``        keys where the declaration disagreed with the read path
        ``agreed``         keys where both produced the same value
        ``conflicts``      the compiler's own conflict report
        ``emitted``        the context you would actually send (read-path only)

    ``schema`` enables entity patterns on both sides. It is required for the
    comparison to mean anything: the library ships an empty schema, so without one
    the read path finds nothing and every declaration trivially "adds" a key.

    ``added`` and ``changed`` are the whole measurement. ``added`` is the upside:
    facts the read path could not see. ``changed`` is the risk, and each entry
    names both values so a human can adjudicate.
    """
    from contextgc.client import compile_messages

    baseline_messages, baseline = compile_messages(
        messages, invariants=invariants, schema=schema
    )
    augmented = inject_declarations(messages, source)
    _, with_decl = compile_messages(augmented, invariants=invariants, schema=schema)

    base_state = dict(baseline["active_state_slots"])
    decl_state = dict(with_decl["active_state_slots"])

    added = {k: v for k, v in decl_state.items() if k not in base_state}
    changed = {
        k: {"read_path": base_state[k], "declared": decl_state[k]}
        for k in base_state
        if k in decl_state and str(base_state[k]) != str(decl_state[k])
    }
    agreed = {
        k: v for k, v in decl_state.items()
        if k in base_state and str(base_state[k]) == str(decl_state[k])
    }

    return {
        "baseline_state": base_state,
        "declared_state": decl_state,
        "added": added,
        "changed": changed,
        "agreed": agreed,
        "conflicts": with_decl.get("conflicts", []),
        "declared_share": with_decl["declarations"]["declared_share"],
        # The read-path compile is what gets emitted. Shadow mode never lets a
        # declaration into the context it hands back.
        "emitted": baseline_messages,
        "verdict": _verdict(added, changed, agreed),
    }


def inject_declarations(
    messages: List[Dict[str, Any]],
    source: DeclarationSource,
) -> List[Dict[str, Any]]:
    """Return a copy of ``messages`` with declarations spliced into assistant turns."""
    out = []
    for index, message in enumerate(messages):
        message = dict(message)
        block = source(index, message.get("role", "user"), message.get("content", "") or "")
        if block:
            message["content"] = (message.get("content") or "") + "\n" + block
        out.append(message)
    return out


def _verdict(added: Dict, changed: Dict, agreed: Dict) -> str:
    """
    A one-word summary, stated conservatively.

    Deliberately does not score the declaration. "helpfully different" would be a
    quality judgement this function cannot make: it cannot tell whether an added
    fact is true, only that the read path did not have it. Adjudicating truth
    needs a labelled sample, which is what ``gold.py`` is for.
    """
    if not added and not changed:
        return "no effect"
    if added and not changed:
        return f"added {len(added)} key(s), agreed on the rest"
    if changed and not added:
        return f"disagreed on {len(changed)} key(s), added none"
    return f"added {len(added)}, disagreed on {len(changed)}"


def run_corpus(
    transcripts: List[Any],
    source_for: Callable[[Any], DeclarationSource],
    invariants: Optional[List[str]] = None,
    schema: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Run shadow comparison across a corpus and aggregate."""
    rows: List[Dict[str, Any]] = []
    for transcript in transcripts:
        if limit and len(rows) >= limit:
            break
        try:
            outcome = shadow_compare(
                transcript.messages, source_for(transcript),
                invariants=invariants, schema=schema,
            )
        except Exception as exc:
            rows.append({
                "id": transcript.id,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        rows.append({
            "id": transcript.id,
            "turns": transcript.n_turns,
            "verdict": outcome["verdict"],
            "added": outcome["added"],
            "changed": outcome["changed"],
            "agreed_count": len(outcome["agreed"]),
            "conflicts": len(outcome["conflicts"]),
            "declared_share": outcome["declared_share"],
        })

    ok = [r for r in rows if "error" not in r]
    n = len(ok)
    return {
        "n": n,
        "errors": len(rows) - n,
        "transcripts_with_added_facts": sum(1 for r in ok if r["added"]),
        "transcripts_with_changed_facts": sum(1 for r in ok if r["changed"]),
        "transcripts_with_any_effect": sum(
            1 for r in ok if r["added"] or r["changed"]
        ),
        "total_added": sum(len(r["added"]) for r in ok),
        "total_changed": sum(len(r["changed"]) for r in ok),
        "total_agreed": sum(r["agreed_count"] for r in ok),
        "rows": rows,
    }
