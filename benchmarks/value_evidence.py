"""
Measure what each schema slot's read path actually produces.

A value contract is only as good as the corpus behind it, and a corpus-wide
number hides which slots are carried. ``coding.failing_test`` has fired 0 times
across 40 SWE-agent transcripts: its contract is a guess about a slot nothing
has ever produced, and no amount of a sibling slot's evidence changes that. The
per-slot count has to be visible, next to the contract it is supposed to
support.

The counts come from running the read path itself over the same corpora the
schemas were fitted to, so they are reproducible rather than remembered:

    python -m benchmarks.value_evidence travel
    python -m benchmarks.value_evidence coding --write
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List

from contextgc import load_schema
from contextgc.value_shapes import last_capture_group

CACHE = Path.home() / ".cache" / "contextgc"
APIGEN = CACHE / "apigen-mt_5k.json"

#: Which corpus each shipped schema was fitted to.
CORPUS = {
    "coding": "nebius/SWE-agent-trajectories shard 0",
    "travel": "APIGen-MT-5k, airline",
    "logistics": "APIGen-MT-5k, retail",
}

#: System-prompt markers, because APIGen has no domain field.
DOMAIN_MARKER = {"travel": "airline agent", "logistics": "retail"}


def _apigen_turns(schema_name: str, limit: int) -> List[str]:
    """Human turns only: the read path never sees an ``observation`` turn."""
    if not APIGEN.exists():
        return []
    marker = DOMAIN_MARKER.get(schema_name)
    out: List[str] = []
    for item in json.loads(APIGEN.read_text()):
        if marker and marker not in item.get("system", "").lower():
            continue
        for turn in item.get("conversations", []):
            if turn.get("from") == "human":
                out.append(turn.get("value", ""))
        if limit and len(out) >= limit * 4:
            break
    return out


def _apigen_tool_output(schema_name: str, limit: int) -> List[str]:
    """
    Tool-result turns, which the read path is forbidden to infer from.

    Kept separate so ``in_tool_output`` measures something. Returning an empty
    list here made the column read 0 for every travel slot, which looks like
    "these patterns never touch machine output" rather than "nothing was
    measured".
    """
    if not APIGEN.exists():
        return []
    marker = DOMAIN_MARKER.get(schema_name)
    out: List[str] = []
    for item in json.loads(APIGEN.read_text()):
        if marker and marker not in item.get("system", "").lower():
            continue
        for turn in item.get("conversations", []):
            if turn.get("from") == "observation":
                value = turn.get("value")
                if isinstance(value, str) and value.strip():
                    out.append(value)
        if limit and len(out) >= limit * 4:
            break
    return out


def _coding_turns(limit: int) -> List[str]:
    parquet = CACHE / "swe-agent-trajectories-00000.parquet"
    if not parquet.exists():
        return []
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return []
    table = pq.read_table(parquet, columns=["trajectory"])
    out: List[str] = []
    transcripts = 0
    for batch in table.to_batches(max_chunksize=64):
        for row in batch.column("trajectory").to_pylist():
            transcripts += 1
            for turn in row or []:
                # `text`, not `content`: reading `content` returns None for every
                # turn and the coding slots measure 0, which reads as "this slot
                # never fires" rather than "this reader found nothing".
                value = turn.get("text")
                if isinstance(value, str):
                    out.append(value)
            if limit and transcripts >= limit:
                return out
    return out


def _classified_texts(schema_name: str, limit: int = 0):
    """
    Corpus text split the way the read path sees it.

    The read path refuses to infer state from machine output, so counting a hit
    inside a tool payload as a "read path observation" reports a capability the
    library does not have. The two are counted separately and only speech feeds
    ``observations``.
    """
    from contextgc.sanitizer import ToolSanitizer

    if schema_name == "coding":
        texts = _coding_turns(limit)
    else:
        texts = _apigen_turns(schema_name, limit)
    speech, machine = [], []
    for text in texts:
        target = machine if ToolSanitizer.looks_like_tool_output(text) else speech
        target.append(text)
    # For the non-coding corpora the tool results are a separate turn type the
    # read path is excluded from upstream, so the cost of that rule is measured
    # against them directly.
    if schema_name != "coding":
        machine.extend(_apigen_tool_output(schema_name, limit))
    return speech, machine


def slot_observations(schema_name: str, limit: int = 0) -> Dict[str, Dict]:
    """
    Per-slot observation counts from a read-path run over the fitted corpus.

    ``observations`` counts matches in *speech* only, so a slot mentioned three
    times in one turn counts three times; ``turns`` counts turns that produced at
    least one, which is the number that says whether the slot is reachable at all.
    A slot with 0 in both has never fired, and its contract is unfounded.

    ``in_tool_output`` is reported alongside rather than folded in. It is what the
    patterns *would* match if the machine-output rule were lifted, so the cost of
    that rule is visible instead of implied.
    """
    entities = load_schema(schema_name)
    speech, machine = _classified_texts(schema_name, limit)
    result: Dict[str, Dict] = {}
    for slot, patterns in entities.items():
        compiled = []
        for pattern in patterns:
            group = last_capture_group(pattern)
            if group:
                compiled.append(re.compile(f"(?:{pattern})", re.IGNORECASE))
        values: List[str] = []
        turns_with = 0
        for text in speech:
            found = []
            for rx in compiled:
                for match in rx.finditer(text):
                    value = next(
                        (g for g in match.groups() if g), match.group(0)
                    ).strip()
                    if value:
                        found.append(value)
            values.extend(found)
            if found:
                turns_with += 1
        in_tool = 0
        for text in machine:
            for rx in compiled:
                for match in rx.finditer(text):
                    value = next(
                        (g for g in match.groups() if g), match.group(0)
                    ).strip()
                    if value:
                        in_tool += 1
        counts = Counter(values)
        result[slot] = {
            "observations": len(values),
            "turns": turns_with,
            "distinct": len(counts),
            "fired": bool(values),
            "in_tool_output": in_tool,
            "top": counts.most_common(6),
        }
    return result


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schema", choices=["coding", "travel", "logistics"])
    parser.add_argument("--write", action="store_true",
                        help="record per-slot counts in the schema's _measurement")
    parser.add_argument("--limit", type=int, default=0, help="cap turns scanned")
    args = parser.parse_args(argv)

    stats = slot_observations(args.schema, args.limit)
    print(f"{args.schema}  ({CORPUS[args.schema]})")
    print("  speech only -- the read path refuses to infer from tool output\n")
    for slot, s in stats.items():
        flag = "" if s["fired"] else "   <- never fired: contract is unfounded"
        print(f"  {slot:<20} {s['observations']:>4} obs  "
              f"{s['turns']:>4} turns  {s['distinct']:>3} distinct"
              f"  {s['in_tool_output']:>4} in tool output{flag}")
        if s["top"]:
            print(f"       {', '.join(repr(v) for v, _ in s['top'])}")

    if args.write:
        path = Path(__file__).resolve().parent.parent / "contextgc" / "schemas" / f"{args.schema}.json"
        data = json.loads(path.read_text())
        measurement = data.setdefault("_measurement", {})
        measurement["value_evidence"] = {
            slot: {"observations": s["observations"], "turns": s["turns"],
                   "distinct": s["distinct"], "fired": s["fired"],
                   "in_tool_output": s["in_tool_output"]}
            for slot, s in stats.items()
        }
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"\n  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
