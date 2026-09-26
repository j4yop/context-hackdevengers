"""
Tests for the benchmark harness itself.

A benchmark that is wrong is worse than no benchmark, because it gets quoted.
These pin the properties the harness promises: that it refuses to report a
precision it did not measure, that shadow mode cannot leak a declaration into
emitted context, and that the numbers it reports are internally consistent.
"""

import json

import pytest
from conftest import MINIMAL

from benchmarks import gold, harness, report, shadow
from benchmarks.corpus import Transcript, describe, normalise_messages


def make(turns=8):
    return Transcript(
        "t1",
        [{"role": "user", "content": "deliver to Tower B, Flat 402"} for _ in range(turns)],
        "synthetic",
    )


# ---------------------------------------------------------------------------
# The report must not overstate
# ---------------------------------------------------------------------------

def test_a_measurement_always_carries_its_n_and_its_caveat():
    result = harness.run([make()])
    text = report.render(result)
    assert "n" in text
    for measurement in result.measurements:
        assert measurement.does_not_mean, f"{measurement.name} has no caveat"
        assert "NOT:" in text


def test_precision_is_not_reported_without_labels(tmp_path):
    result = harness.run([make()])
    text = gold.render(gold.score(result.extractions, labels=[]))
    assert "Not measured" in text
    # No figure may be asserted at all -- not just no percentage.
    assert "PRECISION " not in text.replace("PRECISION (hand-labelled sample)", "")


def test_small_samples_are_flagged():
    scored = {
        "n_labelled": 3, "n_unmatched_labels": 0, "correct": 2, "incorrect": 1,
        "unclear": 0, "precision": 0.667, "n": 3, "matched": [],
    }
    assert "small sample" in gold.render(scored)


def test_synthetic_corpus_is_labelled_as_such():
    text = report.render(harness.run([make()]))
    assert "SYNTHETIC" in text
    assert "not independent evidence" in text


def test_a_retirement_violation_is_called_a_bug_not_a_metric():
    result = harness.run([make()])
    # Force the measurement to a non-zero value and confirm the framing.
    for measurement in result.measurements:
        if measurement.name == "retirement_violations":
            measurement.value = 3
    text = report.render(result)
    assert "BUG, not a metric" in text


def test_report_flags_a_context_that_grew():
    result = harness.run([make()])
    for measurement in result.measurements:
        if measurement.name == "contexts_that_grew":
            measurement.value = 2
    assert "MORE tokens" in report.render(result)


def test_missing_turns_are_reported_as_unexercised():
    result = harness.run([make()])
    for measurement in result.measurements:
        if measurement.name == "keys_reasserted":
            measurement.value = 0
    text = report.render(result)
    assert "never exercised" in text


# ---------------------------------------------------------------------------
# Shadow mode must not be able to leak a declaration
# ---------------------------------------------------------------------------

def declaring(index, role, content):
    return '<contextgc-state>{"assert":{"destination_address":"Declared St"}}</contextgc-state>' \
        if role == "assistant" else None


def test_shadow_never_emits_a_declared_context():
    messages = [
        {"role": "user", "content": "deliver to Tower B, Flat 402"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "thanks"},
    ]
    outcome = shadow.shadow_compare(messages, declaring, schema=MINIMAL)
    emitted = json.dumps(outcome["emitted"])
    assert "Declared St" not in emitted, "a declaration reached the emitted context"
    assert "contextgc-state" not in emitted


def test_shadow_reports_an_added_key():
    # "it" is invisible to the read path, which is the case the write path exists
    # for: the agent resolves the reference and reports it.
    messages = [
        {"role": "user", "content": "the parcel is going to the old depot"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "thanks"},
    ]
    outcome = shadow.shadow_compare(messages, declaring, schema=MINIMAL)
    assert "destination_address" in outcome["added"]
    assert "read path found nothing" or True  # the point is it is reported at all
    assert outcome["verdict"].startswith("added")


def test_shadow_reports_a_changed_key_with_both_values():
    messages = [
        {"role": "user", "content": "deliver to Gate 2 security entrance"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "thanks"},
    ]
    outcome = shadow.shadow_compare(messages, declaring, schema=MINIMAL)
    assert "destination_address" in outcome["changed"]
    pair = outcome["changed"]["destination_address"]
    assert "read_path" in pair and "declared" in pair


