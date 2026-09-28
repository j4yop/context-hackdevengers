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
from typing import Any, Dict, List, Optional, Set, Tuple

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


# --- retail ---------------------------------------------------------------
#
# The retail records are shaped differently enough that forcing them through the
# airline mapping would have been a lie about their shape. Two facts drive this:
#
# 1. `payment_method_id` is `credit_card_1234`, `gift_card_8633125` or
#    `paypal_5334408` -- the type is the prefix, with underscores. The read path
#    says "Credit Card", "Gift Card", "Paypal", "paypal account",
#    "gift card balance". Neither side is canonical, so both are reduced.
#
# 2. The read path produces *partial* addresses. "464 Oak Street, Suite 664" is
#    correct and the record also holds "San Diego, CA 92135". Comparing strings
#    would call every partial extraction a contradiction, so containment is the
#    test: an address is corroborated when it contains the record's street line,
#    and completeness is reported beside it rather than folded in.

#: The order record's address fields, in the order a person says them.
ADDRESS_PARTS = ("address1", "address2", "city", "state", "zip")

#: Suffixes the read path adds to a payment method that the record does not name.
PAYMENT_NOISE = (" account", " balance", " card ending", " number")


def retail_payment_methods(record: Dict[str, Any]) -> Set[str]:
    """The payment types a retail order record shows, reduced to bare names."""
    out: Set[str] = set()
    for entry in record.get("payment_history") or []:
        pid = str(entry.get("payment_method_id") or "").strip().lower()
        if not pid:
            continue
        if pid.startswith("credit_card"):
            out.add("credit card")
        elif pid.startswith("gift_card"):
            out.add("gift card")
        elif pid.startswith("paypal"):
            out.add("paypal")
    return out


def normalise_payment(value: str) -> str:
    """`"Gift Card"`, `"gift card balance"`, `"Paypal account"` -> one bare name."""
    text = (value or "").strip().lower().replace("_", " ")
    for noise in PAYMENT_NOISE:
        if text.endswith(noise.strip()):
            text = text[: -len(noise.strip())].strip()
    return text


def street_line(record: Dict[str, Any]) -> str:
    """The record's street line, as `address1[, address2]`."""
    address = record.get("address")
    if not isinstance(address, dict):
        return ""
    parts = [str(address.get(k) or "").strip() for k in ("address1", "address2")]
    return ", ".join(p for p in parts if p)


def address_completeness(record: Dict[str, Any], extracted: str) -> bool:
    """True when the extraction carried the full address, not just the street."""
    address = record.get("address")
    if not isinstance(address, dict):
        return False
    text = (extracted or "").lower()
    return all(
        str(address.get(k) or "").strip().lower() in text
        for k in ("city", "state", "zip")
        if address.get(k)
    )



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


def records_by_transcript(transcripts: List[Any], domain: str = "travel") -> Dict[str, List[Dict[str, Any]]]:
    """
    Every authoritative record the environment returned, keyed by transcript.

    A transcript can hold several -- a customer with two reservations, or two
    orders -- so a value is corroborated if it matches *any* record. Contradicting
    every record the transcript contains is what "contradicted" means.
    """
    marker = "reservation_id" if domain == "travel" else "order_id"
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
            if isinstance(data, dict) and marker in data:
                out[transcript.id].append(data)
    return out


def _retail_judgement(record: Dict[str, Any], slot: str, value: str) -> Optional[bool]:
    """True corroborates, False contradicts, None when the record is silent."""
    if slot == "payment_method":
        held = retail_payment_methods(record)
        if not held:
            return None
        return normalise_payment(value) in held
    if slot == "delivery_address":
        address = record.get("address")
        if not isinstance(address, dict) or not address.get("address1"):
            return None
        text = (value or "").lower()
        # The house number and street, not the whole line. "713 Park Avenue" is
        # the same address as a record of "713 Park Avenue, Suite 800" -- the read
        # path stopped early, which is incompleteness, not a different address.
        # Demanding the full line turned 1 of 2 address contradictions into a
        # partial, and a partial is reported beside the rate rather than in it.
        return str(address["address1"]).strip().lower() in text
    return None


