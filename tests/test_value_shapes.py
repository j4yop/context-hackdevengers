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

The corpus-dependent tests skip when the cached corpora are absent, so the suite
still runs on a clean checkout.
"""

import json
import re
from pathlib import Path

import pytest

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
    "travel.active_reservation": ["None", "HTTPError: 403", "memset.py", "1234567"],
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
    assert last_capture_group(r"(?i:([A-Z0-9]{6}))") == "[A-Z0-9]{6}"
    assert last_capture_group(r"(?-i:([A-Z0-9]{6}))") == "[A-Z0-9]{6}"
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


def test_test_anchoring_spans_underscores_and_dots():
    """
    Not preceded by an alphanumeric. Separators would be too strict: the read
    path really produces `base_test_test.py` and `tests.test_flask_pyoidc`.
    """
    contract, _ = derive_value_contract(load_schema("coding")["failing_test"])
    for good in ("test_memset.py", "tests/test_x.py::TestY",
                 "tests/mobly/base_test_test.py", "tests.test_flask_pyoidc"):
        assert re.search(contract, good, re.IGNORECASE), good
    for bad in ("latest_file.py", "HTTPError: 403 Forbidden", "None"):
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
    the contract it is supposed to support.
    """
    for name in SCHEMAS:
        measurement = json.loads((SCHEMA_DIR / f"{name}.json").read_text())["_measurement"]
        evidence = measurement["value_contracts"]["slots"]
        assert set(evidence) == set(load_schema(name))
        for slot, record in evidence.items():
            assert record["read_path_observations"] > 0, f"{name}.{slot} never fired"
            assert record["read_path_turns"] > 0, f"{name}.{slot} never fired"
            assert record["derived_from"]


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
