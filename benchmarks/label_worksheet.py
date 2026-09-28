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
    """Run the read path over a corpus and return its extractions."""
    from benchmarks.harness import run

    if corpus == "swe-agent":
        transcripts = load_swe_agent(limit=limit, path=corpus_path)
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


def build(
    schema_name: str,
    corpus: str = "swe-agent",
    limit: int = 60,
    per_entity: int = 12,
    corpus_path: Optional[str] = None,
    already: Optional[set] = None,
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
    return {
        "instructions": (
            "For each row, read the turn in context and set `verdict` to correct, "
            "incorrect, or unclear. Fill in `note` with why, and `labelled_by` with "
            "who read it. Then: python -m benchmarks.label_worksheet "
            f"{schema_name} --merge <this file>"
        ),
        "doctrine": DOCTRINE,
        "corpus": corpus,
        "per_entity": per_entity,
        "rows": len(rows),
        "entities": dict(Counter(r["entity"] for r in rows)),
        "labelled": 0,
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
    added = 0
    for item in items:
        key = (item.get("transcript"), item.get("entity"), item.get("value"),
               item.get("turn_index"))
        if key in have:
            continue
        existing.append({
            "transcript": item["transcript"],
            "entity": item["entity"],
            "value": item["value"],
            "turn_index": item["turn_index"],
            "verdict": item["verdict"],
            "note": item.get("note") or "",
            "labelled_by": item.get("labelled_by") or "unattributed",
            "corpus": worksheet.get("corpus"),
            "schema": f"contextgc/schemas/{schema_name}.json",
        })
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
        print("\nre-score with:")
        print(f"  python -m benchmarks run --schema {args.schema} "
              f"--corpus {worksheet.get('corpus')} --limit {args.limit}")
        return 0

    from benchmarks.gold import LABELS_BY_SCHEMA, load_labels

    corpus = args.corpus or ("swe-agent" if args.schema == "coding" else "apigen-airline")
    labels = load_labels(LABELS_BY_SCHEMA[args.schema]) if args.schema in LABELS_BY_SCHEMA else []
    already = {(row.get("transcript"), row.get("entity"), row.get("value"), row.get("turn_index"))
               for row in labels}

    worksheet = build(args.schema, corpus, args.limit, args.per_entity,
                      args.corpus_path, already=already)
    print(f"worksheet: {worksheet['rows']} rows across "
          f"{len(worksheet['entities'])} slots, {len(already)} existing labels excluded")
    for entity, count in sorted(worksheet["entities"].items()):
        print(f"  {entity:<22} {count}")
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
