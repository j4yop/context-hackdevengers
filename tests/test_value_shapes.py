"""
Tests for contracts derived from the schemas' own patterns.

Each test here corresponds to a specific wrong answer the first derivation
produced, found by running it against the corpora rather than by inspection:

* the scanner read ``(?-i:(...))`` as a top-level capture and returned nothing,
  then a second attempt returned a stray ``)``
* ``basic economy`` -- 14 of 42 ``cabin_class`` observations, the most common
  value in the slot -- was dropped for being "structural"
* anchoring ``test_`` to a separator rejected 2 of 126 real values whose module
  names put an underscore or a dot in front of ``test_``
* ``[A-Z0-9]{6}`` matched the ``HTTPError`` inside ``HTTPError: 403`` and the
  ``memset`` inside ``memset.py``
* ``coding.failing_test`` matched 740 times in tool output and **not once in
  speech**, so the read path could never produce it and the slot was unreachable

The corpus-dependent tests skip when the cached corpora are absent, so the suite
still runs on a clean checkout.
"""

import json
import re
from pathlib import Path

import pytest

from benchmarks.value_evidence import slot_observations
from contextgc import load_schema
from contextgc.value_shapes import derive_value_contract, last_capture_group

SCHEMAS = ("coding", "travel", "logistics")
SCHEMA_DIR = Path(__file__).resolve().parent.parent / "contextgc" / "schemas"

#: Wrong-shaped declarations seen in the 14B capture, per slot. `latest_file.py`
#: and `my_test_helper.py` are wrong for `failing_test` and perfectly good for
#: `current_file`, which is why they are listed per slot rather than globally.
WRONG_SHAPED = {
    "coding.failing_test": [
        "HTTPError: 403 Forbidden",
        "None",
        "SyntaxError: '(' was never closed",
        "mocking_memset_api_response",
        "latest_file.py",
        "my_test_helper.py",
        "lexicon memset create example.com ",
    ],
    "coding.current_file": [
        "None",
        "lexicon memset create example.com ",
        "403 Forbidden",
    ],
    "travel.cabin_class": ["None", "HTTPError: 403"],
    "travel.active_reservation": [
        "None", "HTTPError: 403", "memset.py", "1234567", "memset", "abcdef", "h0mvie",
    ],
    "logistics.delivery_address": ["None", "HTTPError: 403", "memset.py"],
    "logistics.payment_method": ["None", "HTTPError: 403", "memset.py"],
}


def _corpus_available() -> bool:
    try:
        from benchmarks.value_evidence import _apigen_turns, _coding_turns
    except Exception:
        return False
    return bool(_coding_turns(1) or _apigen_turns("travel", 1))


# --- the capture scanner -------------------------------------------------


def test_the_capture_scanner_handles_nesting():
    """
    A non-capturing group inside the wanted capture, a capture nested in a
    scoped flag group, and a plain capture. The first two both broke the first
    two attempts.
    """
    assert last_capture_group(r"([\w][\w./-]*\.(?:py|js|ts))") == r"[\w][\w./-]*\.(?:py|js|ts)"
    # `(?i:` turns case-insensitivity *on*, which is already how the gate matches,
    # so the scope states nothing new and is dropped.
    # A case-INsensitive scope states nothing new: the gate already matches
    # that way, so the wrapper carries no constraint and is dropped.
    assert last_capture_group(r"(?i:([A-Z0-9]{6}))") == "[A-Z0-9]{6}"
    # A case-SENSITIVE scope is a real constraint and has to survive.
    assert last_capture_group(r"\breservation\s*(?:id|#)\s*([A-Z0-9]{6})") == "[A-Z0-9]{6}"
    assert last_capture_group(r"\bno groups here\b") is None


def test_every_scanned_capture_group_compiles():
    """A scanner that returns a span the engine rejects is worse than none."""
    for name in SCHEMAS:
        for slot, patterns in load_schema(name).items():
            for pattern in patterns:
                group = last_capture_group(pattern)
                if group is not None:
                    re.compile(group)


# --- the derivation itself ------------------------------------------------


def test_the_most_common_cabin_class_survives_the_derivation():
    """
    `basic economy` is 14 of 42 observations in its own corpus. A derivation
    that only reads a branch as a vocabulary drops it, and a contract that
    rejects the commonest value in a slot is worse than no contract.
    """
    contract, basis = derive_value_contract(load_schema("travel")["cabin_class"])
    assert "vocabulary" in basis
    for value in ("basic economy", "premium economy", "economy", "business", "first",
                  "Basic Economy", "BUSINESS"):
        assert re.search(contract, value, re.IGNORECASE), value


def test_a_reservation_code_is_a_whole_value_not_a_fragment():
    """Searched, `[A-Z0-9]{6}` also matches inside other words."""
    contract, _ = derive_value_contract(load_schema("travel")["active_reservation"])
    assert re.search(contract, "XR266K", re.IGNORECASE)
    for other in ("HTTPError: 403", "memset.py", "1234567"):
        assert not re.search(contract, other, re.IGNORECASE), other


