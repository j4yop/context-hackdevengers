"""
Score read-path extractions against the booking database, not against a person.

Every airline tool result in the corpus is the environment's own record of a
reservation: ``{"reservation_id": "0U4NPP", "origin": "PHL", "cabin": "economy",
"flights": [{"flight_number": "HAT076", "date": "2024-05-09", ...}]}``. That is
ground truth, in the conversation, for the exact slots the travel schema tracks.

It is worth being precise about why using it here is legitimate when the read
path refuses to use it. The library must not *infer* state from a machine payload
-- a booking record is a database dump, not a statement of what the customer
wants. Evaluating against it is the opposite operation: the payload is the answer
key, held aside from the system under test. Refusing to read the key and refusing
to score against the key would be one and the same mistake.

So this gives a number, and it is a *different* number from the hand-labelled
one, with a different meaning:

* hand-labelled precision asks "did a person read the turn and judge this true"
* this asks "is this value consistent with what the environment recorded"

The second is stricter in one way and looser in another. It is stricter because
the record is authoritative rather than a reader's impression. It is looser
because it cannot see whether the customer had *moved on* by that turn -- it
checks the value, not its currency, which is the same limitation the staleness
attempt ran into. A value can be real and out of date, and this scores it correct.

Every extraction lands in exactly one bucket and the three are reported apart:

``corroborated``
    the transcript holds a record for that slot and the value matches one
``contradicted``
    the transcript holds records for that slot and the value matches none
``unverifiable``
    the transcript holds no record for that slot, so this says nothing

    python -m benchmarks.ground_truth travel --limit 200
    python -m benchmarks.ground_truth travel --limit 200 --show 10
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Set, Tuple

from benchmarks.corpus import load_apigen_mt
from contextgc import load_schema

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

#: Which JSON field of a reservation record is the ground truth for each slot.
#: A field may be nested, and `flights` is a list, so several spellings.
SLOT_FIELDS: Dict[str, Tuple[str, ...]] = {
    "active_reservation": ("reservation_id",),
    "passenger_id": ("user_id",),
    "origin_airport": ("origin", "flights[].origin"),
    "destination_airport": ("destination", "flights[].destination"),
    "flight_number": ("flights[].flight_number",),
    "flight_date": ("flights[].date",),
    "cabin_class": ("cabin",),
}


def _iso_to_spoken(value: str) -> str:
    """``2024-05-09`` -> ``May 9, 2024``, the way a person says it."""
    try:
        year, month, day = value.split("-")
        return f"{MONTHS[int(month) - 1]} {int(day)}, {year}"
    except (ValueError, IndexError):
        return value


def _normalise_cabin(value: str) -> str:
    return (value or "").replace("_", " ").strip().lower()


def _normalise_date(value: str) -> str:
    value = (value or "").strip()
    return _iso_to_spoken(value) if re.match(r"^\d{4}-\d{2}-\d{2}$", value) else value


def slot_values(record: Dict[str, Any], slot: str) -> Set[str]:
    """Every value the booking record holds for one slot."""
    out: Set[str] = set()
    for field in SLOT_FIELDS.get(slot, ()):
        if field == "flights[].origin":
            out.update(f.get("origin") for f in record.get("flights", []) if f.get("origin"))
        elif field == "flights[].destination":
            out.update(f.get("destination") for f in record.get("flights", []) if f.get("destination"))
        elif field == "flights[].flight_number":
            out.update(f.get("flight_number") for f in record.get("flights", []) if f.get("flight_number"))
        elif field == "flights[].date":
            out.update(_normalise_date(f.get("date")) for f in record.get("flights", []) if f.get("date"))
        else:
            value = record.get(field)
            if isinstance(value, str) and value.strip():
                out.add(value.strip())
    if slot == "cabin_class":
        out = {_normalise_cabin(v) for v in out}
    return out


def records_by_transcript(transcripts: List[Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Every booking record the environment returned, keyed by transcript.

    A transcript can have several -- a customer with two reservations -- so a
    value is corroborated if it matches *any* record. Contradicting every record
    the transcript contains is what "contradicted" means here.
    """
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for transcript in transcripts:
        for message in transcript.messages:
            body = (message.get("content") or "").strip()
            if not body.startswith("{"):
                continue
            try:
                data = json.loads(body)
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and "reservation_id" in data:
                out[transcript.id].append(data)
    return out


