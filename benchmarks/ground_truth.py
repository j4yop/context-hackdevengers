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
from pathlib import Path
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


#: Which key identifies a record, per schema. Keyed by *schema*, not by corpus
#: name: the airline half of APIGen carries `reservation_id` and the retail half
#: carries `order_id`, and the two spellings of "which half" (`airline` vs
#: `travel`) did not match -- so passing the corpus name here looked airline
#: records up by `order_id`, found none, and scored every declaration
#: unverifiable. 109 declarations, 0 corroborated, and it looked like a finding.
RECORD_MARKER = {"travel": "reservation_id", "logistics": "order_id"}


def records_by_transcript(transcripts: List[Any], schema_name: str = "travel") -> Dict[str, List[Tuple[int, Dict[str, Any]]]]:
    """
    Every authoritative record, keyed by transcript, **with the turn it was seen
    at**.

    The turn matters, and dropping it produced 70 wrong verdicts. A customer says
    "please ship it to 123 Oak Street", the agent applies the change, and the
    *next* tool result shows 123 Oak Street. Scoring the utterance against the
    only record in the transcript -- the order *before* the change -- reports a
    contradiction for a fact the read path got exactly right. Three such cases
    read by hand:

        apigen-1751 turn 13 names "760 Elm Avenue", record before: 592 Elm
                          record after:  760 Elm Avenue
        apigen-1817 turn 11 names "123 Oak Street", record before: 463 Main
                          record after:  123 Oak Street
        apigen-1865 turn 12 names "828 River Road",  record before: 388 Spruce
                          record after:  828 River Road

    So the state a turn is judged against is the order as it was *just before*
    the turn, and equally any state the environment goes on to record. Both are
    checked; a value matching neither is a real disagreement.
    """
    marker = RECORD_MARKER.get(schema_name, "reservation_id")
    out: Dict[str, List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
    for transcript in transcripts:
        for turn, message in enumerate(transcript.messages):
            body = (message.get("content") or "").strip()
            if not body.startswith("{"):
                continue
            try:
                data = json.loads(body)
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and marker in data:
                out[transcript.id].append((turn, data))
    return out


def _states_for_slot(
    records: List[Tuple[int, Dict[str, Any]]], slot: str, turn: int
) -> Tuple[Set[str], List[Set[str]]]:
    """
    ``(state_as_of_just_before, every_state_recorded_at_or_after)``.

    Two different questions, and conflating them is what produced 70 false
    contradictions. The state before the turn is what a customer is restating.
    A state after it is what the environment went on to record -- which is how a
    *requested* change gets confirmed, since the record before the turn shows the
    order as it was.

    The second list is also the answer to "could the record have disagreed?". If
    nothing is recorded at or after the turn, the order never had a chance to
    reflect the change, so a value matching nothing is **unverifiable**, not
    contradicted: a customer who says "charge the difference to my credit card"
    and then ends the conversation leaves no trace, and calling the read path
    wrong for agreeing with them measures nothing.
    """
    before: Set[str] = set()
    after: List[Set[str]] = []
    for seen_at, record in records:
        values = _values_for_slot(record, slot)
        if not values:
            continue
        if seen_at < turn:
            before = values
        else:
            after.append(values)
    return before, after


def _values_for_slot(record: Dict[str, Any], slot: str) -> Set[str]:
    """The values one record holds for one slot, domain-appropriate."""
    if slot in ("payment_method", "delivery_address"):
        return _retail_judgement_values(record, slot)
    if slot in SLOT_FIELDS:
        return slot_values(record, slot)
    return set()


def _retail_judgement_values(record: Dict[str, Any], slot: str) -> Set[str]:
    if slot == "payment_method":
        return retail_payment_methods(record)
    if slot == "delivery_address":
        address = record.get("address")
        if not isinstance(address, dict) or not address.get("address1"):
            return set()
        return {str(address["address1"]).strip().lower()}
    return set()


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
    records = records_by_transcript(transcripts, schema_name)

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

        turn = item.get("turn") or 0
        before, after = _states_for_slot(records_here, slot, turn)
        states = [s for s in [before, *after] if s]
        if not states:
            buckets["unverifiable"][slot] += 1
            by_entity[slot]["unverifiable"] += 1
            continue

        if slot == "cabin_class":
            probe = _normalise_cabin(value)
        elif slot == "payment_method":
            probe = normalise_payment(value)
        elif slot == "delivery_address":
            # The house number and street, not the whole line: "713 Park Avenue"
            # is the same address as a record holding "713 Park Avenue, Suite
            # 800", and the read path stops early more often than not.
            probe = (value or "").lower().strip()
        else:
            probe = value.strip()

        def matches(state: Set[str]) -> bool:
            if slot == "delivery_address":
                return any(candidate in probe for candidate in state)
            if slot == "cabin_class":
                return probe in {_normalise_cabin(c) for c in state}
            if slot == "payment_method":
                return probe in {normalise_payment(c) for c in state}
            return probe in state

        corroborated = any(matches(state) for state in states)
        held_display = sorted({c for state in states for c in state})[:8]
        if corroborated:
            buckets["corroborated"][slot] += 1
            by_entity[slot]["corroborated"] += 1
            if slot == "delivery_address" and not any(
                address_completeness(record, value)
                for _, record in records_here
            ):
                # Correct, and incomplete: the read path stopped at the street
                # line and left off the city, state and zip the record holds.
                # Reported beside the rate, never folded into it.
                partial_addresses[transcript_id] += 1
        elif not after:
            # Nothing was recorded at or after this turn, so the order never had
            # the chance to reflect whatever the customer was asking for. That is
            # silence, not disagreement.
            buckets["unverifiable"][slot] += 1
            by_entity[slot]["unverifiable"] += 1
        else:
            buckets["contradicted"][slot] += 1
            by_entity[slot]["contradicted"] += 1
            if len(contradicted) < 40:
                contradicted.append({
                    "transcript": transcript_id, "entity": slot, "value": value,
                    "turn": turn,
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



def _render_declarations(args: Any) -> int:
    result = score_declarations(args.declarations, args.schema,
                                "airline" if args.schema == "travel" else "retail")
    rate = result["corroboration_rate"]
    print("=" * 78)
    print("THE WRITE PATH -- was a fact the model ASSERTED actually true?")
    print("=" * 78)
    print(f"  capture        {result['capture']}")
    print(f"  model          {result['model']}")
    print(f"  transcripts    {result['transcripts']}")
    print()
    print("  A declared value wins over the read path by design, so an unchecked")
    print("  declaration silently overrides everything the read path got right.")
    print("  These are the first numbers for that.")
    print()
    print("  declared values with a record to check them against")
    print(f"    corroborated  {result['corroborated']}")
    print(f"    contradicted  {result['contradicted']}"
          + (f"  ({rate:.1%} of the decidable pair is corroborated)" if rate else ""))
    print(f"    unverifiable  {result['unverifiable']}  (no record saw the outcome)")
    print("  declared values with NO ground truth at all")
    print(f"    unchecked     {result['no_ground_truth']}  (the slot has no field in any")
    print("                    record, so nothing here can settle them either way)")
    print()
    print(f"  the value gate would reject {result['rejected_by_the_value_gate']} of the declared values")
    wrong = result["contradicted_examples"]
    caught = sum(1 for e in wrong if e["gate_would_reject"])
    print(f"  ... and {caught} of the {len(wrong)} the record contradicts")
    print()
    if wrong:
        print("  WHAT THE RECORD DENIES:")
        for e in wrong:
            mark = "caught" if e["gate_would_reject"] else "MISSED"
            print(f"    [{mark:>6}] {e['entity']} = {str(e['value'])[:44]!r}")
            print(f"             record holds {e['records_hold'][:3]}")
    print()
    print("  A MISSED one is the interesting one: a value that satisfies its")
    print("  contract and is still wrong. A contract checks shape, never truth, so")
    print("  the write path cannot be called proven while any of these survive.")
    return 0


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("schema", nargs="?", default="travel", choices=["travel", "logistics"])
    parser.add_argument("--corpus", default=None)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--corpus-path")
    parser.add_argument("--show", type=int, default=0, metavar="N",
                        help="print N contradicted extractions")
    parser.add_argument(
        "--declarations", metavar="CAPTURE",
        help="score a capture's *declarations* against the records instead of the "
             "read path's extractions. This is the write path: whether a fact the "
             "model asserted was true",
    )
    parser.add_argument("--json")
    args = parser.parse_args(argv)

    if args.declarations:
        return _render_declarations(args)
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
        print("  A RETAIL RECORD IS SCORED AT THE RIGHT POINT IN THE CONVERSATION.")
        print("  A customer says \"ship it to 123 Oak Street\", the agent applies the")
        print("  change, and the *next* tool result shows 123 Oak Street. Scoring that")
        print("  utterance against the only record in the transcript -- the order")
        print("  *before* the change -- reports a contradiction for a fact the read")
        print("  path got exactly right. So a value is checked against the state as")
        print("  of just before the turn and against every state recorded at or")
        print("  after it. Doing this moved contradictions from 70 to 19.")
        print()
        print("  And a record that never saw the outcome is silence, not disagreement.")
        print("  If nothing is recorded at or after the turn, the order had no chance")
        print("  to reflect the change, so a value matching nothing is UNVERIFIABLE.")
        print("  A customer who names a payment method and then ends the")
        print("  conversation leaves no trace; calling the read path wrong for")
        print("  agreeing with them measures nothing. That split is the rest of the")
        print("  19 down to 15, and it applies to the airline corpus too.")
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




# --- the write path --------------------------------------------------------
#
# Everything above scores what the *read path* inferred. The write path is the
# model declaring facts, and until now nothing had ever checked whether a
# declared fact was true. A declared value wins over the read path by design --
# that is the whole point of letting an agent state its own facts -- so an
# unchecked declaration is the one failure mode that silently overrides
# everything the read path got right.
#
# The same records settle it. A capture is keyed by transcript and turn, the
# corpus has the booking record for that transcript, and the turn indices line
# up, so a declaration can be scored against the state the environment held when
# the model said it.


def score_declarations(
    capture_path: str, schema_name: str = "travel", domain: str = "travel",
    transcripts: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Score every declaration in a capture against the environment's records.

    Four buckets, and the fourth is the one that was previously invisible:

    ``corroborated``
        the record supports the declared value
    ``contradicted``
        the record disagrees -- the write path stated something false, and it
        would have won over the read path
    ``no_ground_truth``
        the slot has no field in any record, so nothing here can say
    ``unverifiable``
        the slot has a field, but the record never saw the outcome
    """
    from contextgc.state_protocol import parse_declaration

    with open(capture_path, encoding="utf-8") as handle:
        capture = json.load(handle)
    if transcripts is None:
        transcripts = load_apigen_mt(limit=500, domain=domain)
    records = records_by_transcript(transcripts, schema_name)
    schema = load_schema(schema_name)
    known = set(schema)
    contracts = json.loads(
        (Path(__file__).resolve().parent.parent / "contextgc" / "schemas"
         / f"{schema_name}.json").read_text(encoding="utf-8")
    ).get("values", {})

    buckets: Dict[str, Counter] = defaultdict(Counter)
    wrong: List[Dict[str, Any]] = []
    gate_rejected = 0
    for transcript_id, turns in capture.get("declarations", {}).items():
        for turn, raw in turns.items():
            declaration = parse_declaration(f"<contextgc-state>{raw}</contextgc-state>")
            values: List[Tuple[str, str]] = []
            for group in (declaration.asserts, declaration.pins, declaration.unsure):
                values += list(group.items())
            for slot, value in values:
                if slot not in known:
                    buckets["no_ground_truth"][slot] += 1
                    continue
                if slot not in contracts:
                    buckets["no_ground_truth"][slot] += 1
                    continue
                pattern = re.compile(contracts[slot], re.IGNORECASE)
                shape_ok = bool(pattern.search(str(value)))
                if not shape_ok:
                    gate_rejected += 1
                before, after = _states_for_slot(
                    records.get(transcript_id, []), slot, int(turn)
                )
                states = [s for s in [before, *after] if s]
                if not states:
                    buckets["unverifiable"][slot] += 1
                    continue
                raw = str(value).strip()
                if slot == "cabin_class":
                    probe = _normalise_cabin(raw)
                elif slot == "flight_date":
                    # A model may say a date the way the record stores it, or the
                    # way a person says it. `2024-05-20` and `May 20, 2024` are
                    # the same flight date; scoring them different called a true
                    # declaration a contradiction three times in one conversation.
                    probe = _normalise_date(raw)
                else:
                    probe = raw
                def in_states(state: Set[str]) -> bool:
                    if slot == "cabin_class":
                        return probe in {_normalise_cabin(c) for c in state}
                    if slot == "flight_date":
                        return probe in {_normalise_date(c) for c in state}
                    return probe in state

                held = any(in_states(s) for s in states)
                if held:
                    buckets["corroborated"][slot] += 1
                elif not after:
                    buckets["unverifiable"][slot] += 1
                else:
                    buckets["contradicted"][slot] += 1
                    if len(wrong) < 40:
                        wrong.append({
                            "transcript": transcript_id, "turn": int(turn),
                            "entity": slot, "value": value,
                            "records_hold": sorted({c for s in states for c in s})[:6],
                            "gate_would_reject": not shape_ok,
                        })
    decidable = sum(buckets["corroborated"].values()) + sum(buckets["contradicted"].values())
    return {
        "capture": capture_path,
        "model": capture.get("model"),
        "transcripts": len(capture.get("declarations", {})),
        "declarations": sum(sum(c.values()) for c in buckets.values()),
        "corroborated": sum(buckets["corroborated"].values()),
        "contradicted": sum(buckets["contradicted"].values()),
        "unverifiable": sum(buckets["unverifiable"].values()),
        "no_ground_truth": sum(buckets["no_ground_truth"].values()),
        "corroboration_rate": (
            sum(buckets["corroborated"].values()) / decidable if decidable else None
        ),
        "by_entity": {b: dict(c) for b, c in sorted(buckets.items())},
        "rejected_by_the_value_gate": gate_rejected,
        "contradicted_examples": wrong,
    }


if __name__ == "__main__":
    sys.exit(main())
