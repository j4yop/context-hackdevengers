"""
Build a worksheet a human can label, and read the verdicts back.

Coverage is free and precision is not, so the limiting factor on every precision
number in this project is how fast a person can read an extraction in context and
say whether it is true. This module removes everything except that act:

    python -m benchmarks.label_worksheet coding --per-entity 12
    # ... a human fills in "verdict" on each row ...
    python -m benchmarks.label_worksheet coding --merge worksheet.json

Three things it does that hand-picking does not.

**It spreads the budget across slots.** All 39 committed labels are
``current_file``, so the reported 100% says nothing about the other eight slots
the library ships. A fixed budget spent on whichever slot is easiest to sample
reproduces that exactly, and the number stays a statement about one regex. The
worksheet samples round-robin across slots, so 12 per slot is 12 per slot.

**It quotes the turn.** Judging ``current_file = "dispatcher.py"`` needs the
surrounding prose -- the two "confirmed errors" this project once carried were
both mislabelled because the labeller read the value without the sentence that
said the agent had moved on. Each row carries the registering turn and its
neighbours, so the judgement is made on the same evidence a second labeller
would get.

**It will not invent a verdict.** Every row ships as ``unlabelled``. The merge
refuses anything still unlabelled, and records who labelled it, so a number can
never acquire a denominator that a person did not judge.

Rows are de-duplicated by value first and by transcript second, so a slot whose
values repeat across a hundred turns does not hand back a hundred judgements
about the same fact. Precision is scored over *independent units*
(``benchmarks.gold.clusters_of``) and inflating ``n`` with repeats was the
project's first precision bug.
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from benchmarks.corpus import load_apigen_mt, load_swe_agent
from benchmarks.loader_defaults import CLI_DEFAULTS
from contextgc import load_schema

#: The judgement the label files record, copied so a labeller is not asked to
#: invent a standard. It is also the standard the existing 39 labels were made
#: under, so new labels are comparable with old ones.
DOCTRINE = (
    "correct when the agent opens/edits/creates or restates this exact value at "
    "this turn. incorrect when the value is not something the agent acted on here. "
    "unclear when the turn genuinely does not settle it."
)

#: Characters of the registering turn quoted per row, and how many neighbouring
#: turns to include. Enough to judge from; not so much that a row is a page.
TURN_CHARS = 600
CONTEXT_TURNS = 1


def _extractions(schema_name: str, corpus: str, limit: int, corpus_path: Optional[str]):
    """
    Run the read path over a corpus and return its extractions.

    The corpus has to be the one `benchmarks run` will load, or the labels a
    person fills in will not match the extractions the report scores. It was not,
    and the failure is quiet and total:

        labels supplied        142
        matched an extraction  43
        ! 99 label(s) did not match any extraction.

    99 of 142 human judgements discarded, the second slot reported UNMEASURED,
    and a report that looked complete. The cause was one argument: this loader
    called `load_swe_agent(limit=...)` with `per_repo` at its default of `None`,
    which packs the window out of 13 repositories, while the CLI defaults to
    `per_repo=2` and spreads over 20. Different transcripts, so no label key
    could line up.

    So the CLI's defaults are read from the parser rather than restated here.
    Restating them is how the two drift apart again.
    """
    from benchmarks.harness import run

    if corpus == "swe-agent":
        transcripts = load_swe_agent(
            limit=limit, path=corpus_path,
            min_turns=CLI_DEFAULTS["min_turns"],
            per_repo=CLI_DEFAULTS["per_repo"],
        )
    else:
        transcripts = load_apigen_mt(
            limit=limit, path=corpus_path,
            domain="airline" if "airline" in corpus else "retail",
        )
    result = run(transcripts, schema=load_schema(schema_name), max_extractions=100000)
    return {t.id: t for t in transcripts}, result.extractions


def _quote(transcript, index: int) -> str:
    """The registering turn, trimmed, with its neighbours for context."""
    low, high = index - CONTEXT_TURNS, index + CONTEXT_TURNS + 1
    low, high = max(0, low), min(len(transcript.messages), high)
    parts = []
    for offset in range(low, high):
        message = transcript.messages[offset]
        marker = ">>>" if offset == index else "   "
        body = (message["content"] or "").strip().replace("\n", " ")
        if len(body) > TURN_CHARS:
            body = body[:TURN_CHARS] + " [...]"
        parts.append(f"{marker} [{offset}] {message['role']}: {body}")
    return "\n".join(parts)


def _turn_facts(transcript, index: int, value: str) -> Dict[str, Any]:
    """
    The mechanical evidence about one row, independent of any judgement.

    Every field here is a fact about the bytes: which turn the value appears in,
    whether that turn is the registering one, whether the turn is machine output,
    and whether the value is surrounded by a listing. They are recorded so a
    reviewer can check the suggestion instead of re-deriving it, and so a wrong
    suggestion is visible as a wrong fact rather than as an opinion.
    """
    facts: Dict[str, Any] = {"in_registering_turn": False, "in_neighbour": False}
    if transcript is None:
        return facts
    turn = index if 0 <= index < len(transcript.messages) else None
    if turn is not None:
        message = transcript.messages[turn]
        facts["registering_role"] = message["role"]
        facts["registering_is_machine_output"] = _is_machine_output(message["content"], message["role"])
        facts["in_registering_turn"] = value in (message["content"] or "")
    for offset in (index - 1, index + 1):
        if 0 <= offset < len(transcript.messages):
            if value in (transcript.messages[offset]["content"] or ""):
                facts["in_neighbour"] = True
                break
    return facts


def _is_machine_output(content: str, role: str) -> bool:
    from contextgc.sanitizer import ToolSanitizer

    return ToolSanitizer.looks_like_tool_output(content or "", role)


def suggest(rows: List[Dict[str, Any]], transcripts: Dict[str, Any],
            who: str = "contextgc label_worksheet (mechanical)") -> List[Dict[str, Any]]:
    """
    Attach a *suggestion* and its evidence to each row. Never a verdict.

    The suggestion is not a judgement and does not become one. ``verdict`` stays
    ``unlabelled``, the merge still refuses while it is, and nothing here is
    written to the label file -- so a reviewer can agree, disagree, or ignore
    every one of these and the resulting precision number is still theirs.

    The rules are deliberately mechanical and checkable:

    * the value is absent from the registering turn, or present only in a
      neighbouring turn, or the registering turn is machine output -> ``unclear``
      or ``incorrect`` with that stated as the reason
    * the value is in the registering turn and the turn is the agent's own
      speech -> ``correct``

    That is a text check, not an understanding of the conversation, which is the
    entire limitation: the "confirmed errors" this project once carried were all
    cases where the value was in the turn and the judgement was still wrong,
    because the agent had already moved on.
    """
    out = []
    for row in rows:
        value = row.get("value") or ""
        transcript = transcripts.get(row.get("transcript"))
        facts = _turn_facts(transcript, row.get("turn_index", 0), value)
        row = dict(row)
        row["mechanical_evidence"] = facts
        flags = []
        if not facts.get("in_registering_turn"):
            if facts.get("in_neighbour"):
                flags.append("value is in a NEIGHBOURING turn, not the registering one")
                suggestion = "incorrect"
            else:
                flags.append("value does not appear in the quoted turns at all")
                suggestion = "incorrect"
        elif facts.get("registering_is_machine_output"):
            flags.append("registering turn is machine output")
            suggestion = "unclear"
        else:
            suggestion = "correct"
        if facts.get("registering_role") == "user":
            # Not a warning. APIGen files the *customer's own speech* and its tool
            # results under the same `user` role, so the role alone cannot tell
            # them apart, and an earlier version of this flag said "user/tool
            # role" on 59 of 80 rows -- every one of which the sanitizer had
            # correctly classified as speech. The role is reported as a fact and
            # the classifier's answer is the one that counts.
            flags.append(
                f"role is 'user', which in this corpus is both the customer and "
                f"tool results; classified as "
                f"{'machine output' if facts.get('registering_is_machine_output') else 'speech'}"
            )
        row["triage_flags"] = flags
        row["model_suggestion"] = suggestion
        kind = "machine output" if facts.get("registering_is_machine_output") else "speech"
        row["model_reason"] = (
            f"{'value appears in' if facts.get('in_registering_turn') else 'value is absent from'} "
            f"turn {row.get('turn_index')} "
            f"(role {facts.get('registering_role', '?')}, {kind})"
        )
        row["model_suggested_by"] = who
        row["model_suggestion_is_not_a_verdict"] = True
        out.append(row)
    return out


def sample_rows(
    extractions: List[Dict[str, Any]],
    transcripts: Dict[str, Any],
    per_entity: int,
    already: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """
    Choose ``per_entity`` rows per slot, spread across slots.

    Split out from ``build`` so the sampling can be tested without a corpus: it
    is a policy -- round-robin across slots, one judgement per distinct value and
    per distinct transcript -- and a policy should not need a 5,000-row download
    to check.
    """
    already = already or set()
    by_entity: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    seen_value: Dict[str, set] = defaultdict(set)
    seen_transcript: Dict[str, set] = defaultdict(set)
    for item in sorted(
        extractions,
        key=lambda e: (e.get("transcript", ""), e.get("turn", 0)),
    ):
        entity = item.get("entity")
        value = item.get("value")
        transcript_id = item.get("transcript")
        if not entity or value is None or transcript_id is None:
            continue
        # The key is the same 4-tuple `benchmarks.gold.label_key` builds, so a row
        # a person already judged is not asked of them again. Comparing a 3-tuple
        # against the 4-tuple set silently matched nothing and the exclusion did
        # nothing at all.
        if (transcript_id, entity, value, item.get("turn")) in already:
            continue
        # One judgement per distinct value, and per transcript, so the sample
        # cannot be 12 rows about the same fact in the same file.
        if value in seen_value[entity]:
            continue
        if transcript_id in seen_transcript[entity]:
            continue
        seen_value[entity].add(value)
        seen_transcript[entity].add(transcript_id)
        by_entity[entity].append(item)

    rows: List[Dict[str, Any]] = []
    for rank in range(max((len(v) for v in by_entity.values()), default=0)):
        for entity in sorted(by_entity):
            pool = by_entity[entity]
            taken = len([r for r in rows if r["entity"] == entity])
            if rank >= len(pool) or taken >= per_entity:
                continue
            item = pool[rank]
            transcript = transcripts.get(item["transcript"])
            rows.append({
                "id": f"{len(rows) + 1:03d}",
                "entity": entity,
                "value": item["value"],
                "transcript": item["transcript"],
                "turn_index": item.get("turn"),
                "verdict": "unlabelled",
                "note": "",
                "labelled_by": "",
                "turn_in_context": _quote(transcript, item.get("turn", 0)) if transcript else "",
            })
    return rows


def starved_slots(counts: Dict[str, int], per_entity: int) -> Dict[str, int]:
    """
    Which slots got fewer rows than their budget, and by how many.

    Split out for the same reason ``sample_rows`` is: the ambiguity is a policy,
    and a policy should not need a 5,000-row download to check.

    A slot short of its budget means one of two things, and the difference
    matters more than the count. Either the transcript window never reached the
    slot's values, or the corpus has no more distinct ones. `failing_test` is
    the case that made this necessary: 49 distinct values across the shard, 2
    inside the default 60-transcript window. Two rows read as "this slot cannot
    be labelled", which is how a person comes to drop the slot and report
    coding precision as single-slot for good. So the shortfall is reported, and
    the cause is not guessed at -- raising ``--limit`` is what tells them apart.
    """
    return {e: per_entity - n for e, n in sorted(counts.items()) if n < per_entity}


def build(
    schema_name: str,
    corpus: str = "swe-agent",
    limit: int = 60,
    per_entity: int = 12,
    corpus_path: Optional[str] = None,
    already: Optional[set] = None,
    with_suggestions: bool = False,
) -> Dict[str, Any]:
    """
    A worksheet: ``per_entity`` unlabelled rows for each slot, spread across
    distinct values and distinct transcripts.
    """
    already = already or set()
    transcripts, extractions = _extractions(schema_name, corpus, limit, corpus_path)
    rows = sample_rows(extractions, transcripts, per_entity, already)
    for row in rows:
        row["schema"] = schema_name
    if with_suggestions:
        rows = suggest(rows, transcripts)
    counts = Counter(r["entity"] for r in rows)
    starved = starved_slots(counts, per_entity)
    return {
        "instructions": (
            "For each row, read the turn in context and set `verdict` to correct, "
            "incorrect, or unclear. Fill in `note` with why, and `labelled_by` with "
            "who read it. Then: python -m benchmarks.label_worksheet "
            f"{schema_name} --merge <this file>"
        ),
        "doctrine": DOCTRINE,
        "corpus": corpus,
        "limit": limit,
        "loader_defaults": dict(CLI_DEFAULTS),
        "per_entity": per_entity,
        "rows": len(rows),
        "entities": dict(counts),
        "starved_slots": starved,
        "starved_note": (
            "these slots got fewer rows than --per-entity asked for. Either the "
            "transcript window was too small to reach their values, or the corpus "
            "has no more distinct ones. Raise --limit to tell which: "
            "`coding.failing_test` goes 2 -> 7 -> 21 -> 44 rows at limits "
            "60, 500, 2000, 6000."
            if starved else ""
        ),
        "labelled": 0,
        "suggestions_attached": bool(with_suggestions),
        "suggestions_are_verdicts": False,
        "suggestion_note": (
            "model_suggestion is a mechanical text check, not a judgement, and is "
            "not written to the label file. verdict is the human's."
            if with_suggestions else ""
        ),
        "items": rows,
    }


def merge(worksheet: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
    """
    Fold judged rows into the committed label file.

    Refuses while anything is unlabelled, and refuses a row whose quote is
    missing -- a judgement made without the turn in front of the labeller is how
    the two "confirmed errors" in this project were made.
    """
    from benchmarks.gold import LABELS_BY_SCHEMA, load_labels, save_labels

    items = worksheet.get("items", [])
    unlabelled = [i["id"] for i in items if i.get("verdict", "unlabelled") == "unlabelled"]
    if unlabelled:
        sys.exit(
            f"{len(unlabelled)} rows are still unlabelled ({unlabelled[:8]}"
            f"{'...' if len(unlabelled) > 8 else ''})\n"
            "  nothing is merged while a row has no verdict"
            + ("\n\n  a model_suggestion on a row is not a verdict and cannot fill it."
               if any(i.get("model_suggestion") for i in items) else "")
        )
    no_quote = [i["id"] for i in items if not i.get("turn_in_context")]
    if no_quote:
        sys.exit(
            f"{len(no_quote)} rows have no turn quoted ({no_quote[:8]})\n"
            "  rebuild the worksheet: a judgement made without the turn is not a label"
        )
    bad = [i["id"] for i in items
           if i.get("verdict") not in ("correct", "incorrect", "unclear")]
    if bad:
        sys.exit(f"unrecognised verdicts on rows {bad[:8]}")

    path = LABELS_BY_SCHEMA.get(schema_name)
    if not path:
        sys.exit(f"no label file is defined for schema {schema_name!r}")

    existing = load_labels(path)
    have = {(row.get("transcript"), row.get("entity"), row.get("value"), row.get("turn_index"))
            for row in existing}
    kf_path = os.path.join(os.path.dirname(path), "known_failures.json")
    corrected = set()
    if os.path.exists(kf_path):
        with open(kf_path, encoding="utf-8") as handle:
            kf = json.load(handle)
        corrected = {(c["transcript"], c["turn_index"]) for c in kf.get("corrected", [])}

    added = 0
    for item in items:
        key = (item.get("transcript"), item.get("entity"), item.get("value"),
               item.get("turn_index"))
        if key in have or (item.get("transcript"), item.get("turn_index")) in corrected:
            continue
        row = {
            "transcript": item["transcript"],
            "entity": item["entity"],
            "value": item["value"],
            "turn_index": item["turn_index"],
            "verdict": item["verdict"],
            "note": item.get("note") or "",
            "labelled_by": item.get("labelled_by") or "unattributed",
            "corpus": worksheet.get("corpus"),
            "schema": f"contextgc/schemas/{schema_name}.json",
        }
        # The verdict is the human's. If a mechanical suggestion was on offer it is
        # recorded that one existed, so a later reader can see the reviewer was
        # not working blind -- and so nobody can mistake agreement with the
        # suggestion for the suggestion's own confidence.
        if item.get("model_suggestion"):
            row["offered_suggestion"] = item["model_suggestion"]
            row["suggestion_source"] = item.get("model_suggested_by")
            row["suggestion_agrees_with_verdict"] = (
                item["model_suggestion"] == item["verdict"]
            )
        existing.append(row)
        have.add(key)
        added += 1
    save_labels(existing, path)
    verdicts = Counter(i["verdict"] for i in items)
    return {
        "path": path,
        "added": added,
        "already_present": len(items) - added,
        "total_labels": len(existing),
        "verdicts": dict(verdicts),
        "entities": dict(Counter(i["entity"] for i in items)),
    }


def _render(worksheet: Dict[str, Any]) -> str:
    lines = [
        "=" * 78,
        f"LABELLING WORKSHEET -- {worksheet['corpus']}, schema "
        f"{worksheet['items'][0]['schema'] if worksheet['items'] else '?'}",
        "=" * 78,
        "",
        worksheet["instructions"],
        "",
        "JUDGEMENT STANDARD",
        f"  {worksheet['doctrine']}",
        "",
        f"{worksheet['rows']} rows, {worksheet['per_entity']} per slot:",
    ]
    for entity, count in sorted(worksheet["entities"].items()):
        lines.append(f"  {entity:<22} {count}")
    lines.append("")
    lines.append("=" * 78)
    for item in worksheet["items"]:
        lines.append("")
        lines.append(f"[{item['id']}] {item['entity']} = {item['value']!r}")
        lines.append(f"  {item['transcript']} turn {item['turn_index']}")
        lines.append("  " + "-" * 74)
        for line in (item["turn_in_context"] or "(no turn available)").split("\n"):
            lines.append(f"  {line}")
        lines.append("  " + "-" * 74)
        if item.get("model_suggestion"):
            lines.append(f"  SUGGESTED   : {item['model_suggestion']}"
                         f"   ({item.get('model_reason', '')})")
            for flag in item.get("triage_flags", []):
                lines.append(f"                ! {flag}")
            lines.append("                ^ mechanical text check, not a judgement")
        lines.append(f"  verdict     : {item['verdict']}")
        lines.append(f"  note        : {item['note']}")
        lines.append(f"  labelled_by : {item['labelled_by']}")
    return "\n".join(lines)


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("schema", choices=["coding", "travel", "logistics"])
    parser.add_argument("--corpus", default=None,
                        help="defaults to swe-agent for coding, apigen for the others")
    parser.add_argument("--limit", type=int, default=60,
                        help="transcripts to run the read path over")
    parser.add_argument("--per-entity", type=int, default=12)
    parser.add_argument("--corpus-path")
    parser.add_argument("--out", help="write the worksheet JSON here")
    parser.add_argument("--text", action="store_true", help="also print the human-readable form")
    parser.add_argument("--suggest", action="store_true",
                        help="attach a mechanical suggestion and its evidence to each row. "
                             "The verdict stays unlabelled: a suggestion is not a judgement "
                             "and the merge ignores it.")
    parser.add_argument("--merge", metavar="FILE",
                        help="fold a judged worksheet into the committed label file")
    args = parser.parse_args(argv)

    if args.merge:
        with open(args.merge, encoding="utf-8") as handle:
            worksheet = json.load(handle)
        result = merge(worksheet, args.schema)
        print(f"merged into {result['path']}")
        print(f"  added               {result['added']}")
        print(f"  already present     {result['already_present']}")
        print(f"  total labels        {result['total_labels']}")
        print(f"  verdicts            {result['verdicts']}")
        print(f"  entities            {result['entities']}")
        # The worksheet's own window, not a guess. A label key is
        # (transcript, slot, turn), so labels drawn from a different slice of
        # the corpus simply do not line up -- and the report discards them
        # without ever saying why the number is smaller than expected.
        corpus_name = worksheet.get("corpus", args.schema)
        domain = " --domain airline" if corpus_name == "apigen-airline" else (
            " --domain retail" if corpus_name == "apigen-retail" else "")
        print("\nre-score with -- the SAME --limit this worksheet was built at,")
        print("or the labels will not match the extractions:")
        print(f"  python -m benchmarks run --corpus {corpus_name}{domain} "
              f"--schema {args.schema} --limit {worksheet.get('limit', '?')}")

        return 0

    from benchmarks.gold import LABELS_BY_SCHEMA, load_labels

    corpus = args.corpus or ("swe-agent" if args.schema == "coding" else "apigen-airline")
    labels = load_labels(LABELS_BY_SCHEMA[args.schema]) if args.schema in LABELS_BY_SCHEMA else []
    already = {(row.get("transcript"), row.get("entity"), row.get("value"), row.get("turn_index"))
               for row in labels}

    worksheet = build(args.schema, corpus, args.limit, args.per_entity,
                      args.corpus_path, already=already,
                      with_suggestions=args.suggest)
    print(f"worksheet: {worksheet['rows']} rows across "
          f"{len(worksheet['entities'])} slots, {len(already)} existing labels excluded")
    for entity, count in sorted(worksheet["entities"].items()):
        print(f"  {entity:<22} {count}")
    if worksheet["starved_slots"]:
        print("\n  starved: " + ", ".join(
            f"{entity} {count} short" for entity, count in
            worksheet["starved_slots"].items()))
        print("  these slots got fewer rows than --per-entity asked for. Either the")
        print("  transcript window was too small to reach their values, or the corpus")
        print("  has no more. Raise --limit to tell which -- failing_test goes 2 -> 7")
        print("  -> 21 -> 44 rows at limits 60, 500, 2000, 6000.")
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(worksheet, handle, indent=2)
        print(f"\nwritten -> {args.out}")
    if args.text or not args.out:
        print()
        print(_render(worksheet))
    return 0


if __name__ == "__main__":
    sys.exit(main())