def score(transcripts: List[Any], schema_name: str = "travel") -> Dict[str, Any]:
    from benchmarks.harness import run

    result = run(transcripts, schema=load_schema(schema_name), max_extractions=100000)
    records = records_by_transcript(transcripts)

    buckets: Dict[str, Counter] = defaultdict(Counter)
    by_entity: Dict[str, Counter] = defaultdict(Counter)
    contradicted: List[Dict[str, Any]] = []
    for item in result.extractions:
        slot = item.get("entity")
        value = item.get("value")
        transcript_id = item.get("transcript")
        if not slot or value is None:
            continue
        records_here = records.get(transcript_id, [])
        if not records_here:
            buckets["unverifiable"][slot] += 1
            by_entity[slot]["unverifiable"] += 1
            continue
        if slot not in SLOT_FIELDS:
            buckets["unverifiable"][slot] += 1
            by_entity[slot]["unverifiable"] += 1
            continue
        candidates: Set[str] = set()
        for record in records_here:
            candidates |= slot_values(record, slot)
        if not candidates:
            buckets["unverifiable"][slot] += 1
            by_entity[slot]["unverifiable"] += 1
            continue
        probe = _normalise_cabin(value) if slot == "cabin_class" else value.strip()
        if probe in candidates:
            buckets["corroborated"][slot] += 1
            by_entity[slot]["corroborated"] += 1
        else:
            buckets["contradicted"][slot] += 1
            by_entity[slot]["contradicted"] += 1
            if len(contradicted) < 40:
                contradicted.append({
                    "transcript": transcript_id, "entity": slot, "value": value,
                    "turn": item.get("turn"),
                    "records_hold": sorted(candidates)[:8],
                })
    return {
        "extractions": len(result.extractions),
        "corroborated": sum(buckets["corroborated"].values()),
        "contradicted": sum(buckets["contradicted"].values()),
        "unverifiable": sum(buckets["unverifiable"].values()),
        "by_entity": {k: dict(v) for k, v in sorted(by_entity.items())},
        "transcripts_with_records": len(records),
        "contradicted_examples": contradicted,
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("schema", nargs="?", default="travel", choices=["travel", "logistics"])
    parser.add_argument("--corpus", default=None)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--corpus-path")
    parser.add_argument("--show", type=int, default=0, metavar="N",
                        help="print N contradicted extractions")
    parser.add_argument("--json")
    args = parser.parse_args(argv)

    corpus = args.corpus or ("apigen-airline" if args.schema == "travel" else "apigen-retail")
    transcripts = load_apigen_mt(
        limit=args.limit, path=args.corpus_path,
        domain="airline" if "airline" in corpus else "retail",
    )
    if not transcripts:
        sys.exit("no transcripts loaded")
    result = score(transcripts, args.schema)

    print("GROUND TRUTH -- scored against the booking database, not a reader")
    print(f"  corpus {corpus}, {len(transcripts)} transcripts, "
          f"{result['transcripts_with_records']} carrying a booking record\n")
    total = result["extractions"] or 1
    print(f"  extractions                       {result['extractions']}")
    print(f"  corroborated by the record        {result['corroborated']} "
          f"({result['corroborated']/total:.1%})")
    print(f"  contradicted by the record        {result['contradicted']} "
          f"({result['contradicted']/total:.1%})")
    print(f"  unverifiable (no record for slot) {result['unverifiable']} "
          f"({result['unverifiable']/total:.1%})")
    print()
    print(f"  {'slot':<22} {'corrob':>7} {'contra':>7} {'unverif':>8}")
    for slot, counts in result["by_entity"].items():
        print(f"  {slot:<22} {counts.get('corroborated', 0):>7} "
              f"{counts.get('contradicted', 0):>7} {counts.get('unverifiable', 0):>8}")
    print()
    print("  The corroboration rate is over corroborated + contradicted only. The")
    print("  unverifiable column is not a pass: it is extractions this check says")
    print("  nothing about, and folding it in would flatter the number.")
    if result["contradicted"]:
        print()
        print("  WHAT THE RECORD CONTRADICTS:")
        for row in result["contradicted_examples"][:args.show or 8]:
            print(f"    {row['entity']} = {row['value']!r}  ({row['transcript']} turn {row['turn']})")
            print(f"        record holds: {row['records_hold']}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
        print(f"\n  wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