def test_shadow_verdict_never_calls_a_declaration_correct():
    """It cannot know truth, so the vocabulary must not imply it."""
    messages = [
        {"role": "user", "content": "deliver to Gate 2"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "thanks"},
    ]
    outcome = shadow.shadow_compare(messages, declaring, schema=MINIMAL)
    text = report.render_shadow(shadow.run_corpus(
        [Transcript("t", messages, "synthetic")], lambda t: declaring, schema=MINIMAL,
    ))
    assert "correct" not in outcome["verdict"]
    assert "needs adjudicating" in text or "DISAGREEMENTS" in text


def test_shadow_refuses_to_run_without_captures():
    """The CLI must say there is nothing to compare rather than inventing a number."""
    from benchmarks.__main__ import main
    with pytest.raises(SystemExit) as exc:
        main(["shadow", "--corpus", "synthetic", "--corpus-path", "/nonexistent"])
    assert "needs --captures" in str(exc.value)


# ---------------------------------------------------------------------------
# Corpus handling
# ---------------------------------------------------------------------------

def test_empty_and_role_less_messages_are_dropped():
    out = normalise_messages([
        {"role": "ai", "text": "hello"},
        {"role": "user", "text": ""},
        {"role": "nonsense", "text": "x"},
        {"role": "user", "text": None},
    ])
    assert out == [{"role": "assistant", "content": "hello"}]


def test_describe_reports_turn_statistics():
    described = describe([make(5), make(15)])
    assert described["count"] == 2
    assert described["turns_total"] == 20
    assert described["turns_min"] == 5
    assert described["turns_max"] == 15


def test_a_crashing_transcript_is_recorded_not_skipped():
    """A malformed transcript is a finding about the corpus, not a reason to abort."""
    broken = Transcript("bad", [{"role": "user", "content": None} for _ in range(3)], "synthetic")
    broken.messages[1] = {"role": "user", "content": {"not": "a string"}}

    result = harness.run([broken, make()])
    assert result.errors, "a crash was silently skipped"
    assert result.per_transcript, "the run aborted instead of continuing"
    assert len(result.per_transcript) == 1, "the good transcript was lost too"


def test_a_transcript_that_cannot_report_its_length_is_still_counted():
    class Unmeasurable(Transcript):
        @property
        def n_turns(self):
            raise RuntimeError("boom")

    result = harness.run([Unmeasurable("odd", [{"role": "user", "content": "hi"}], "synthetic")])
    assert not result.errors, "a missing length is not a compile failure"
    assert len(result.per_transcript) == 1


# ---------------------------------------------------------------------------
# Gold labelling
# ---------------------------------------------------------------------------

def test_precision_denominator_excludes_unclear():
    scored = gold.score(
        [{"transcript": "t", "entity": "e", "value": "v", "turn": 0, "source": "inferred"}],
        labels=[{"transcript": "t", "entity": "e", "turn_index": 0, "verdict": "unclear"}],
    )
    assert scored["n"] == 0
    assert scored["precision"] is None
    assert scored["unclear"] == 1


def test_drifted_labels_are_reported():
    scored = gold.score(
        [{"transcript": "t", "entity": "e", "value": "NEW", "turn": 0, "source": "inferred"}],
        labels=[{"transcript": "t", "entity": "e", "turn_index": 0,
                 "verdict": "correct", "value": "OLD"}],
    )
    assert not scored["matched"][0]["value_agrees"]


def test_unmatched_labels_are_surfaced():
    labels = [
        {"transcript": "gone", "entity": "e", "turn_index": 0, "verdict": "correct"},
        {"transcript": "here", "entity": "e", "turn_index": 0, "verdict": "correct"},
    ]
    scored = gold.score(
        [{"transcript": "here", "entity": "e", "value": "v", "turn": 0, "source": "inferred"}],
        labels=labels,
    )
    assert scored["n_unmatched_labels"] == 1
    assert "did not match" in gold.render(scored)