def test_a_test_slot_is_reachable_from_the_agents_own_speech():
    """
    `failing_test` was unreachable, and the fix belonged to the pattern rather
    than to the measurement. It matched 740 times in the coding corpus and
    **not once in speech** -- every hit sat inside a pytest result, which the
    read path is forbidden to infer from. So the slot could never fire, could
    never be labelled, and contributed nothing to precision past `current_file`.

    Requiring the noun phrase that actually introduces a file -- "the test file
    `test_dispatcher.py`", "the tests in `test_run.py`" -- makes it reachable:

        before:    0 speech observations,  0 distinct values
        after:    78 speech observations, 49 distinct values

    Those are assertions, not commands: of 81 noun-phrase hits in the shard, 10
    sit beside a shell command and 71 do not. And the read path was already
    discarding the other 740, so nothing it used is lost by narrowing.
    """
    contract, _ = derive_value_contract(load_schema("coding")["failing_test"])
    for good in ("test_header.py", "tests/test_models.py",
                 "tests/parsers/test_header.py", "unicode_literals_test.py",
                 "control/tests/sisotool_test.py"):
        assert re.search(contract, good, re.IGNORECASE), good
    for bad in ("HTTPError: 403 Forbidden", "None", "reproduce.py"):
        assert not re.search(contract, bad, re.IGNORECASE), bad

    # The reachability count needs the corpus, so it is recomputed where the
    # corpus is. What is asserted everywhere is the shipped schema's own record.
    shipped = json.loads((SCHEMA_DIR / "coding.json").read_text())["_measurement"][
        "value_contracts"
    ]["slots"]["failing_test"]
    assert shipped["fired"] is True
    assert shipped["read_path_observations"] > 0
    assert shipped["distinct_values"] >= 20
    assert shipped["in_tool_output"] < shipped["read_path_observations"]


@pytest.mark.skipif(not _corpus_available(), reason="corpus not cached")
def test_failing_test_really_fires_from_speech():
    """
    The numbers in the schema are stored; this recomputes them from the corpus so
    a pattern edit that quietly made the slot unreachable again cannot pass.
    """
    stats = slot_observations("coding")["failing_test"]
    assert stats["fired"] is True, "the slot must be reachable from speech at all"
    assert stats["distinct"] >= 20, (
        f"only {stats['distinct']} distinct values -- too few to label"
    )
    assert stats["in_tool_output"] < stats["observations"], (
        "if the slot still mostly fires in tool output, the read path discards it"
    )




def test_a_case_scope_in_the_pattern_survives_into_the_contract():
    """
    The travel schema writes its reservation id as `(?-i:([A-Z0-9]{6}))` and the
    value gate matches case-insensitively. An earlier derivation returned the
    group source alone, so the contract became `^(?:[A-Z0-9]{6})$` and accepted
    `memset` and `abcdef` -- any six word characters -- as a reservation code.
    A dropped flag is a lost constraint, not a cosmetic difference.
    """
    # A case-INsensitive scope states nothing new: the gate already matches
    # that way, so the wrapper carries no constraint and is dropped.
    assert last_capture_group(r"(?i:([A-Z0-9]{6}))") == "[A-Z0-9]{6}"
    assert last_capture_group(r"(?-i:([A-Z0-9]{6}))") == "(?-i:[A-Z0-9]{6})"

    contract, _ = derive_value_contract(load_schema("travel")["active_reservation"])
    assert "(?-i:" in contract
    for good in ("XR266K", "H0MVIE", "2SNACP"):
        assert re.search(contract, good, re.IGNORECASE), good
    for bad in ("memset", "abcdef", "h0mvie", "1234567"):
        assert not re.search(contract, bad, re.IGNORECASE), bad


def test_an_absolute_path_still_survives_the_contract():
    """The match is a search, not a full match, so a leading `/` is fine."""
    contract, _ = derive_value_contract(load_schema("coding")["current_file"])
    assert re.search(contract, "/lexicon/lexicon/providers/memset.py", re.IGNORECASE)


# --- the stored contracts -------------------------------------------------


def test_anchoring_is_not_applied_twice():
    """
    `travel.active_reservation` has three patterns whose capture group is
    identical. The anchoring loop used to run once per pattern and re-wrap its
    own output, producing `^^^...$$$` -- which still behaved correctly, so only
    reading the stored value found it.
    """
    for name in SCHEMAS:
        for slot, patterns in load_schema(name).items():
            contract, _ = derive_value_contract(patterns)
            assert "^^" not in contract, f"{name}.{slot} stacked anchors: {contract}"
            assert "$$" not in contract, f"{name}.{slot} stacked anchors: {contract}"