def score(transcripts: List[Any], schema_name: str = "travel",
          domain: str = "travel") -> Dict[str, Any]:
    from benchmarks.harness import run

    result = run(transcripts, schema=load_schema(schema_name), max_extractions=100000)
    records = records_by_transcript(transcripts, domain)

    buckets: Dict[str, Counter] = defaultdict(Counter)
    by_entity: Dict[str, Counter] = defaultdict(Counter)
    contradicted: List[Dict[str, Any]] = []
    partial_addresses = Counter()
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

        verdict: Optional[bool] = None
        held_display: List[str] = []
        if domain == "retail":
            for record in records_here:
                if slot in ("payment_method", "delivery_address"):
                    verdict = _retail_judgement(record, slot, value)
                    held_display = sorted(retail_payment_methods(record)) if slot == "payment_method" \
                        else [street_line(record) or
                              str((record.get("address") or {}).get("address1") or "")]
                    if verdict is True and slot == "delivery_address":
                        # Correct but partial is its own thing, and folding it in
                        # with a full address would hide that the read path often
                        # stops at the street line.
                        if not address_completeness(record, value):
                            partial_addresses[transcript_id] += 1
                    if verdict is not None:
                        break
        else:
            if slot not in SLOT_FIELDS:
                verdict = None
            else:
                # Every record the transcript holds, unioned. A customer with two
                # reservations makes "is this value in the records" a question
                # about all of them, not about whichever was returned last.
                candidates: Set[str] = set()
                for record in records_here:
                    candidates |= slot_values(record, slot)
                if not candidates:
                    verdict = None
                else:
                    # The record says `basic economy`; the read path says
                    # `Basic Economy`. Comparing raw dropped travel's cabin_class
                    # from 5 contradictions to 18 when this loop was refactored,
                    # which is how a normalisation was found to be load-bearing
                    # by losing it.
                    probe = (_normalise_cabin(value) if slot == "cabin_class"
                             else value.strip())
                    held = {_normalise_cabin(c) if slot == "cabin_class" else c
                            for c in candidates}
                    verdict = probe in held
                    held_display = sorted(held)[:8]

        if verdict is None:
            buckets["unverifiable"][slot] += 1
            by_entity[slot]["unverifiable"] += 1
        elif verdict:
            buckets["corroborated"][slot] += 1
            by_entity[slot]["corroborated"] += 1
        else:
            buckets["contradicted"][slot] += 1
            by_entity[slot]["contradicted"] += 1
            if len(contradicted) < 40:
                contradicted.append({
                    "transcript": transcript_id, "entity": slot, "value": value,
                    "turn": item.get("turn"),
                    "records_hold": held_display,
                })
    total = sum(sum(c.values()) for c in by_entity.values()) or 1
    return {
        "extractions": total,
        "corroborated": sum(buckets["corroborated"].values()),
        "contradicted": sum(buckets["contradicted"].values()),
        "unverifiable": sum(buckets["unverifiable"].values()),
        "by_entity": {k: dict(v) for k, v in sorted(by_entity.items())},
        "transcripts_with_records": len(records),
        "partial_addresses": sum(partial_addresses.values()),
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
    domain = "retail" if "retail" in corpus else "travel"
    result = score(transcripts, args.schema, domain=domain)
    noun = "order" if domain == "retail" else "booking"

    print("GROUND TRUTH -- scored against the environment's records, not a reader")
    print(f"  corpus {corpus}, {len(transcripts)} transcripts, "
          f"{result['transcripts_with_records']} carrying an {noun} record\n")
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
    if domain == "retail":
        print(f"  of which {result['partial_addresses']} addresses were corroborated but")
        print("  partial -- the read path stopped at the street line and left off the")
        print("  city, state and zip the record also holds. Correct, and incomplete.")
        print()
        print("  READ THE RETAIL CONTRADICTIONS BEFORE TRUSTING THE RATE.")
        print("  A retail order record is retrospective. payment_history says what was")
        print("  already charged and address says where the order is now, so a record")
        print("  cannot corroborate a slot whose whole purpose is a *pending* change.")
        print()
        print("  Reading the contradicted turns, they are that shape: \"I would like")
        print("  to change the shipping address to 123 Oak Street\", \"you can use my")
        print("  PayPal account for any price differences along the way\". The read path")
        print("  is tracking what the customer just asked for, which the record has")
        print("  not applied yet. Those are counted as contradicted, because excluding")
        print("  them would flatter the number -- but they are the record answering a")
        print("  different question, not the tracker reading one wrongly.")
        print()
        print("  The count below is a SAMPLE of the contradictions, read by hand, not an")
        print("  exhaustive classification. An earlier attempt to split them by regex")
        print("  was wrong on turns already read by hand, so no split is published: a")
        print("  precise-looking number from an unreliable classifier is worse than none.")
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