def test_the_stored_contracts_still_match_the_derivation():
    """
    Contracts are stored so a reviewer can read them. This fails if an entity
    pattern is edited without re-deriving, rather than letting the two drift.
    """
    for name in SCHEMAS:
        stored = json.loads((SCHEMA_DIR / f"{name}.json").read_text())["values"]
        for slot, patterns in load_schema(name).items():
            contract, _ = derive_value_contract(patterns)
            assert stored[slot] == contract, f"{name}.{slot} is stale; re-derive it"


def test_every_slot_records_how_often_its_read_path_fired():
    """
    A corpus-wide count hides which slots are carried. The count sits next to
    the contract it is supposed to support, and a slot that never fired has to
    say so rather than inherit a sibling's credibility.
    """
    for name in SCHEMAS:
        measurement = json.loads((SCHEMA_DIR / f"{name}.json").read_text())["_measurement"]
        evidence = measurement["value_contracts"]["slots"]
        assert set(evidence) == set(load_schema(name))
        for slot, record in evidence.items():
            assert record["derived_from"]
            assert record["fired"] == (record["read_path_observations"] > 0)
            assert "in_tool_output" in record


def test_no_slot_is_carried_by_a_contract_with_nothing_behind_it():
    """
    `coding.failing_test` was the reason this needed saying out loud. It matched
    740 times in the coding corpus and not once in speech -- every mention inside
    a pytest result, which the read path is forbidden to infer from -- so the
    read path never produced the slot and its contract had no evidence behind it.
    A corpus-wide count hid that, because the count was large and true.

    Its pattern now requires the noun phrase that introduces a file, and the slot
    fires 78 times from speech over 49 distinct values. That is the whole fix: a
    pattern change, validated against the corpus, with the reachability counted
    before and after rather than asserted.

    This test is the ratchet. If a future pattern edit leaves a slot unfired, it
    fails here instead of quietly widening the precision denominator.
    """
    unfired = []
    for name in SCHEMAS:
        slots = json.loads((SCHEMA_DIR / f"{name}.json").read_text())["_measurement"][
            "value_contracts"
        ]["slots"]
        for slot, record in slots.items():
            if not record["fired"]:
                unfired.append(f"{name}.{slot}")
    assert not unfired, (
        f"unreachable from speech, so their contracts are unfounded and no "
        f"precision may be claimed for them: {unfired}"
    )


def test_the_residual_false_accepts_are_recorded_not_swept_up():
    """
    `failing_test` still accepts `my_test_helper.py`: a helper module whose name
    contains `test_`. Distinguishing it would need more than the pattern carries,
    so it is recorded as a limit rather than fitted away.
    """
    contracts = json.loads((SCHEMA_DIR / "coding.json").read_text())["_measurement"][
        "value_contracts"
    ]
    residual = contracts["residual_false_accepts"]["failing_test"][
        "wrong_shaped_still_accepted"
    ]
    assert "my_test_helper.py" in residual


# --- against the corpora --------------------------------------------------


@pytest.mark.skipif(not _corpus_available(), reason="corpora not cached locally")
@pytest.mark.parametrize("name", SCHEMAS)
def test_no_real_read_path_value_is_rejected(name):
    """
    The read path and the write path must agree about what a value is. Every
    value the parser has ever produced is accepted by the contract derived for
    that same slot.
    """
    from benchmarks.value_evidence import _apigen_turns, _coding_turns
    from contextgc.value_shapes import last_capture_group

    texts = _coding_turns(0) if name == "coding" else _apigen_turns(name, 0)
    joined = "\n".join(texts)
    for slot, patterns in load_schema(name).items():
        contract, _ = derive_value_contract(patterns)
        found = set()
        for pattern in patterns:
            if last_capture_group(pattern) is None:
                continue
            for match in re.finditer(f"(?:{pattern})", joined, re.IGNORECASE):
                value = next((g for g in match.groups() if g), match.group(0)).strip()
                if value:
                    found.add(value)
        rejected = [v for v in sorted(found) if not re.search(contract, v, re.IGNORECASE)]
        assert not rejected, f"{name}.{slot} rejects {len(rejected)} real values: {rejected[:5]}"


@pytest.mark.parametrize("key", sorted(WRONG_SHAPED))
def test_known_wrong_shaped_declarations_are_rejected(key):
    name, slot = key.split(".")
    contract, _ = derive_value_contract(load_schema(name)[slot])
    accepted = [w for w in WRONG_SHAPED[key] if re.search(contract, w, re.IGNORECASE)]
    residual = json.loads((SCHEMA_DIR / f"{name}.json").read_text())["_measurement"][
        "value_contracts"
    ].get("residual_false_accepts", {}).get(slot, {}).get("wrong_shaped_still_accepted", [])
    assert set(accepted) <= set(residual), (
        f"{key} accepts {accepted}, which is neither accepted nor recorded as a limit"
    )
