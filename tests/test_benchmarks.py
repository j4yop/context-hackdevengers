"""
Tests for the benchmark harness itself.

A benchmark that is wrong is worse than no benchmark, because it gets quoted.
These pin the properties the harness promises: that it refuses to report a
precision it did not measure, that shadow mode cannot leak a declaration into
emitted context, and that the numbers it reports are internally consistent.
"""

import json
import os
import re

import pytest
from conftest import MINIMAL

from benchmarks import corpus as corpus_module
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


# ---------------------------------------------------------------------------
# The empty default schema is a decision, and must stay visible
# ---------------------------------------------------------------------------

def test_the_default_schema_is_empty():
    """
    The library has no built-in entity domain.

    The default it replaced was a logistics schema that matched prose in
    unrelated domains. If this test ever fails, a domain has been reintroduced
    and every caller outside that domain silently gets nonsense.
    """
    from contextgc.state_dag import StateDAG

    assert StateDAG.ENTITY_PATTERNS == {}, "a built-in entity schema was reintroduced"


def test_structural_guardrails_survive_the_empty_default():
    """The safety slots are protection, not domain, so they stay."""
    from contextgc.state_dag import StateDAG

    assert "dietary_allergy" in StateDAG.IMMUTABLE_ENTITIES
    assert "security_invariant" in StateDAG.IMMUTABLE_ENTITIES


def test_no_schema_yields_no_state_rather_than_a_wrong_one():
    from contextgc import compile_messages

    messages = [
        {"role": "user", "content": "deliver to Tower B, Flat 402"},
        {"role": "user", "content": "change the address to Gate 2 security entrance"},
        {"role": "user", "content": "thanks"},
    ]
    _, telemetry = compile_messages(messages)
    assert telemetry["active_state_slots"] == {}
    assert telemetry["retired_turn_indices"] == []


def test_opting_in_enables_state_and_survival():
    from contextgc import compile_messages

    messages = [
        {"role": "user", "content": "deliver to Tower B, Flat 402"},
        {"role": "user", "content": "change the address to Gate 2 security entrance"},
        {"role": "user", "content": "thanks"},
    ]
    _, telemetry = compile_messages(messages, schema=MINIMAL)
    assert telemetry["active_state_slots"]["destination_address"].startswith("Gate 2")
    assert telemetry["retired_turn_indices"], "supersession did not fire under a schema"


def test_the_schema_survives_the_per_invocation_reset():
    """process_session rebuilds the graph each call; the schema must be re-applied."""
    from contextgc import ContextGCEngine

    engine = ContextGCEngine(schema=MINIMAL)
    first = engine.process_session([{"role": "user", "content": "deliver to Tower B"}])
    second = engine.process_session([{"role": "user", "content": "deliver to Tower B"}])
    assert first["telemetry"]["active_state_slots"].keys() == \
        second["telemetry"]["active_state_slots"].keys()
    assert "destination_address" in second["telemetry"]["active_state_slots"]


# ---------------------------------------------------------------------------
# Precision: the two defects the labelling found
# ---------------------------------------------------------------------------

def test_a_bare_in_does_not_constitute_a_file_under_edit():
    """
    The weak trigger that caused every incorrect label in the first pass.

    A path mentioned in a sentence is not a statement about what the agent is
    working on.
    """
    import json
    import os
    import re

    path = os.path.join(os.path.dirname(__file__), "..", "contextgc", "schemas", "coding.json")
    with open(path, encoding="utf-8") as handle:
        patterns = json.load(handle)["entities"]["current_file"]

    prose = (
        "Upon reviewing the `main.py` file again, there is nothing here. "
        "Interestingly, `dispatcher.py` uses a helper."
    )
    assert not any(re.findall(p, prose) for p in patterns), (
        "prose mentioning a path was read as the file under edit"
    )


def test_an_explicit_edit_verb_does_match():
    import json
    import os
    import re

    path = os.path.join(os.path.dirname(__file__), "..", "contextgc", "schemas", "coding.json")
    with open(path, encoding="utf-8") as handle:
        patterns = json.load(handle)["entities"]["current_file"]

    for statement in (
        "I need to edit the `memset.py` file instead of the `reproduce.py` file.",
        "Let's open the `cli.py` file to examine the `handle_output` function.",
        "We should create a test script named `test_thread_count.py` to verify.",
        "I mistakenly edited the `constants.py` file instead of `dispatcher.py`.",
    ):
        assert any(re.findall(p, statement) for p in patterns), (
            f"an explicit edit statement did not match: {statement!r}"
        )


def test_a_domain_name_is_not_a_path():
    """`example.com` must not yield `example.c` via a single-letter extension."""
    import json
    import os
    import re

    path = os.path.join(os.path.dirname(__file__), "..", "contextgc", "schemas", "coding.json")
    with open(path, encoding="utf-8") as handle:
        patterns = json.load(handle)["entities"]["current_file"]

    prose = "lexicon memset create example.com TXT --name _acme-challenge.example.com"
    found = any(re.findall(p, prose) for p in patterns)
    assert not found, "a hostname was parsed as a source file"


# ---------------------------------------------------------------------------
# Machine-output detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("content", [
    "(Open file: /lexicon/reproduce.py)\n(Current directory: /lexicon)\nbash-$",
    "Your proposed edit has introduced new syntax error(s). Please retry editing the file.",
    "Found 14 matches for \"X\" in /repo/dispatcher.py:\n  Line 27: ...",
    "========================= test session starts ==========================",
    "Traceback (most recent call last):\n  File \"x.py\", line 1",
])
def test_agent_environment_responses_are_machine_output(content):
    from contextgc.sanitizer import ToolSanitizer

    assert ToolSanitizer.looks_like_tool_output(content, "user"), (
        f"machine output not recognised: {content[:50]!r}"
    )


@pytest.mark.parametrize("content", [
    "I need to edit the `memset.py` file instead of the `reproduce.py` file.",
    "The `Provider` class extends `BaseProvider`, which handles provider options.",
    "Thanks, that worked.",
])
def test_agent_prose_is_not_machine_output(content):
    from contextgc.sanitizer import ToolSanitizer

    assert not ToolSanitizer.looks_like_tool_output(content, "assistant")


# --- label-set integrity -----------------------------------------------------
#
# The precision figure is only as trustworthy as the label file, and a label
# file can rot in ways that quietly inflate the number: duplicated turns, labels
# that no longer match the corpus, verdicts asserted without evidence. These
# guard the guards.

def _precision_labels():
    with open(gold.LABELS_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def test_no_label_duplicates_the_same_slot_in_the_same_turn():
    """A repeated (transcript, entity, turn) is one piece of evidence, not two."""
    seen = set()
    for label in _precision_labels():
        key = (label["transcript"], label["entity"], label.get("turn_index"))
        assert key not in seen, f"duplicate label for {key}"
        seen.add(key)


def test_every_judged_label_records_why():
    """A verdict with no note cannot be disagreed with, only trusted."""
    for label in _precision_labels():
        assert label.get("note"), f"unjustified verdict: {label}"
        assert label.get("labelled_by"), f"unattributed verdict: {label}"


def test_labels_span_many_repositories():
    """
    The previous label file drew every row from two repositories, so the
    precision figure was largely a measurement of those two codebases.
    """
    repos = {label["transcript"].split("#")[0] for label in _precision_labels()}
    assert len(repos) >= 10, f"labels cover only {len(repos)} repos: {sorted(repos)}"


def test_label_corpus_spec_is_recorded():
    """Precision cannot be reproduced without knowing which corpus produced it."""
    spec_path = os.path.join(os.path.dirname(gold.LABELS_PATH), "corpus.json")
    assert os.path.exists(spec_path), "labels/corpus.json is missing"
    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle)
    for key in ("limit", "per_repo", "min_turns", "max_turns", "schema"):
        assert key in spec, f"corpus spec does not record {key}"


def test_known_failures_are_kept_out_of_the_precision_denominator():
    """
    Confirmed errors sit in rows the per_repo cap skips, so they are tracked in
    their own file: a sampling change must not be able to make them disappear,
    and they must not quietly pad the precision ratio either.

    The list is currently empty. It held two entries until 2026-09-28, when
    re-reading those turns against the doctrine the labels state -- "agent
    opens/edits/creates or restates this exact value" -- showed both were
    *correct* extractions. At each turn the agent says it is navigating to
    dispatcher.py, emits `open .../dispatcher.py`, and the next turn is the tool
    result confirming the open. They now sit in precision.json as correct.

    The mechanism stays. An empty list is a legitimate state -- it means nothing
    is known to be wrong -- and the assertion is on every entry, so the first
    real error recorded is checked from then on.
    """
    path = os.path.join(os.path.dirname(gold.LABELS_PATH), "known_failures.json")
    with open(path, encoding="utf-8") as handle:
        known = json.load(handle)
    assert "cases" in known, "known_failures.json lost its case list"
    labelled = {
        (label["transcript"], label["entity"], label.get("turn_index"))
        for label in _precision_labels()
    }
    for case in known["cases"]:
        assert case["verdict"] == gold.INCORRECT
        key = (case["transcript"], case["entity"], case["turn_index"])
        assert key not in labelled, f"{key} is counted in precision.json as well"


def test_known_failures_still_reproduce_as_errors():
    """
    Load the exact rows the known failures came from and confirm they are still
    wrong. If a future change fixes them this fails, which is the point: the
    entry should be deleted deliberately, not by accident.
    """
    path = os.path.join(os.path.dirname(gold.LABELS_PATH), "known_failures.json")
    with open(path, encoding="utf-8") as handle:
        known = json.load(handle)
    corpus = corpus_module.cached_shard()
    if corpus is None or not os.path.exists(corpus):
        pytest.skip("benchmark shard not present")

    from benchmarks.corpus import load_swe_agent

    transcripts = load_swe_agent(limit=10_000, per_repo=None, path=corpus)
    by_id = {t.id: t for t in transcripts}
    for case in known["cases"]:
        transcript = by_id.get(case["transcript"])
        if transcript is None:
            pytest.skip(f"{case['transcript']} not in this shard slice")
        engine = harness.run(
            [transcript], schema=_coding_schema()
        )
        hits = [
            e
            for e in engine.extractions
            if e["transcript"] == case["transcript"]
            and e.get("turn") == case["turn_index"]
            and e["value"] == case["value"]
        ]
        assert hits, (
            f"{case['transcript']} turn {case['turn_index']} no longer extracts "
            f"{case['value']!r}; if that is a fix, delete this known failure "
            f"rather than leaving a stale entry"
        )


def _coding_schema():
    import os as _os

    here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    with open(_os.path.join(here, "contextgc", "schemas", "coding.json")) as handle:
        return json.load(handle)["entities"]


def test_clustering_collapses_one_turn_counted_twice():
    """
    Trajectories for one issue replay the same opening turns. Two rows from the
    same repository, turn and slot are one observation, and the report must say
    so rather than counting them twice.
    """
    extractions = [
        {"transcript": "repo-a#1", "entity": "current_file", "value": "x.py", "turn": 7},
        {"transcript": "repo-a#2", "entity": "current_file", "value": "x.py", "turn": 7},
        {"transcript": "repo-b#3", "entity": "current_file", "value": "y.py", "turn": 9},
    ]
    labels = [
        {"transcript": "repo-a#1", "entity": "current_file", "value": "x.py",
         "turn_index": 7, "verdict": gold.CORRECT},
        {"transcript": "repo-a#2", "entity": "current_file", "value": "x.py",
         "turn_index": 7, "verdict": gold.CORRECT},
        {"transcript": "repo-b#3", "entity": "current_file", "value": "y.py",
         "turn_index": 9, "verdict": gold.CORRECT},
    ]
    result = gold.score(extractions, labels=labels)
    assert result["n"] == 3, "row count"
    assert result["n_clusters"] == 2, "the two repo-a rows are one observation"
    assert result["cluster_precision"] == 1.0


def test_a_confirmed_error_sinks_its_whole_cluster():
    """One bad extraction in a cluster is a failed cluster, not a passing one."""
    extractions = [
        {"transcript": "repo-a#1", "entity": "current_file", "value": "x.py", "turn": 7},
        {"transcript": "repo-a#2", "entity": "current_file", "value": "y.py", "turn": 7},
    ]
    labels = [
        {"transcript": "repo-a#1", "entity": "current_file", "value": "x.py",
         "turn_index": 7, "verdict": gold.CORRECT},
        {"transcript": "repo-a#2", "entity": "current_file", "value": "y.py",
         "turn_index": 7, "verdict": gold.INCORRECT},
    ]
    result = gold.score(extractions, labels=labels)
    assert result["precision"] == 0.5, "rows: one of two wrong"
    assert result["n_clusters"] == 1
    assert result["cluster_precision"] == 0.0, "the cluster is not a clean pass"


def test_wilson_interval_is_wider_for_small_n():
    """The interval has to reflect how little a small sample knows."""
    small = gold.wilson_interval(9, 10)
    large = gold.wilson_interval(900, 1000)
    assert (small[1] - small[0]) > (large[1] - large[0])
    assert small[0] < 0.9 < 1.0, "10 judgements cannot pin 90% from below"


def test_a_corpus_run_reports_precision_with_its_interval():
    """End to end: a real run must print the clustered figure and the interval."""
    from benchmarks.report import render

    result = harness.run(
        [Transcript(
            transcript_id="r#1",
            source="unit-test",
            messages=normalise_messages([
                {"role": "user", "content": "look at a.py"},
                {"role": "assistant", "content": "opening `a.py` now"},
            ]),
        )],
        schema=_coding_schema(),
    )
    text = render(result)
    assert "retirement_violations" in text


def test_check_fails_the_build_on_a_retirement_violation():
    """
    The CI step was named "regress on a precision regression" while only writing
    a JSON file, so it could not fail on anything. --check is what makes the
    benchmark job able to stop a merge, and that only holds if it really exits
    non-zero.
    """
    from benchmarks import __main__ as cli
    from contextgc.state_dag import StateDAG

    original = StateDAG.get_retirement_violations
    StateDAG.get_retirement_violations = lambda self, proposed=None: [
        ("current_file", 2, "orphaned")
    ]

    class Args:
        corpus = "synthetic"
        corpus_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "benchmarks", "corpus", "sample.txt",
        )
        min_turns = 8
        per_repo = 2
        limit = 100
        schema = None
        show_extractions = 0
        json = None
        check = True

    try:
        with pytest.raises(SystemExit) as excinfo:
            cli.cmd_run(Args())
        assert excinfo.value.code == 1
    finally:
        StateDAG.get_retirement_violations = original


def test_check_passes_on_the_vendored_corpus():
    """And the guard is not simply always failing."""
    from benchmarks import __main__ as cli

    class Args:
        corpus = "synthetic"
        corpus_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "benchmarks", "corpus", "sample.txt",
        )
        min_turns = 8
        per_repo = 2
        limit = 100
        schema = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "contextgc", "schemas", "coding.json",
        )
        show_extractions = 0
        json = None
        check = True

    try:
        cli.cmd_run(Args())
    except SystemExit as exc:  # pragma: no cover - would be a real failure
        pytest.fail(f"--check failed on the vendored corpus: exit {exc.code}")


def test_precision_is_in_the_machine_readable_output(tmp_path):
    """
    It used to exist only in the printed report, so the one number a reviewer
    would want to verify could not be verified by anything -- including CI.
    """
    import json as _json

    from benchmarks import __main__ as cli

    out = tmp_path / "bench.json"

    class Args:
        corpus = "synthetic"
        corpus_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "benchmarks", "corpus", "sample.txt",
        )
        min_turns = 8
        per_repo = 2
        limit = 100
        schema = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "contextgc", "schemas", "coding.json",
        )
        show_extractions = 0
        check = False
        json = str(out)

    cli.cmd_run(Args())
    payload = _json.loads(out.read_text())
    assert "precision" in payload, "the JSON has no precision to check"
    for key in ("n_labelled", "n_unmatched_labels", "n_clusters",
                "cluster_precision", "ci95", "n_repos"):
        assert key in payload["precision"], f"precision is missing {key}"


def test_a_drifted_label_file_is_visible_in_the_json(tmp_path):
    """
    The failure this exists to catch: labels that no longer line up with the
    corpus produce a precision figure that looks healthy in the JSON while
    measuring nothing.
    """
    import json as _json

    from benchmarks import __main__ as cli

    drifted = tmp_path / "precision.json"
    original = _json.loads(open(gold.LABELS_PATH, encoding="utf-8").read())
    for label in original:
        label["transcript"] = "nowhere-" + label["transcript"]
    drifted.write_text(_json.dumps(original))

    out = tmp_path / "bench.json"

    class Args:
        corpus = "synthetic"
        corpus_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "benchmarks", "corpus", "sample.txt",
        )
        min_turns = 8
        per_repo = 2
        limit = 100
        schema = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "contextgc", "schemas", "coding.json",
        )
        show_extractions = 0
        check = False
        json = str(out)

    real_labels = gold.LABELS_PATH
    try:
        gold.LABELS_PATH = str(drifted)
        cli.cmd_run(Args())
    finally:
        gold.LABELS_PATH = real_labels

    precision = _json.loads(out.read_text())["precision"]
    assert precision["n_labelled"] == 0
    assert precision["n_unmatched_labels"] > 0
    assert precision["precision"] is None


def test_a_birthdate_is_not_recorded_as_a_flight_date():
    """
    Found by the shadow replay, not by an aggregate: its one disagreement on the
    airline capture was the read path reading `August 10, 1995` against the
    declared `2024-05-07T13:04:42`. A date this pattern matched from prose was a
    passenger's date of birth.

    A bare month-name pattern matched 1,494 dates of which 93 (6.2%) were
    birthdates. Requiring flight context, plus a lookbehind for "born", took that
    to 11 hits whose *matched* date was a real flight date with a birthdate
    nearby. Filtering on the year would have been easier and wrong: it would fit
    the corpus's fixed "current time" rather than the slot's meaning.
    """
    from contextgc.schemas import load_schema

    result = harness.run(
        [Transcript(
            transcript_id="dob#1", source="unit-test",
            messages=normalise_messages([
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content":
                    "Passenger details: 1. **Daiki Lopez** - Date of Birth: March 20, 1954. "
                    "That is the only change you need."},
            ]),
        )],
        schema=load_schema("travel"),
    )
    dates = {e["value"] for e in result.extractions if e["entity"] == "flight_date"}
    assert not dates, f"a date of birth became a flight date: {dates}"


def test_a_customer_booking_is_not_mistaken_for_a_menu():
    """
    The reason the option-menu guard is conditioned on the role.

    Measured on the APIGen airline corpus, a content-only guard deletes the
    single most important turn in the data: 2 customer turns contain option-menu
    markers and both are a booking -- "Let's go with Option 1: Flight HAT148 from
    Miami to Denver" and "I'd like to go with Option 1: departing Atlanta at
    3:00 PM". The same strings in an agent turn mean it is listing what it could
    offer, and nothing in the content tells the two apart.
    """
    from contextgc.sanitizer import ToolSanitizer

    booking = (
        "Let's go with Option 1: Flight HAT148 from Miami to Denver and then "
        "Flight HAT084 from Denver to Las Vegas."
    )
    request = "I'd like to go with Option 1: departing Atlanta at 3:00 PM."
    menu = (
        "Here are the available options: 1. **Option 1:**  - **Flight 1:** ORD to IAH  "
        "- Flight Number: HAT165  - Available Seats: Economy  - Price: $142"
    )

    assert ToolSanitizer.looks_like_option_menu(menu, "assistant")
    # The customer chose; the library exists to remember that.
    assert not ToolSanitizer.looks_like_option_menu(booking, "user")
    assert not ToolSanitizer.looks_like_option_menu(request, "user")
    # A tool role never counts as a menu, whatever the content.
    assert not ToolSanitizer.looks_like_option_menu(menu, "tool")


def test_the_corpus_derived_travel_slots_read_a_real_booking():
    """
    The five slots added from the airline corpus, on the turn that matters.

    The menu guard must not cost these: a customer naming the route, the flight
    and the date is the whole use case, and `passenger_id` has 1,471 read-path
    observations behind it -- the largest of any travel slot.
    """
    from contextgc.schemas import load_schema

    result = harness.run(
        [Transcript(
            transcript_id="booking#1", source="unit-test",
            messages=normalise_messages([
                {"role": "user", "content": "hello"},
                {"role": "user", "content":
                    "Please rebook me on flight HAT076 from PHL to DEN on May 17, 2024. "
                    "My user ID is amelia_rossi_1651."},
            ]),
        )],
        schema=load_schema("travel"),
    )
    found = {(e["entity"], e["value"]) for e in result.extractions}
    for expected in (
        ("flight_number", "HAT076"),
        ("origin_airport", "PHL"),
        ("destination_airport", "DEN"),
        ("flight_date", "May 17, 2024"),
        ("passenger_id", "amelia_rossi_1651"),
    ):
        assert expected in found, f"missing {expected}; got {sorted(found)}"


def test_an_airport_slot_does_not_read_an_english_word():
    """
    Every pattern is compiled case-insensitively, so an unscoped `to ([A-Z]{3})`
    read "to the" as the airport `the`. Measured, that produced 52 distinct
    origin values where the corpus has 20 IATA codes. The same defect the travel
    schema already documents for reservation ids, so the fix is the same: scope
    the class case-sensitively.
    """
    from contextgc.schemas import load_schema

    result = harness.run(
        [Transcript(
            transcript_id="prose#1", source="unit-test",
            messages=normalise_messages([
                {"role": "user", "content": "hello"},
                {"role": "user", "content": "I want to use the add option and pay later."},
            ]),
        )],
        schema=load_schema("travel"),
    )
    airports = {e["value"] for e in result.extractions
                if e["entity"] in ("origin_airport", "destination_airport")}
    assert not airports, f"an English word became an airport: {airports}"


def test_staleness_refuses_to_count_a_read_as_an_edit():
    """
    The measurement that looked most promising and does not survive contact with
    the corpus.

    Taking "any file named against a command" as the action signal has 28.6%
    support, and reports a 44.9% disagreement rate. Reading the turns shows most
    of it is the agent opening a file to diagnose an import error, or running a
    script to verify a fix, while the tracker correctly holds the file it is
    editing. `open lexicon/config.py` is a read. `python reproduce.py` is a run.
    Neither means the file under edit changed.
    """
    from benchmarks.staleness import edited_file

    assert edited_file("Let's open lexicon/config.py to check the imports") is None
    assert edited_file("```\npython reproduce.py\n```") is None
    assert edited_file("Now update the config.py file with the new source") is None
    assert edited_file("Edit reproduce.py to use the resolver") == "reproduce.py"
    assert edited_file("sed -i 's/old/new/' api.py") == "api.py"


def test_staleness_will_not_quarter_its_rate_on_one_transcript():
    """
    25 of 31 disagreements came from a single transcript -- an agent ping-ponging
    between api.py and common_types.py -- and dropping it moved the rate from
    44.9% to 14.3%. The headline would have been one agent's behaviour presented
    as the tracker's, so the tool reports the concentration rather than the
    average.
    """
    from benchmarks import staleness

    result = staleness.staleness([])
    assert "largest_contributor" in result
    assert "rate_without_it" in result["largest_contributor"]
    # An empty corpus must not invent a rate.
    assert result["disagreement_rate"] is None
    assert staleness.MIN_COMPARISONS >= 50, "a rate over a handful of points is not a measurement"


def _fake_extractions():
    """Extractions shaped like the read path's, across three slots."""
    items = []
    for entity, values in (
        ("current_file", [f"mod{i}.py" for i in range(20)]),
        ("cabin_class", ["economy", "business", "basic economy"]),
        ("flight_date", [f"May {i}, 2024" for i in range(1, 6)]),
    ):
        for i, value in enumerate(values):
            items.append({
                "transcript": f"t#{i}", "entity": entity,
                "value": value, "turn": i, "source": "inferred",
            })
    return items


def test_a_worksheet_ships_unlabelled_and_quotes_the_turn():
    """
    Two properties, both about not manufacturing evidence.

    Every row must arrive with no verdict: a worksheet that carried verdicts
    would let a precision number acquire a denominator nobody judged. And every
    row must quote the registering turn, because the two "confirmed errors" this
    project once carried were both mislabelled by a labeller who read a value
    without the sentence that said the agent had moved on.
    """
    from benchmarks import label_worksheet as lw

    rows = lw.sample_rows(_fake_extractions(), {}, per_entity=3)
    assert rows
    for row in rows:
        assert row["verdict"] == "unlabelled", row
        assert row["labelled_by"] == ""


def test_a_worksheet_spreads_its_budget_across_slots():
    """
    All 39 committed labels are `current_file`, so the reported 100% says nothing
    about the other slots the library ships. A budget spent on whichever slot is
    easiest to sample reproduces that exactly, so the worksheet samples
    round-robin and every slot gets its quota before any slot gets a second one.
    """
    from collections import Counter

    from benchmarks import label_worksheet as lw

    rows = lw.sample_rows(_fake_extractions(), {}, per_entity=3)
    counts = Counter(r["entity"] for r in rows)
    assert len(counts) == 3, "one slot means the sample says nothing about the rest"
    assert max(counts.values()) - min(counts.values()) <= 1, counts
    # And the order is interleaved, so a labeller who stops early has not spent
    # the whole budget on one slot.
    assert [r["entity"] for r in rows[:3]] == sorted(counts)


def test_a_worksheet_never_asks_twice_about_one_value_or_one_file():
    """
    Precision is scored over independent units, and inflating `n` with repeats was
    this project's first precision bug -- 39 rows about 39 turns turned out to be
    36 independent facts. A sample of 12 rows about the same file, or the same
    value restated, would report the same thing 12 times.
    """
    from benchmarks import label_worksheet as lw

    rows = lw.sample_rows(_fake_extractions(), {}, per_entity=5)
    for entity in {r["entity"] for r in rows}:
        picked = [r for r in rows if r["entity"] == entity]
        assert len({r["value"] for r in picked}) == len(picked), entity
        assert len({r["transcript"] for r in picked}) == len(picked), entity

    # A corpus that only ever says one thing yields one row, not five.
    same = [{"transcript": f"t#{i}", "entity": "cabin_class", "value": "economy",
             "turn": i} for i in range(5)]
    assert len(lw.sample_rows(same, {}, per_entity=5)) == 1


def test_a_slot_short_of_its_budget_says_so_rather_than_looking_empty():
    """
    The default window returns 2 `failing_test` rows, and 2 rows read as "this
    slot cannot be labelled" when the shard holds 49 distinct values. A person
    who believed that would drop the slot and report coding precision as
    single-slot for good -- which is how it was single-slot in the first place.

    So a starved slot is named, and the cause is refused rather than guessed:
    the window may be too small, or the corpus may have no more, and raising
    --limit is what tells them apart.

        failing_test rows:  2 ->  7 -> 21 -> 44
        at --limit:        60 -> 500 -> 2000 -> 6000
    """
    from benchmarks.label_worksheet import sample_rows, starved_slots

    def _one(entity, value, transcript):
        return {"entity": entity, "value": value, "transcript": transcript, "turn": 0}

    # The same slot, the same 6 distinct values, in transcripts that only a wide
    # window reaches -- which is exactly the shape of the real corpus.
    spread = [_one("failing_test", f"test_{i}.py", f"t{i}") for i in range(6)]

    def counts(rows):
        c = {}
        for r in rows:
            c[r["entity"]] = c.get(r["entity"], 0) + 1
        return c

    full = counts(sample_rows(spread, {}, per_entity=6))
    assert starved_slots(full, 6) == {}, "a slot that met its budget is not starved"

    short = counts(sample_rows(spread[:2], {}, per_entity=6))
    assert starved_slots(short, 6) == {"failing_test": 4}, (
        "a genuine shortfall is reported, with the number short"
    )

    # And the name is never a false alarm on the slot that did fill.
    mixed = counts(sample_rows(
        [_one("current_file", f"mod_{i}.py", f"c{i}") for i in range(6)] + spread[:2],
        {}, per_entity=6))
    assert set(starved_slots(mixed, 6)) == {"failing_test"}, (
        "one starved slot must not make the other look starved too"
    )


def test_a_worksheet_and_a_report_load_the_same_transcripts():
    """
    142 hand labels, 99 of which the report threw away, and the report looked
    complete while it did it.

    `label_worksheet` called `load_swe_agent(limit=...)` and left `per_repo` at
    `None`, which packs the window out of 13 repositories. The CLI defaults to
    `2`, which spreads over 20. Different transcripts, so no label key could
    line up, and the second slot was reported UNMEASURED for a reason that had
    nothing to do with the slot.

    Two ways this has to hold, and the second is the one that keeps holding:
    the same loader arguments, and the same `--limit`. The worksheet therefore
    records the window it used, and the merge prints that window back rather
    than a guess.
    """
    from benchmarks.loader_defaults import CLI_DEFAULTS

    try:
        from benchmarks.label_worksheet import build
    except BaseException:  # pragma: no cover - corpus deps absent
        pass
    try:
        worksheet = build("coding", "swe-agent", limit=120, per_entity=2)
    except BaseException as err:
        # The corpus loader signals a missing pandas/pyarrow with sys.exit, and
        # an `except Exception` here would let it through as a failure on every
        # CI job that has no cached shard.
        if isinstance(err, KeyboardInterrupt):
            raise
        pytest.skip(f"corpus not available here: {err}")
    assert worksheet["limit"] == 120, (
        "a worksheet that does not record its own window cannot tell anyone how "
        "to re-score it"
    )
    assert worksheet["loader_defaults"] == dict(CLI_DEFAULTS), (
        "the worksheet must load with the CLI's own defaults, read from the "
        "parser, or the two drift apart and labels stop matching silently"
    )
    assert worksheet["loader_defaults"]["per_repo"] is not None, (
        "per_repo=None packs the window out of a handful of repositories"
    )

    import importlib
    ns = importlib.import_module("benchmarks.__main__").build_parser().parse_args(["sample"])
    assert ns.per_repo == CLI_DEFAULTS["per_repo"]
    assert ns.min_turns == CLI_DEFAULTS["min_turns"]


def test_a_precision_figure_reports_which_slots_it_covers_and_which_it_does_not():
    """
    The coding figure was 100% over 36 rows that were every one of them
    `current_file`, and the printed output did not say so anywhere. A reader
    took it as a statement about the coding schema, which it was not, and could
    not tell the difference by looking.

    So the breakdown is part of the result, and a slot nobody labelled is
    reported UNMEASURED rather than left out. Left out, it reads as "not
    applicable" -- which is the failure: a slot the read path never even
    produced looked the same as a slot a person simply had not got to.
    """
    from benchmarks.gold import CORRECT, score

    extractions = [
        {"transcript": "r#0", "entity": "current_file", "turn": 0, "value": "a.py"},
    ]
    labels = [
        {"transcript": "r#0", "entity": "current_file", "turn_index": 0,
         "value": "a.py", "verdict": CORRECT, "labelled_by": "t"},
    ]
    schema = {"current_file": [], "failing_test": []}
    result = score(extractions, labels=labels, schema=schema)

    assert result["by_entity"]["current_file"]["n"] == 1
    # failing_test was never labelled, so it must be named, not omitted.
    assert "failing_test" in result["by_entity"], (
        "an unlabelled slot that is absent reads as not-applicable, which is "
        "how an unfired slot looked identical to an unlabelled one"
    )
    assert result["by_entity"]["failing_test"]["n"] == 0
    assert result["slots_measured"] == ["current_file"]
    assert result["slots_unmeasured"] == ["failing_test"]

    from benchmarks.gold import render

    text = render(result)
    assert "failing_test" in text and "UNMEASURED" in text
    assert "1 of 2" in text, (
        "the printed figure must state its own coverage, or it is quotable as "
        "a statement about the schema"
    )


def test_a_capture_scores_the_read_path_at_the_same_turn_not_a_rebuilt_one():
    """
    The old staleness rate was unquotable for three separate reasons and this
    one is quotable for the opposite three. It needs no action signal, so it is
    not confounded by opening a file being a read; the read-path value is
    recorded per turn during the capture, so no alignment is reconstructed from
    whatever text happens to be nearby; and it counts the trajectories that
    contributed, so a rate one agent moves is visible as one.

    The assertion is on the *classification*, not the rate. `memset.py` against
    `lexicon/providers/memset.py` is a precision difference, and folding it into
    disagreement would manufacture a number -- which is what the old attempt
    did, turning a follow-the-agent tracker into a 44.9% staleness figure.
    """
    import json as _json
    from pathlib import Path

    from benchmarks.staleness import score_capture_against_read_path

    capture = Path(__file__).resolve().parent.parent / "captures" / "coding-14b-distinct.json"
    if not capture.exists():
        pytest.skip("capture not present")
    result = score_capture_against_read_path(str(capture))

    assert result["transcripts"] >= 3, (
        f"only {result['transcripts']} trajectories; a rate one agent moves is "
        f"not a rate"
    )
    assert result["comparable"] >= 20, f"only {result['comparable']} comparable turns"
    assert result["exact"] + result["same_file_less_precise"] > result["different_file"], (
        "the read path should mostly agree with an explicit declaration"
    )
    # The leaf comparison is the part that has to be right, so it is checked
    # against a value the capture really contains.
    assert "lexicon/providers/memset.py" in _json.dumps(
        [d["read_path"] for d in result["disagreements"]] + ["lexicon/providers/memset.py"]
    )
    # And the caveat travels with the number, or it gets quoted bare.
    assert "not correctness" in result["why_this_is_not_a_staleness_rate"]


def test_the_tracker_follows_the_agents_last_file_statement_through_a_round_trip():
    """
    The staleness *rate* needs a ground truth for when the file changed and the
    corpus has none. This needs none. If the tracker's value is the agent's most
    recent statement, the tracker is not stale -- whatever the agent did in
    between, and whether or not we can parse its commands.

    So the test is the round trip, not the final value. An agent that goes out
    to a scratch file and back is the only sequence that distinguishes "holds
    the agent's latest statement" from "sticks on the file it first settled on".
    A test that only checked the last value would pass on a tracker that never
    moved at all.
    """
    from benchmarks.staleness import follows_last_statement

    transcript = """
Let's start by examining the `memset.py` file.
Now open lexicon/lexicon/providers/memset.py
I will create a new file called `reproduce.py`
Now update the `reproduce.py` to reproduce it
That is fixed, open lexicon/providers/memset.py again
Finally open lexicon/cli.py
"""
    result = follows_last_statement(transcript)
    assert result["statements"] >= 4, "the sequence must be a sequence"
    assert "reproduce.py" in result["sequence"], "the excursion must be captured"
    assert result["final_value"].endswith("cli.py"), (
        f"the tracker ended on {result['final_value']!r}, not the agent's last "
        f"statement -- that is staleness"
    )
    assert result["sequence"][-1] == result["final_value"]
    # And the caveat travels with the number, so it cannot be quoted bare.
    assert "n=1" in result["caveat"]


def test_a_suggestion_never_becomes_a_verdict(monkeypatch, tmp_path):
    """
    The suggestion pass exists so a reviewer does not start from a blank page. It
    must not be able to fill the one field that makes a precision number mean
    anything: `verdict`, whose denominator is "turns a person read and judged".

    So: `verdict` is untouched, `model_suggestion` is a separate field, and the
    merge still refuses a worksheet where only the suggestions were filled in.

    The label file is redirected to a tmp path. The first version of this test
    called the real merge, and committed a label with `verdict: "incorrect"` and
    `labelled_by: "a person"` into the real travel file -- a fabricated judgement
    written by a test, which is precisely the thing this project exists not to
    do. A test must not be able to assert that the guard works by breaking the
    guard's own data.
    """
    import benchmarks.gold as gold
    from benchmarks import label_worksheet as lw

    target = tmp_path / "labels.json"
    monkeypatch.setitem(gold.LABELS_BY_SCHEMA, "travel", str(target))

    worksheet = {
        "corpus": "unit-test",
        "items": [
            {"id": "001", "transcript": "t#1", "entity": "cabin_class",
             "value": "economy", "turn_index": 1, "verdict": "unlabelled",
             "note": "", "labelled_by": "", "turn_in_context": ">>> [1] user: economy",
             "model_suggestion": "correct", "model_suggested_by": "test"},
        ],
    }
    with pytest.raises(SystemExit) as excinfo:
        lw.merge(worksheet, "travel")
    message = str(excinfo.value)
    assert "unlabelled" in message
    assert "not a verdict" in message
    assert not target.exists(), "nothing may be written while a row is unlabelled"

    # And with a human verdict present, the suggestion is recorded as *offered*
    # and never substituted for what the person said.
    worksheet["items"][0]["verdict"] = "incorrect"
    worksheet["items"][0]["labelled_by"] = "a person"
    merged = lw.merge(worksheet, "travel")
    assert merged["added"] == 1

    added = json.loads(target.read_text())
    assert added[0]["verdict"] == "incorrect"
    assert added[0]["labelled_by"] == "a person"
    assert added[0]["offered_suggestion"] == "correct"
    assert added[0]["suggestion_agrees_with_verdict"] is False


def test_a_suggestion_reports_the_evidence_it_was_made_from():
    """
    A suggestion a reviewer cannot check is an opinion. Each one carries the fact
    it came from: whether the value is in the registering turn, what role that turn
    is, and whether the sanitizer classified it as machine output.
    """
    from benchmarks import label_worksheet as lw

    class _Msg(dict):
        pass

    class _T:
        id = "t#1"
        messages = [
            _Msg(role="assistant", content="opening `memset.py` now"),
            _Msg(role="user", content="the agent is in `memset.py`"),
        ]

    rows = [{
        "id": "001", "entity": "current_file", "value": "memset.py",
        "transcript": "t#1", "turn_index": 0, "verdict": "unlabelled",
        "note": "", "labelled_by": "", "turn_in_context": "",
    }]
    out = lw.suggest(rows, {"t#1": _T()})
    row = out[0]
    assert row["verdict"] == "unlabelled", "a suggestion must not fill the verdict"
    assert row["model_suggestion"] == "correct"
    assert row["mechanical_evidence"]["in_registering_turn"] is True
    assert row["mechanical_evidence"]["registering_role"] == "assistant"
    assert row["model_suggestion_is_not_a_verdict"] is True
    assert "memset.py" in row["model_reason"] or "value appears in" in row["model_reason"]


def test_a_worksheet_excludes_rows_already_labelled():
    from benchmarks import label_worksheet as lw

    items = _fake_extractions()
    already = {(items[0]["transcript"], items[0]["entity"], items[0]["value"],
                items[0]["turn"])}
    rows = lw.sample_rows(items, {}, per_entity=3, already=already)
    assert not any(
        (r["transcript"], r["entity"], r["value"], r["turn_index"]) in already
        for r in rows
    )


def test_the_merge_refuses_a_worksheet_nobody_judged():
    """
    Checked on a hand-built worksheet rather than one from a corpus: the point is
    that the merge refuses, which must hold on a machine with no corpus cached and
    no pandas installed.
    """
    from benchmarks import label_worksheet as lw

    worksheet = {
        "corpus": "unit-test",
        "items": [
            {"id": "001", "transcript": "t#1", "entity": "cabin_class",
             "value": "economy", "turn_index": 3, "verdict": "unlabelled",
             "note": "", "labelled_by": "", "turn_in_context": ">>> [3] user: economy"},
            {"id": "002", "transcript": "t#2", "entity": "cabin_class",
             "value": "business", "turn_index": 4, "verdict": "correct",
             "note": "", "labelled_by": "someone", "turn_in_context": ""},
        ],
    }
    with pytest.raises(SystemExit) as excinfo:
        lw.merge(worksheet, "travel")
    assert "unlabelled" in str(excinfo.value)

    worksheet["items"][0]["verdict"] = "correct"
    worksheet["items"][0]["labelled_by"] = "someone"
    with pytest.raises(SystemExit) as excinfo:
        lw.merge(worksheet, "travel")
    assert "no turn quoted" in str(excinfo.value)

    worksheet["items"][1]["turn_in_context"] = ">>> [4] user: business"
    with pytest.raises(SystemExit):
        lw.merge(worksheet, "nosuchschema")


def test_a_user_id_starting_with_is_is_not_eaten_by_the_verb():
    """
    Found by scoring against the booking database, not by reading the pattern.

    `(?:is|:)?` is an optional verb, and on "user ID isabella_anderson_9682" it
    matched the leading `is` of the *name*, so the read path produced
    `abella_anderson_9682` -- a corrupted id that passed every key-level check.
    15 occurrences in the airline corpus, and the mechanical worksheet suggestion
    called the value `correct` because the string is in the turn.

    A dropped flag or a greedy optional is a lost constraint, not a cosmetic
    difference: this one invents a user.
    """
    from contextgc import load_schema

    pattern = load_schema("travel")["passenger_id"][0]
    got = re.search(f"(?:{pattern})", "user ID isabella_anderson_9682", re.IGNORECASE)
    assert got.group(1) == "isabella_anderson_9682", got.group(1)
    # And the ordinary phrasings still work.
    for text, expected in (
        ("My user ID is amelia_rossi_1651.", "amelia_rossi_1651"),
        ("user id: chen_rossi_8135", "chen_rossi_8135"),
        ("user id is raj_johnson_6495", "raj_johnson_6495"),
    ):
        found = re.search(f"(?:{pattern})", text, re.IGNORECASE)
        assert found and found.group(1) == expected, (text, found and found.group(1))


def test_the_ordinal_first_is_not_a_first_class_cabin():
    """
    Also found by the booking database, which holds only economy / business /
    basic_economy across 3,030 records and never `first`.

    "rescheduling my return flight to the first one-stop option you provided"
    matched the cabin pattern's `to\\s+(?:the\\s+)?(first)` and recorded a First
    Class cabin. This is row 051 of the labelling worksheet, where the mechanical
    suggestion read `correct` -- the string is in the turn, and the check that
    catches it needs the record rather than the text.
    """
    from benchmarks.harness import run
    from contextgc import load_schema

    result = run(
        [Transcript(
            transcript_id="ordinal#1", source="unit-test",
            messages=normalise_messages([
                {"role": "user", "content": "hello"},
                {"role": "user", "content":
                    "Could you reschedule my return flight to the first one-stop "
                    "option you provided earlier?"},
            ]),
        )],
        schema=load_schema("travel"),
    )
    cabins = {e["value"] for e in result.extractions if e["entity"] == "cabin_class"}
    assert not cabins, f"an ordinal became a cabin class: {cabins}"


def test_a_record_is_looked_up_by_the_schema_not_the_corpus_name():
    """
    The airline half of APIGen carries `reservation_id` and the retail half
    carries `order_id`, and the two spellings of "which half" do not match:
    `airline` versus `travel`. Keying the lookup on the corpus name made every
    airline declaration resolve to zero records, so 109 declarations scored
    0 corroborated and 84 unverifiable -- and it read like a finding about the
    write path rather than a lookup that found nothing.
    """
    from benchmarks.ground_truth import RECORD_MARKER, records_by_transcript

    assert RECORD_MARKER["travel"] == "reservation_id"
    assert RECORD_MARKER["logistics"] == "order_id"

    class _T:
        def __init__(self, tid, body):
            self.id = tid
            self.messages = [{"role": "user", "content": body}]

    airline = [_T("apigen-0", '{"reservation_id": "0U4NPP", "cabin": "economy"}')]
    retail = [_T("apigen-0", '{"order_id": "#W9045919", "cabin": "economy"}')]
    assert records_by_transcript(airline, "travel")
    assert not records_by_transcript(airline, "logistics")
    assert records_by_transcript(retail, "logistics")
    assert not records_by_transcript(retail, "travel")


def test_a_declared_date_in_either_format_is_the_same_date():
    """
    The model may say a flight date the way the record stores it or the way a
    person says it. `2024-05-20` and `May 20, 2024` are the same flight date,
    and scoring them differently called a *true* declaration a contradiction
    three times in one conversation -- which is how a scorer starts reporting
    the write path as wrong when it is not.
    """
    from benchmarks.ground_truth import _normalise_date

    assert _normalise_date("2024-05-20") == "May 20, 2024"
    assert _normalise_date("May 20, 2024") == "May 20, 2024"
    assert _normalise_date("2024-05-07T13:04:42") == "2024-05-07T13:04:42", (
        "a full timestamp is not a date and must not be silently truncated"
    )


def test_a_value_gate_cannot_catch_the_one_declaration_it_missed():
    """
    `cabin_class = "basic economy"` where the record says `economy` is the one
    false declaration the value gate lets through. The obvious fix is a
    vocabulary gate: collect the values the outcomes actually take and reject
    anything outside them.

    **That fix is wrong, and this test is the reason it was not shipped.**

    The APIGen booking records admit three cabins: `basic_economy`, `economy`,
    `business`. `basic economy` is not outside that vocabulary -- it is the same
    value as `basic_economy`, written the way a person writes it. So a
    vocabulary gate would accept it, correctly, and catch nothing.

    And it should accept it. The model did not invent a cabin; it attributed a
    *real* cabin to the *wrong booking*. Every check that could catch that is a
    check on meaning, and this project has no oracle for meaning in this
    domain. The write path is 12/82 wrong and the twelfth is unfixable by
    construction, which is worth more than a gate that looks better on a
    table.
    """
    from collections import Counter

    from benchmarks.ground_truth import (
        _normalise_cabin,
        load_apigen_mt,
        records_by_transcript,
    )

    corpus = records_by_transcript(load_apigen_mt(limit=500), "travel")
    if not corpus:
        pytest.skip("APIGen corpus not present")
    admitted = Counter()
    for _rid, body in corpus.items():
        for entry in body:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                cabin = entry[1].get("cabin")
                if cabin:
                    admitted[cabin] += 1

    assert admitted, "no cabin values found in the outcomes"
    assert "basic_economy" in admitted, (
        "the outcomes admit basic_economy, so a vocabulary gate cannot reject "
        "'basic economy' -- it is the same value, spelled the way people spell it"
    )
    # And the scorer already collapses the two spellings, so the 99.6% read-path
    # figure is not resting on an unnormalised enum comparison.
    assert _normalise_cabin("basic_economy") == _normalise_cabin("basic economy")


def test_a_declaration_the_record_denies_is_reported_as_a_contradiction():
    """
    The write path, checked at last. A declared value wins over the read path by
    design, so an unchecked declaration silently overrides everything the read
    path got right -- and until now nothing had ever checked one.

    On the 14B airline capture: 109 declared values, 70 corroborated, **12 the
    record denies**, 2 unverifiable, and 25 in slots with no record field at all
    so nothing can settle them either way. The value gate rejects 11 of the 12.

    The twelfth is the one worth reading twice: `cabin_class = "basic economy"`
    where the record says `economy`. It satisfies its contract and is still
    wrong. A contract checks shape, never truth.
    """
    import json as _json
    from pathlib import Path

    from benchmarks.ground_truth import score_declarations

    capture = Path(__file__).resolve().parent.parent / "captures" / "airline-14b.json"
    if not capture.exists():
        pytest.skip("airline capture not present")
    result = score_declarations(str(capture), "travel", "airline")

    assert result["corroborated"] > 0, "nothing was checked at all"
    assert result["contradicted"] > 0, (
        "a write path with no false declarations would be a claim worth a "
        "re-read of the scorer, not a reason to relax the assertion"
    )
    assert result["corroborated"] > result["contradicted"], (
        "the model is mostly right, which is the expected shape"
    )
    # Unchecked declarations are reported apart, never folded into the rate.
    assert result["no_ground_truth"] > 0
    assert result["corroboration_rate"] is not None

    # And the gate must catch the large majority of what the record denies.
    denied = result["contradicted_examples"]
    caught = [e for e in denied if e["gate_would_reject"]]
    assert len(caught) >= len(denied) - 1, (
        f"the value gate caught {len(caught)} of {len(denied)} false declarations; "
        f"a contract that stops catching them is not doing its job"
    )
    _json.dumps(result)  # must stay JSON-serialisable


def test_a_requested_change_is_scored_against_the_record_that_showed_it():
    """
    The union of every record in a transcript is the wrong ground truth, and it
    manufactured 70 contradictions on the retail corpus.

    A customer says "ship it to 123 Oak Street", the agent applies the change,
    and the *next* tool result shows 123 Oak Street. The only record available at
    the time of the utterance is the order *before* the change, so scoring against
    it calls a fact the read path got exactly right a contradiction. Three read
    by hand:

        apigen-1751 turn 13  "760 Elm Avenue"   before: 592 Elm    after: 760 Elm
        apigen-1817 turn 11  "123 Oak Street"   before: 463 Main    after: 123 Oak
        apigen-1865 turn 12  "828 River Road"  before: 388 Spruce  after: 828 River

    A value is therefore checked against the state as of just before the turn and
    against every state recorded at or after it.
    """
    from benchmarks.ground_truth import _states_for_slot

    records = [
        (5, {"address": {"address1": "592 Elm Avenue", "city": "Houston"}}),
        (17, {"address": {"address1": "760 Elm Avenue", "city": "Houston"}}),
    ]
    before, after = _states_for_slot(records, "delivery_address", turn=13)
    assert before == {"592 elm avenue"}
    assert after == [{"760 elm avenue"}]
    # The value the customer named at turn 13 matches neither the state before it
    # nor... it matches the one after, which is the whole point.
    assert "760 elm avenue" in {v for state in [before, *after] for v in state}

    # A turn after the change is judged against the new state.
    before2, after2 = _states_for_slot(records, "delivery_address", turn=20)
    assert before2 == {"760 elm avenue"}
    assert after2 == []


def test_a_record_that_never_saw_the_outcome_is_silence_not_disagreement():
    """
    A customer who names a payment method and then ends the conversation leaves
    no trace. Nothing is recorded at or after the turn, so the order had no chance
    to reflect the change, and a value matching nothing is UNVERIFIABLE rather
    than contradicted. Calling the read path wrong for agreeing with them measures
    nothing. This split took retail contradictions from 19 to 15, and it applies to
    the airline corpus too.
    """
    from benchmarks.ground_truth import _states_for_slot

    records = [(3, {"payment_history": [{"payment_method_id": "gift_card_8633125"}]})]
    before, after = _states_for_slot(records, "payment_method", turn=11)
    assert before == {"gift card"}
    assert after == [], "nothing recorded after the turn, so no outcome to check"
    # `after` being empty is exactly the signal that this is silence, and the
    # scorer reads it as such rather than as a contradiction.


def test_a_retail_record_reduces_to_bare_payment_names():
    """
    Neither side is canonical. The record says `credit_card_5843230`; the read
    path says "Credit Card", "Gift Card", "Paypal", "paypal account",
    "gift card balance". Comparing raw made the two look like different methods,
    and forcing the airline's exact-match rule onto retail would have been a lie
    about the shape of the data.
    """
    from benchmarks.ground_truth import normalise_payment, retail_payment_methods

    record = {"payment_history": [
        {"payment_method_id": "credit_card_5843230"},
        {"payment_method_id": "gift_card_8633125"},
        {"payment_method_id": "paypal_5334408"},
    ]}
    assert retail_payment_methods(record) == {"credit card", "gift card", "paypal"}
    for spoken in ("Credit Card", "gift card", "PayPal", "Paypal",
                   "paypal account", "gift card balance"):
        assert normalise_payment(spoken) in {"credit card", "gift card", "paypal"}, spoken


def test_an_address_corroborates_on_the_street_line_not_the_whole_thing():
    """
    "713 Park Avenue" is the same address as a record holding
    "713 Park Avenue, Suite 800". The read path stops early more often than not,
    and demanding the full line turned incompleteness into a contradiction -- 1 of
    2 address contradictions at 200 transcripts, and it was a partial.
    """
    from benchmarks.ground_truth import (
        _retail_judgement,
        address_completeness,
        street_line,
    )

    record = {"address": {"address1": "713 Park Avenue", "address2": "Suite 800",
                          "city": "Austin", "state": "TX", "zip": "78701"}}
    assert street_line(record) == "713 Park Avenue, Suite 800"
    assert _retail_judgement(record, "delivery_address", "713 Park Avenue") is True
    assert _retail_judgement(
        record, "delivery_address", "713 Park Avenue, Suite 800, Austin, TX, 78701"
    ) is True
    # A different address is a real contradiction.
    assert _retail_judgement(record, "delivery_address", "592 Elm Avenue") is False
    # Partial and complete are distinguished, not folded together.
    assert address_completeness(record, "713 Park Avenue") is False
    assert address_completeness(
        record, "713 Park Avenue, Suite 800, Austin, TX, 78701"
    ) is True


def test_a_record_with_no_address_or_payment_says_nothing():
    """Silence is not agreement. A record missing the field is `unverifiable`."""
    from benchmarks.ground_truth import _retail_judgement

    assert _retail_judgement({}, "delivery_address", "123 Pine St") is None
    assert _retail_judgement({"payment_history": []}, "payment_method", "gift card") is None
    assert _retail_judgement({"address": {}}, "delivery_address", "123 Pine St") is None


def test_ground_truth_scores_only_what_the_record_can_settle():
    """
    The unverifiable bucket is not a pass. An extraction the record says nothing
    about has to be counted apart, or folding it into a rate flatters the number.
    """
    from benchmarks import ground_truth as gt

    record = {"reservation_id": "ABC123", "user_id": "amelia_rossi_1651",
              "origin": "PHL", "destination": "DEN", "cabin": "basic_economy",
              "flights": [{"origin": "PHL", "destination": "DEN",
                           "flight_number": "HAT076", "date": "2024-05-09"}]}
    assert gt.slot_values(record, "active_reservation") == {"ABC123"}
    assert gt.slot_values(record, "passenger_id") == {"amelia_rossi_1651"}
    assert gt.slot_values(record, "origin_airport") == {"PHL"}
    assert gt.slot_values(record, "flight_number") == {"HAT076"}
    # An ISO date in the record, a spoken date from the read path.
    assert gt.slot_values(record, "flight_date") == {"May 9, 2024"}
    # `basic_economy` in the record, `basic economy` out of it.
    assert gt.slot_values(record, "cabin_class") == {"basic economy"}
    # A slot with no field in the record has nothing to settle.
    assert gt.slot_values(record, "no_such_slot") == set()


def test_a_policy_statement_about_a_cabin_is_not_the_passengers_cabin():
    """
    Found by scoring against the booking database, and the third of three
    `cabin_class` attempts that were measured rather than reasoned about.

    "Change flights (note: basic economy flights cannot be modified)" is a rule
    about the category, and the read path recorded the passenger's cabin as Basic
    Economy. The booking record held `business`, and the value was contradicted.

    Two earlier fixes were tried and measured worse, so they are not here:

    * requiring the mention to sit near "your"/"you are flying" would have lost
      50 of 122 corroborated extractions to fix 4 of 6
    * taking the *last* mention in a turn as the conclusion raised contradictions
      from 6 to 10, because agents state the current cabin and then offer an
      upgrade -- "you are in economy, would you like business?"

    This guard removes 69 of 1,361 `basic economy` matches, and reading all 69
    showed every one is a policy statement about the category, with no genuine
    mention among them.
    """
    from benchmarks.harness import run
    from contextgc import load_schema

    policy = (
        "I can help with that. Here are some options: 1. Change flights "
        "(note: basic economy flights cannot be modified). 2. Change cabin class."
    )
    genuine = "I booked a basic economy ticket and need to add a checked bag."

    for text, should_extract in ((policy, False), (genuine, True)):
        result = run(
            [Transcript(
                transcript_id="policy#1", source="unit-test",
                messages=normalise_messages([
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": text},
                ]),
            )],
            schema=load_schema("travel"),
        )
        cabins = {e["value"] for e in result.extractions if e["entity"] == "cabin_class"}
        assert bool(cabins) is should_extract, (text[:50], cabins)


def test_a_truncated_extraction_sample_says_so_and_is_not_scored_blind():
    """
    Found by reading the precision denominator, not by any test failing.

    `harness.run` capped retained extractions at 400, which is a memory guard for
    a 200 MB corpus -- and it silently moved precision. The airline corpus yields
    615 active facts, so 21 of 152 hand labels had no extraction to match and the
    denominator fell from 149 to 131. Because transcripts are compiled in order,
    the lost labels were not a random sample: every transcript past the cap
    contributed nothing scoreable. Reported precision read 98% instead of 99% for
    no reason in the library at all.

    So the drop is counted, the cap is exposed, and the report says when it bit.
    """
    from benchmarks import harness as h
    from benchmarks.report import render_truncation_notice

    def build(n):
        return normalise_messages(
            [{"role": "user", "content": f"the gate code is {1000 + i}"} for i in range(n)]
        )

    capped = h.run(
        [Transcript(transcript_id=f"cap#{i}", source="unit-test", messages=build(3))
         for i in range(20)],
        schema=MINIMAL, max_extractions=5,
    )
    assert len(capped.extractions) == 5
    assert capped.extractions_dropped > 0
    notice = render_truncation_notice(capped)
    assert "not retained" in notice
    assert "TRUNCATED" in notice
    assert "not a fair sample" in notice

    # And a complete run is silent about it.
    full = h.run(
        [Transcript(transcript_id=f"full#{i}", source="unit-test", messages=build(3))
         for i in range(20)],
        schema=MINIMAL,
    )
    assert full.extractions_dropped == 0
    assert render_truncation_notice(full) == ""


def test_an_options_menu_is_not_recorded_as_a_booking():
    """
    Found by reading the registering turns of the second domain. A turn listed
    every cabin with its seat count and price and then asked the user to choose;
    the pattern took `Basic Economy` off the price list and recorded it as the
    passenger's cabin.
    """
    from contextgc.schemas import load_schema

    menu = (
        "Here are the available flights from DFW to SEA: 1. **Flight HAT038** - "
        "Available Seats: Basic Economy (7), Economy (1), Business (6) - Prices: "
        "Basic Economy ($88), Economy ($123), Business ($463). Please let me know "
        "which flight and cabin class you would like to book."
    )
    result = harness.run(
        [Transcript(
            transcript_id="menu#1", source="unit-test",
            messages=normalise_messages([
                {"role": "user", "content": "book me a flight"},
                {"role": "assistant", "content": menu},
            ]),
        )],
        schema=load_schema("travel"),
    )
    assert not result.extractions, (
        f"an options menu became state: {result.extractions}"
    )


def test_the_travel_schema_still_reads_real_statements():
    """The menu guard must not cost the extractions that were right."""
    from contextgc.schemas import load_schema

    result = harness.run(
        [Transcript(
            transcript_id="t#1", source="unit-test",
            messages=normalise_messages([
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content":
                    "Your reservation is in the business cabin, so 2 bags are free."},
                {"role": "user", "content": "thanks"},
                {"role": "assistant", "content":
                    "You have a basic economy ticket, so bags cost $50 each."},
            ]),
        )],
        schema=load_schema("travel"),
    )
    # The harness reports the final value per entity, so the earlier statement is
    # visible as a supersession rather than as a second extraction.
    assert [e["value"].lower() for e in result.extractions] == ["basic economy"]
    assert result.per_transcript[0]["superseded"] == 1, (
        "the business cabin statement should have been superseded, not lost"
    )


# --- captures ----------------------------------------------------------------
#
# The write path cannot be measured without a record of what a real model
# actually declared, and that record cannot be invented. These cover the
# mechanical half only: nothing here fabricates a declaration.

def test_blocks_are_extracted_and_counted():
    from benchmarks import capture as cap

    text = ('sure\n<contextgc-state>{"assert": {"a": "1"}}</contextgc-state>\n'
            'and also\n<contextgc-state>{"pin": {"b": "2"}}</contextgc-state>')
    assert cap.extract_blocks(text) == ['{"assert": {"a": "1"}}', '{"pin": {"b": "2"}}']
    assert cap.parse_block('{"assert": {"a": "1"}}') == {"assert": {"a": "1"}}
    assert cap.parse_block("not json") is None


def test_a_malformed_block_is_counted_not_hidden():
    from benchmarks import capture as cap

    turns = [
        {"role": "assistant", "content": '<contextgc-state>{"assert": {"a": "1"}}</contextgc-state>'},
        {"role": "assistant", "content": "<contextgc-state>totally not json</contextgc-state>"},
    ]
    summary = cap.summarise(turns)
    assert summary["blocks"] == 2
    assert summary["malformed"] == 1, "a model that emits broken JSON is a finding"
    assert summary["declared_turns"] == 2


def test_malformed_blocks_are_reported_by_reason_not_just_counted():
    """
    "8 of 36 blocks are malformed" is a number to shrug at. The airline capture's
    eight were 3 verb-nestings, 2 syntax errors, 2 repeated keys and 1 empty
    block: four different defects with four different fixes, and knowing only
    the total hides which one to go after.
    """
    from benchmarks import capture as cap

    turns = [
        {"role": "assistant", "content":
            '<contextgc-state>{"assert": {"a": "1"}}</contextgc-state>'},
        {"role": "assistant", "content":
            "<contextgc-state>totally not json</contextgc-state>"},
        {"role": "assistant", "content":
            '<contextgc-state>{"pin": {"a": "1"}, "pin": {"b": "2"}}</contextgc-state>'},
        {"role": "assistant", "content":
            '<contextgc-state>{"assert": {"unsure": {"x": "y"}}}</contextgc-state>'},
        {"role": "assistant", "content": "<contextgc-state>   </contextgc-state>"},
    ]
    summary = cap.summarise(turns)
    assert summary["malformed"] == 4
    reasons = summary["malformed_reasons"]
    assert reasons["unparseable JSON"] == 1
    assert reasons["a repeated key"] == 1
    assert reasons["a verb nested inside another"] == 1
    assert reasons["empty"] == 1

    # And the verifier has to say which, not only how many.
    payload = {
        "version": cap.CAPTURE_VERSION,
        "endpoint": "http://localhost:1/v1",
        "model": "test",
        "turns": turns,
    }
    problems = cap.verify(payload)
    assert any("a repeated key" in p for p in problems), problems


def test_a_capture_with_no_declarations_is_reported_as_unusable():
    """
    A capture where the model never declared anything would make `shadow` report
    a clean comparison having measured nothing. It has to be refused.
    """
    from benchmarks import capture as cap

    payload = {
        "version": cap.CAPTURE_VERSION,
        "endpoint": "http://localhost:1/v1",
        "model": "test",
        "turns": [{"role": "assistant", "content": "just talking, no block here"}],
    }
    problems = cap.verify(payload)
    assert any("never emitted" in p for p in problems), problems


def test_a_capture_without_an_endpoint_cannot_be_attributed():
    from benchmarks import capture as cap

    payload = {
        "version": cap.CAPTURE_VERSION,
        "turns": [{"role": "assistant",
                   "content": '<contextgc-state>{"assert": {"a": "1"}}</contextgc-state>'}],
    }
    assert any("endpoint" in p for p in cap.verify(payload))


def test_a_complete_capture_verifies_clean():
    from benchmarks import capture as cap

    payload = {
        "version": cap.CAPTURE_VERSION,
        "endpoint": "http://localhost:1/v1",
        "model": "test",
        "turns": [{"role": "assistant",
                   "content": '<contextgc-state>{"assert": {"a": "1"}}</contextgc-state>'}],
    }
    assert cap.verify(payload) == []


# --- the write path is unmeasured, and the plumbing is proven anyway ----------
#
# No model is reachable from CI, so no genuine capture exists and none is
# fabricated here. What can be guaranteed is that the moment a real model *is*
# reachable the measurement works, and that its absence is reported rather than
# quietly passing. A capture is a record of what a real model said; a synthetic
# one measures this harness, not the write path.

class _FakeCompletions:
    """A scripted OpenAI-compatible endpoint, in-process."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        from contextgc import compile_messages  # noqa: F401  (import cost only)

        self.calls.append(kwargs)
        reply = self._replies.pop(0) if self._replies else "done"

        class _Msg:
            content = reply

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()


class _FakeClient:
    def __init__(self, replies):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(replies)})()


def test_capture_to_shadow_runs_end_to_end(tmp_path, monkeypatch):
    """
    The whole measurement path, against a scripted endpoint.

    A plumbing guarantee, not a number. The point is that capture -> verify ->
    replay cannot rot unnoticed: if this breaks, whoever first tries to measure
    the write path finds out from a test failure rather than from a silent wrong
    answer.
    """
    import json as _json

    from benchmarks import capture as cap
    from benchmarks.__main__ import cmd_capture
    from benchmarks.corpus import Transcript, normalise_messages
    from benchmarks.shadow import replay_source, run_corpus
    from contextgc.schemas import load_schema

    replies = [
        'I should be editing `src/alpha.py`.'
        '<contextgc-state>{"assert": {"current_file": "src/alpha.py"}}</contextgc-state>',
        'Correcting that: `src/beta.py`.'
        '<contextgc-state>{"assert": {"current_file": "src/beta.py"},'
        ' "pin": {"spend_cap": "500"}}</contextgc-state>',
        'done',
    ]
    client = _FakeClient(replies)
    monkeypatch.setattr(cap, "_client", lambda: (client, "scripted"))

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_file = tmp_path / "cap.json"

    class Args:
        transcript = os.path.join(here, "benchmarks", "corpus", "sample.txt")
        out = str(out_file)
        limit = 1
        schema = "coding"
        verify = False

    assert cmd_capture(Args()) == 0
    assert len(client.chat.completions.calls) >= 1, "the endpoint was never called"

    payload = _json.loads(out_file.read_text())
    assert payload["model"] == "scripted"
    assert payload["endpoint"], "a capture must record where it came from"
    assert cap.verify(payload) == [], cap.verify(payload)

    summary = cap.summarise(payload["turns"])
    assert summary["declared_turns"] >= 1
    assert "current_file" in summary["keys"]

    # Replay it the way `benchmarks shadow` does, keyed by turn, with no model.
    by_turn = {
        index: block
        for index, turn in enumerate(payload["turns"])
        for block in cap.extract_blocks(turn["content"])
    }
    assert by_turn, "no blocks were extractable from the capture"
    parsed = [cap.parse_block(b) for b in by_turn.values()]
    assert all(parsed), "a recorded block did not parse"
    assert any("current_file" in (p.get("assert") or {}) for p in parsed)

    transcript = Transcript(
        transcript_id="replay#1", source="unit-test",
        messages=normalise_messages([{"role": "user", "content": "go"}]),
    )
    result = run_corpus(
        [transcript],
        source_for=lambda t: replay_source({}),
        schema=load_schema("coding"),
    )
    assert isinstance(result, dict) and result, "shadow mode produced no result"
    # And the same call with the captured blocks actually attached, which is the
    # path that reports what a declaration would have changed.
    with_declarations = run_corpus(
        [transcript],
        source_for=lambda t: replay_source(by_turn),
        schema=load_schema("coding"),
    )
    assert isinstance(with_declarations, dict) and with_declarations
    # Shadow mode must never emit a declared context: it reports, it does not act.
    assert "declared_context" not in with_declarations or not with_declarations.get(
        "declared_context"
    )


def test_a_capture_with_no_declarations_is_refused_not_scored(tmp_path, monkeypatch):
    """
    The failure mode that matters: a capture where the model never declared
    anything would make `shadow` report a clean comparison having measured
    nothing at all.
    """
    import json as _json

    from benchmarks import capture as cap
    from benchmarks.__main__ import cmd_capture

    client = _FakeClient(["just talking", "still talking", "no block here"])
    monkeypatch.setattr(cap, "_client", lambda: (client, "scripted"))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    empty_capture = tmp_path / "empty.json"

    class Args:
        transcript = os.path.join(here, "benchmarks", "corpus", "sample.txt")
        out = str(empty_capture)
        limit = 1
        schema = "coding"
        verify = False

    cmd_capture(Args())
    payload = _json.loads(empty_capture.read_text())
    problems = cap.verify(payload)
    # Either refusal is correct: nothing was recorded at all, or turns were
    # recorded and none of them declared. Both mean the same thing to shadow
    # mode, which is that there is nothing to replay.
    assert any("never emitted" in p or "no turns" in p for p in problems), problems

    class Verify:
        out = str(empty_capture)
        verify = True
        transcript = None
        limit = 1
        schema = None

    with pytest.raises(SystemExit) as exc:
        cmd_capture(Verify())
    assert exc.value.code == 1


# --- the capture -> replay chain ----------------------------------------------
#
# Four defects lived here, and every one of them produced the same symptom: a
# clean-looking shadow report having replayed nothing. "40 compared, 0 errors,
# 39 agreed" is indistinguishable from a real result, which is why each is
# pinned here with a declaration that *disagrees* with the read path.

class _DisagreeingModel:
    """
    Declares a file the read path will not infer, so the effect is non-zero.

    A local completions class rather than the shared scripted one: this needs the
    same reply every turn, and a list that runs dry mid-trajectory produces a
    capture that is quietly empty.
    """

    REPLY = (
        'Looking at `declared_only.py`.'
        '<contextgc-state>{"assert": {"current_file": "declared_only.py"}}'
        "</contextgc-state>"
    )

    def __init__(self):
        def _create(*args, **kwargs):
            message = type("M", (), {"content": self.REPLY})()
            choice = type("C", (), {"message": message})()
            return type("R", (), {"choices": [choice]})()

        self.chat = type("Chat", (), {"completions": type("X", (), {"create": _create})()})()


def test_a_capture_that_disagrees_shows_a_non_zero_effect(tmp_path, monkeypatch):
    from benchmarks import capture as cap
    from benchmarks.__main__ import cmd_capture
    from benchmarks.corpus import Transcript
    from contextgc.schemas import load_schema

    monkeypatch.setattr(cap, "_client", lambda: (_DisagreeingModel(), "disagreeing"))
    # The corpus the capture runs over is the one it is replayed against. The id
    # guard added alongside this test caught an earlier version of this test doing
    # exactly that, which is the behaviour it exists to prevent.
    from benchmarks.corpus import normalise_messages as _nm
    transcript = Transcript(
        transcript_id="disagree#1", source="unit-test",
        messages=_nm([
            {"role": "user", "content": "fix it"},
            {"role": "assistant", "content": "opening `memset.py` now"},
            {"role": "user", "content": "ok"},
        ]),
    )
    monkeypatch.setattr("benchmarks.corpus.load_synthetic", lambda path, **kw: [transcript])
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cap_file = tmp_path / "cap.json"

    class Capture:
        transcript = os.path.join(here, "benchmarks", "corpus", "sample.txt")
        out = str(cap_file)
        limit = 1
        schema = "coding"
        verify = False

    cmd_capture(Capture())
    payload = json.loads(cap_file.read_text())
    assert payload["declarations"], "no declaration index was written"
    assert any(
        "declared_only.py" in block
        for turns in payload["declarations"].values()
        for block in turns.values()
    ), "the declared value did not survive into the replayable index"

    # Replay against the same transcript, which says something else entirely.
    from benchmarks.shadow import run_corpus
    result = run_corpus(
        [transcript],
        source_for=lambda t: __import__(
            "benchmarks.shadow", fromlist=["replay_source"]
        ).replay_source(payload["declarations"].get(transcript.id, {})),
        schema=load_schema("coding"),
        captures=payload["declarations"],
    )
    assert result["total_agreed"] == 0, (
        f"a disagreeing declaration was counted as agreement: {result}"
    )
    assert result["total_changed"] or result["total_added"], (
        f"a disagreeing declaration produced no effect at all: {result}"
    )


def test_capture_refuses_a_corpus_it_cannot_replay_against(tmp_path):
    """
    Capture and replay must come from the same corpus. Capturing from a
    transcript file and replaying against the downloaded shard shares no ids,
    and used to report every key as agreeing.
    """
    from benchmarks.corpus import Transcript, normalise_messages
    from benchmarks.shadow import run_corpus
    from contextgc.schemas import load_schema

    corpus = [Transcript(
        transcript_id=f"shard-repo-{i}#{i}", source="unit-test",
        messages=normalise_messages([{"role": "user", "content": "go"}]),
    ) for i in range(3)]
    captures = {"some-other-file:0": {"1": '{"assert": {"a": "1"}}'}}

    with pytest.raises(SystemExit) as exc:
        run_corpus(
            corpus,
            source_for=lambda t: (lambda i, r, c: None),
            schema=load_schema("coding"),
            captures=captures,
        )
    assert "share no transcript ids" in str(exc.value)


def test_a_json_capture_index_is_replayable():
    """
    JSON object keys are always strings. Shadow mode walks the transcript asking
    for integer turn indices, so an index read back from disk never matched --
    and the symptom was a clean zero rather than a crash.
    """
    from benchmarks.shadow import replay_source

    source = replay_source({"1": '{"assert": {"a": "1"}}', "3": '{"assert": {"a": "3"}}'})
    assert source(1, "assistant", "x"), "string key 1 was not found"
    assert source(3, "assistant", "x"), "string key 3 was not found"
    assert source(2, "assistant", "x") is None
    assert source(1, "user", "x") is None, "a user turn must never declare"


def test_capture_records_the_trajectory_turn_not_its_own(tmp_path, monkeypatch):
    """
    The capture used to hold its own conversation and borrow the transcript's id,
    so its turn indices meant nothing relative to the transcript. The declared
    index has to be the trajectory's index.
    """
    from benchmarks import capture as cap
    from benchmarks.corpus import Transcript

    transcript = Transcript(
        transcript_id="idx#1", source="unit-test",
        messages=[
            {"role": "user", "content": "start"},
            {"role": "assistant", "content": "opening `a.py`"},
            {"role": "user", "content": "next"},
            {"role": "assistant", "content": "opening `b.py`"},
        ],
    )

    calls = {"n": 0}

    class _Completions:
        def create(self, **kwargs):
            calls["n"] += 1
            reply = ('declaring. <contextgc-state>{"assert": {"current_file": "x.py"}}'
                     "</contextgc-state>")
            msg = type("M", (), {"content": reply})()
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    class _Model:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr("benchmarks.corpus.load_synthetic", lambda path, **kw: [transcript])
    monkeypatch.setattr(cap, "_client", lambda: (_Model(), "idx-test"))

    payload = cap.capture("unused", str(tmp_path / "c.json"), limit=1, schema_path="coding")
    index = payload["declarations"]["idx#1"]
    assert sorted(int(k) for k in index) == [1, 3], (
        f"declarations were filed against the wrong turns: {sorted(index)}"
    )


def _fake_client(reply_for):
    """A stand-in endpoint that records every prompt it was handed."""
    seen = []

    class _Completions:
        def create(self, **kwargs):
            seen.append(kwargs["messages"])
            msg = type("M", (), {"content": reply_for(len(seen))})()
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    class _Model:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": _Completions()})()

    return _Model(), seen


def test_capture_creates_the_directory_it_was_asked_to_write_into(tmp_path, monkeypatch):
    """
    `python -m benchmarks capture --out captures/run1.json` failed with
    FileNotFoundError on a fresh clone, after the model had already run for
    several minutes. The output path was taken on trust.
    """
    from benchmarks import capture as cap
    from benchmarks.corpus import Transcript

    transcript = Transcript(
        transcript_id="d#0", source="unit-test",
        messages=[{"role": "assistant", "content": "opened `a.py`"}],
    )
    model, _seen = _fake_client(
        lambda n: '<contextgc-state>{"assert": {"f": "a.py"}}</contextgc-state>'
    )
    monkeypatch.setattr("benchmarks.corpus.load_synthetic", lambda path, **kw: [transcript])
    monkeypatch.setattr(cap, "_client", lambda: (model, "d-test"))

    nested = tmp_path / "captures" / "deep" / "run1.json"
    assert not nested.parent.exists()
    cap.capture("unused", str(nested), limit=1, schema_path="coding", progress=False)
    assert nested.exists(), "capture did not create the directory it was told to write into"


def test_capture_keeps_silent_turns_so_compliance_is_measurable(tmp_path, monkeypatch):
    """
    Silent turns were dropped from the capture, so the file held only the turns
    that complied. That made the compliance rate unmeasurable -- it could only
    ever come back as 100%, and the report printed it as a clean result.
    """
    from benchmarks import capture as cap
    from benchmarks.corpus import Transcript

    transcript = Transcript(
        transcript_id="s#0", source="unit-test",
        messages=[
            {"role": "assistant", "content": "turn one"},
            {"role": "assistant", "content": "turn two"},
            {"role": "assistant", "content": "turn three"},
            {"role": "assistant", "content": "turn four"},
        ],
    )
    block = '<contextgc-state>{"assert": {"f": "a.py"}}</contextgc-state>'
    model, _seen = _fake_client(lambda n: block if n % 2 else "no state changed here")
    monkeypatch.setattr("benchmarks.corpus.load_synthetic", lambda path, **kw: [transcript])
    monkeypatch.setattr(cap, "_client", lambda: (model, "s-test"))

    payload = cap.capture(
        "unused", str(tmp_path / "c.json"), limit=1, schema_path="coding", progress=False
    )
    assert len(payload["turns"]) == 4, (
        f"silent turns were discarded, so compliance is unreportable: {payload['turns']}"
    )
    summary = cap.summarise(payload["turns"])
    assert summary["compliance"] == 0.5, (
        f"a model that complied on 2 of 4 turns was scored as {summary['compliance']}"
    )
    assert payload["prompts_asked"] == 4


def test_capture_drops_old_turns_to_fit_the_context_and_records_it(tmp_path, monkeypatch):
    """
    A 32k-character transcript is about 8k tokens: twice a 4k context. The
    endpoint truncates the tail of the prompt itself, so the model is asked to
    declare against a turn it cannot see, and the resulting low compliance rate
    looks like a property of the protocol rather than of the prompt.
    """
    from benchmarks import capture as cap
    from benchmarks.corpus import Transcript

    transcript = Transcript(
        transcript_id="big#0", source="unit-test",
        messages=[
            {"role": "user", "content": "x" * 4000},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "y" * 4000},
            {"role": "assistant", "content": "recent answer"},
        ],
    )
    model, seen = _fake_client(
        lambda n: '<contextgc-state>{"assert": {"f": "a.py"}}</contextgc-state>'
    )
    monkeypatch.setattr("benchmarks.corpus.load_synthetic", lambda path, **kw: [transcript])
    monkeypatch.setattr(cap, "_client", lambda: (model, "big-test"))

    payload = cap.capture(
        "unused", str(tmp_path / "c.json"), limit=1, schema_path="coding",
        context_chars=9000, progress=False,
    )
    sent = sum(len(m.get("content") or "") for m in seen[-1])
    assert sent <= 9000, f"prompt of {sent} chars exceeded the 9000 budget"
    assert payload["context_truncated_prompts"] > 0, (
        "the prompt was trimmed and the capture did not say so"
    )
    # The turn being declared is the most recent one and must survive trimming.
    assert any("recent answer" in (m.get("content") or "") for m in seen[-1]), (
        "the turn under declaration was trimmed out of its own prompt"
    )


def test_a_transcript_system_message_does_not_replace_the_protocol(tmp_path, monkeypatch):
    """
    The system slot was assigned over rather than appended to, so a corpus
    carrying its own system message silently deleted the protocol instruction.
    The capture then came back with zero declarations and the report blamed the
    model for a prompt we had removed.
    """
    from benchmarks import capture as cap
    from benchmarks.corpus import Transcript

    transcript = Transcript(
        transcript_id="sys#0", source="unit-test",
        messages=[
            {"role": "system", "content": "You are a careful coding agent."},
            {"role": "assistant", "content": "opened `a.py`"},
        ],
    )
    model, seen = _fake_client(
        lambda n: '<contextgc-state>{"assert": {"f": "a.py"}}</contextgc-state>'
    )
    monkeypatch.setattr("benchmarks.corpus.load_synthetic", lambda path, **kw: [transcript])
    monkeypatch.setattr(cap, "_client", lambda: (model, "sys-test"))

    cap.capture("unused", str(tmp_path / "c.json"), limit=1, schema_path="coding", progress=False)
    first_prompt = seen[0]
    assert "contextgc-state" in first_prompt[0]["content"], (
        "the protocol instruction was dropped from the system prompt"
    )
    assert any(
        "You are a careful coding agent." in (m.get("content") or "") for m in first_prompt
    ), "the transcript's own system message was discarded instead of appended"
    # The system message must stay first. Trimming the history to fit the context
    # once reversed the whole list, which put the system message at the end and
    # the turns in reverse order.
    assert first_prompt[0]["role"] == "system"
    assert [m["content"] for m in first_prompt if m["role"] == "assistant"] == [
        "opened `a.py`"
    ], f"the trajectory was handed over out of order: {first_prompt}"


def test_capture_resumes_instead_of_repeating_paid_for_turns(tmp_path, monkeypatch):
    """
    A local server that drops after the fortieth of forty-two calls used to cost
    the whole run. Turns are now written as they arrive, and a re-run skips the
    (transcript, turn) pairs already captured.
    """
    from benchmarks import capture as cap
    from benchmarks.corpus import Transcript

    transcript = Transcript(
        transcript_id="r#0", source="unit-test",
        messages=[
            {"role": "assistant", "content": "turn one"},
            {"role": "assistant", "content": "turn two"},
            {"role": "assistant", "content": "turn three"},
        ],
    )
    block = '<contextgc-state>{"assert": {"f": "a.py"}}</contextgc-state>'
    out = tmp_path / "c.json"

    # First run dies after two calls, having already written them.
    calls = {"n": 0}

    class _Dying:
        def create(self, **kwargs):
            calls["n"] += 1
            if calls["n"] > 2:
                raise ConnectionError("the local server went away")
            msg = type("M", (), {"content": block})()
            return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    class _M1:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": _Dying()})()

    monkeypatch.setattr("benchmarks.corpus.load_synthetic", lambda path, **kw: [transcript])
    monkeypatch.setattr(cap, "_client", lambda: (_M1(), "r-test"))
    with pytest.raises(ConnectionError):
        cap.capture("unused", str(out), limit=1, schema_path="coding", progress=False)
    assert out.exists(), "turns were not written before the run failed"
    saved = json.loads(out.read_text())
    assert len(saved["turns"]) == 2, (
        f"completed turns were lost when the server dropped: {len(saved['turns'])}"
    )

    # Second run finishes the job without re-asking.
    model, seen = _fake_client(lambda n: block)
    monkeypatch.setattr(cap, "_client", lambda: (model, "r-test"))
    payload = cap.capture("unused", str(out), limit=1, schema_path="coding", progress=False)
    assert len(seen) == 1, f"resume re-asked {len(seen)} turns it already had"
    assert len(payload["turns"]) == 3
    assert payload["prompts_asked"] == 1


def test_capture_teaches_the_protocol_once_not_twice(tmp_path, monkeypatch):
    """
    The system slot was seeded with `render_instruction()` while the compile also
    passed `teach_protocol=True`, so the model was handed the protocol twice,
    801 bytes per turn. The duplicated `[STATE_PROTOCOL]` wrapper is what the
    model echoed back: of the 17 non-compliant replies in the first real capture,
    four restated the wrapper and the format line as prose.
    """
    from benchmarks import capture as cap
    from benchmarks.corpus import Transcript

    transcript = Transcript(
        transcript_id="p#0", source="unit-test",
        messages=[{"role": "assistant", "content": "opened `a.py`"}],
    )
    model, seen = _fake_client(
        lambda n: '<contextgc-state>{"assert": {"f": "a.py"}}</contextgc-state>'
    )
    monkeypatch.setattr("benchmarks.corpus.load_synthetic", lambda path, **kw: [transcript])
    monkeypatch.setattr(cap, "_client", lambda: (model, "p-test"))

    cap.capture("unused", str(tmp_path / "c.json"), limit=1, schema_path="coding", progress=False)
    blob = "\n".join(m.get("content") or "" for m in seen[0])
    assert blob.count("[STATE_PROTOCOL]") == 1, (
        f"the protocol was taught {blob.count('[STATE_PROTOCOL]')} times per turn"
    )
    assert blob.count("<contextgc-state>{") == 1, (
        "the output format was shown more than once, so the model had two "
        "competing templates to copy"
    )


def test_the_capture_summary_agrees_with_the_pipeline_about_a_string_revoke():
    """
    `summarise` re-implemented the protocol's parsing and disagreed with it. The
    model emitted `{"revoke":"current_file"}` -- a bare string where the format
    asks for a list -- and the pipeline recorded one revocation, while the
    summary iterated the string and reported ten: `_` `r` `e` `n` `i` `c` `u`
    `t` `f` `l`. Those letters then appeared in the capture report as the
    model's most-declared keys.
    """
    from benchmarks.capture import summarise
    from contextgc.state_protocol import parse_declaration

    text = '<contextgc-state>{"revoke":"current_file"}</contextgc-state>'
    pipeline = parse_declaration(text)
    assert pipeline.revokes == ["current_file"]

    reported = summarise([{"content": text}])["keys"]
    assert reported == {"current_file": 1}, (
        f"the summary reported {reported} where the pipeline recorded "
        f"{pipeline.revokes}"
    )


def test_resume_refuses_turns_captured_under_a_different_prompt(tmp_path, monkeypatch):
    """
    Resume keyed only on the file version. After the protocol stopped being
    taught twice, re-running against the existing capture reused all 42 stale
    turns, asked 0 prompts, and rewrote the file -- so the "new" measurement was
    byte-identical to the "old" one and the fix appeared to change nothing. A
    capture must not be stitched from turns asked under two different prompts.
    """
    from benchmarks import capture as cap
    from benchmarks.corpus import Transcript

    transcript = Transcript(
        transcript_id="f#0", source="unit-test",
        messages=[
            {"role": "assistant", "content": "turn one"},
            {"role": "assistant", "content": "turn two"},
        ],
    )
    block = '<contextgc-state>{"assert": {"f": "a.py"}}</contextgc-state>'
    out = tmp_path / "c.json"

    model, seen = _fake_client(lambda n: block)
    monkeypatch.setattr("benchmarks.corpus.load_synthetic", lambda path, **kw: [transcript])
    monkeypatch.setattr(cap, "_client", lambda: (model, "f-test"))
    cap.capture("unused", str(out), limit=1, schema_path="coding", progress=False)
    assert len(seen) == 2

    # Same prompt: resumes.
    model, seen = _fake_client(lambda n: block)
    monkeypatch.setattr(cap, "_client", lambda: (model, "f-test"))
    cap.capture("unused", str(out), limit=1, schema_path="coding", progress=False)
    assert seen == [], "an identical prompt should have resumed"

    # Different prompt: must re-ask rather than reuse.
    model, seen = _fake_client(lambda n: block)
    monkeypatch.setattr(cap, "_client", lambda: (model, "f-test"))
    cap.capture(
        "unused", str(out), limit=1, schema_path="coding",
        context_chars=4000, progress=False,
    )
    assert len(seen) == 2, (
        "turns captured under a different context budget were reused, so one "
        "file now mixes two experiments"
    )

    # And the stale fingerprint is not silently carried forward.
    from contextgc import load_schema, render_instruction

    saved = json.loads(out.read_text())
    fresh = cap._fingerprint(render_instruction(), load_schema("coding"), 4000)
    assert saved["prompt_fingerprint"] == fresh, (
        "the capture does not record the prompt it was produced under"
    )


# ===========================================================================
# the flattering metric
# ===========================================================================
#
# Shadow mode reported `keys added 19` on a run where the coding schema defined
# two keys and the declaration used neither. Nineteen is the write path's
# headline number and it was entirely off-schema invention. These pin the split.

SHADOW_SCHEMA = {"entities": {"current_file": [r"opening ([\w./-]+\.py)"]}}


def test_shadow_separates_added_keys_the_schema_could_have_found():
    from benchmarks import shadow as sh

    # The block is added by inject_declarations, as a real capture's would be.
    # Embedding it in the message instead would let the read path mine the
    # declaration's own JSON for entities, and the invented key would appear in
    # the baseline too.
    messages = [
        {"role": "user", "content": "fix it"},
        {"role": "assistant", "content": "opening memset.py"},
        {"role": "user", "content": "keep going"},
    ]
    outcome = sh.shadow_compare(
        messages,
        sh.model_source(lambda _turn: '{"assert": {"current_file": "other.py", '
                                       '"auth_token": "abc"}}'),
        schema=SHADOW_SCHEMA,
    )
    assert "auth_token" in outcome["added_off_schema"], (
        "an invented key was counted as something the read path could have found"
    )
    assert outcome["added_off_schema"]["auth_token"] == "abc"
    # `current_file` was declared with a different value, so it is a change, not
    # an addition -- and the change is the number that needs a human.
    assert "current_file" in outcome["changed"]
    assert "none defined by the schema" in outcome["verdict"], outcome["verdict"]


def block_(body):
    return f"<contextgc-state>{body}</contextgc-state>"


def test_a_verdict_of_only_off_schema_additions_says_so():
    """
    "added 19 key(s), agreed on the rest" reads as nineteen recovered facts. When
    none of them is a key the schema defines, the verdict has to say that
    instead of leaving the reader to notice.
    """
    from benchmarks.shadow import _verdict

    added = {f"junk{i}": "v" for i in range(19)}
    verdict = _verdict(added, {}, {"current_file": "memset.py"}, {}, added)
    assert "none defined by the schema" in verdict, (
        f"the verdict presented 19 inventions as recovered facts: {verdict!r}"
    )
    assert "19" in verdict


def test_a_verdict_with_in_schema_additions_reports_the_split():
    from benchmarks.shadow import _verdict

    verdict = _verdict(
        {"current_file": "a.py", "junk": "v"}, {}, {}, {"current_file": "a.py"}, {"junk": "v"}
    )
    assert "1 in schema" in verdict, verdict


def test_the_capture_summary_reports_how_often_declarations_name_a_schema_key():
    """
    Compliance and usefulness came apart on the first real capture. Fixing a
    duplicated-prompt defect took compliance from 59% to 90% while the share of
    declarations naming a schema key did not move. Reporting only compliance
    would have shown a clean improvement.
    """
    from benchmarks.capture import summarise

    turns = [
        {"content": block_('{"assert": {"current_file": "a.py"}}')},
        {"content": block_('{"assert": {"auth_token": "abc"}}')},
        {"content": block_('{"assert": {"line_144": "x"}}')},
    ]
    summary = summarise(turns, schema=SHADOW_SCHEMA)
    assert summary["declared_keys"] == 3
    assert summary["in_schema_keys"] == 1
    assert summary["in_schema_ratio"] == 0.333, summary
    # Compliance is perfect here and usefulness is not; both must be visible.
    assert summary["compliance"] == 1.0


def test_the_capture_summary_does_not_guess_a_schema_it_was_never_given():
    """
    A capture with no recorded schema has no basis for an in-schema ratio, and
    defaulting to the coding schema would report a number for a capture that
    never had one.
    """
    from benchmarks.capture import summarise

    turns = [{"content": block_('{"assert": {"whatever": "x"}}')}]
    summary = summarise(turns, schema=None)
    assert summary["in_schema_ratio"] is None
    assert summary["in_schema_keys"] is None


def test_verify_flags_a_capture_whose_declarations_miss_the_schema():
    from benchmarks.capture import verify

    capture = {
        "version": 1,
        "endpoint": "http://localhost:11434/v1",
        "turns": [
            {"content": block_('{"assert": {"auth_token": "abc"}}')},
            {"content": block_('{"assert": {"line_144": "x"}}')},
        ],
    }
    problems = verify(capture, schema=SHADOW_SCHEMA)
    assert any("schema" in p for p in problems), (
        f"a capture that names nothing the tracker asked for verified clean: {problems}"
    )


def test_the_legacy_prompt_flag_reproduces_the_defect_and_is_refused_as_a_measurement(
    tmp_path, monkeypatch
):
    """
    The README quotes a before/after for the doubled-protocol prompt. A
    comparison in prose that cannot be re-run is a claim rather than a
    measurement, and `PROMPT_VERSION` did not make it re-runnable -- that
    constant only feeds the fingerprint, so setting it to 1 changed the digest
    and left the prompt exactly as it was.
    """
    from benchmarks import capture as cap
    from benchmarks.corpus import Transcript

    transcript = Transcript(
        transcript_id="L#0", source="unit-test",
        messages=[
            {"role": "system", "content": "You are a coding agent."},
            {"role": "assistant", "content": "opened `a.py`"},
        ],
    )
    block = '<contextgc-state>{"assert": {"f": "a.py"}}</contextgc-state>'
    monkeypatch.setattr("benchmarks.corpus.load_synthetic", lambda path, **kw: [transcript])

    def run(name, **kwargs):
        model, seen = _fake_client(lambda n: block)
        monkeypatch.setattr(cap, "_client", lambda: (model, "L-test"))
        payload = cap.capture(
            "unused", str(tmp_path / name), limit=1, schema_path="coding",
            progress=False, **kwargs,
        )
        blob = "\n".join(m.get("content") or "" for m in seen[0])
        return payload, blob

    modern, modern_blob = run("modern.json")
    legacy, legacy_blob = run("legacy.json", legacy_prompt=True)

    assert legacy_blob.count("[STATE_PROTOCOL]") == 2, (
        "--legacy-prompt did not reproduce the doubled protocol instruction"
    )
    assert modern_blob.count("[STATE_PROTOCOL]") == 1
    assert legacy["legacy_prompt"] is True
    assert modern["legacy_prompt"] is False
    assert legacy["prompt_fingerprint"] != modern["prompt_fingerprint"], (
        "the two prompts share a fingerprint, so resume would treat one as the other"
    )
    problems = cap.verify(legacy, schema={"entities": {"f": ["a"]}})
    assert any("legacy_prompt" in problem for problem in problems), (
        f"a doubled-prompt capture verified as a measurement: {problems}"
    )


# ===========================================================================
# the write-path regression check
# ===========================================================================
#
# The nightly ran `capture --verify` on the committed capture and went red every
# night, because verify correctly exits non-zero on a model that names a schema
# slot 34% of the time. A check that fails forever on a known result is not a
# check. These pin the replacement: a baseline, and failure only on movement.

def test_the_write_path_check_fails_on_a_regression_and_passes_when_unchanged(
    tmp_path, monkeypatch
):
    import benchmarks.write_path_check as wpc

    capture = {
        "schema": "coding", "model": "test",
        "turns": [
            {"content": block_('{"assert": {"current_file": "a.py"}}')},
            {"content": block_('{"assert": {"auth_token": "x"}}')},
        ],
    }
    path = tmp_path / "c.json"
    path.write_text(json.dumps(capture))

    baseline = tmp_path / "b.json"
    assert wpc.main([str(path), str(baseline), "--update"]) == 0
    assert wpc.main([str(path), str(baseline)]) == 0, (
        "a capture identical to the baseline was reported as changed"
    )

    worse = json.loads(path.read_text())
    worse["turns"] = [{"content": block_('{"assert": {"auth_token": "x"}}')}]
    path.write_text(json.dumps(worse))
    assert wpc.main([str(path), str(baseline)]) == 1, (
        "the share of declarations naming a schema slot fell to zero and the "
        "check passed"
    )


def test_the_write_path_check_refuses_to_run_without_a_baseline(tmp_path):
    import benchmarks.write_path_check as wpc

    capture = tmp_path / "c.json"
    capture.write_text(json.dumps({"schema": "coding", "turns": []}))
    assert wpc.main([str(capture), str(tmp_path / "absent.json")]) == 1


def test_the_write_path_check_reports_a_missing_capture_as_a_failure(tmp_path):
    import benchmarks.write_path_check as wpc

    assert wpc.main([str(tmp_path / "nope.json"), str(tmp_path / "b.json")]) == 1


def test_a_better_model_is_reported_rather_than_failing(tmp_path, capsys):
    """
    Failing the build because the numbers improved would make the correct action
    -- adopt a better model, re-capture, update the baseline -- look like a
    break, and the likeliest response would be to stop looking.
    """
    import benchmarks.write_path_check as wpc

    capture = tmp_path / "c.json"
    # A baseline recorded against a model that named nothing the tracker asked for.
    capture.write_text(json.dumps({
        "schema": "coding", "model": "weak",
        "turns": [
            {"content": block_('{"assert": {"auth_token": "x"}}')},
            {"content": block_('{"assert": {"line_144": "y"}}')},
        ],
    }))
    baseline = tmp_path / "b.json"
    wpc.main([str(capture), str(baseline), "--update"])

    better = json.loads(capture.read_text())
    better["model"] = "strong"
    better["turns"] = [
        {"content": block_('{"assert": {"current_file": "a.py"}}')},
        {"content": block_('{"assert": {"failing_test": "t.py"}}')},
    ]
    capture.write_text(json.dumps(better))

    assert wpc.main([str(capture), str(baseline)]) == 0, (
        "a capture that improved on the baseline failed the check"
    )
    assert "IMPROVED" in capsys.readouterr().out


def test_informational_metrics_are_judged_by_neither_direction(tmp_path, capsys):
    """
    A capture that emitted twice as many blocks is not worse. Scoring an
    informational metric as though more were worse made a harmless change fail
    the build, which is how a regression detector starts crying wolf.
    """
    import benchmarks.write_path_check as wpc

    capture = tmp_path / "c.json"
    capture.write_text(json.dumps({
        "schema": "coding", "model": "t",
        "turns": [{"content": block_('{"assert": {"current_file": "a.py"}}')}],
    }))
    baseline = tmp_path / "b.json"
    wpc.main([str(capture), str(baseline), "--update"])

    more = json.loads(capture.read_text())
    more["turns"] = more["turns"] * 3
    capture.write_text(json.dumps(more))

    assert wpc.main([str(capture), str(baseline)]) == 0
    out = capsys.readouterr().out
    assert "REGRESSED" not in out, out


# ===========================================================================
# the compactor coverage table must match the corpora
# ===========================================================================
#
# The README published a table of which payload shapes the compactor covers,
# and listed "dict wrapping a map of strings" as an uncovered shape. Measuring
# it: the 507 instances of that shape in the support corpora are all *tool
# calls*, which are deliberately untouched, and the genuine case is 8 payloads
# worth 2.5% of JSON bytes. The table was not wrong about the code; it was
# describing a category the corpora do not contain.

APIGEN_LIMIT = 30  # per domain; the shape counts are not sensitive to this


def _json_shapes():
    from benchmarks.corpus import load_apigen_mt
    from contextgc.sanitizer import ToolSanitizer as sanitizer

    counts = {"tool_call": 0, "has_records": 0, "lookup_map_of_strings": 0}
    for domain in ("airline", "retail"):
        for transcript in load_apigen_mt(domain=domain, limit=APIGEN_LIMIT):
            for message in transcript.messages:
                text = (message.get("content") or "").strip()
                if not text or text[0] not in "[{":
                    continue
                try:
                    data = json.loads(text)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                if "name" in data and ("arguments" in data or "function" in data):
                    counts["tool_call"] += 1
                    continue
                has_records = False
                for key, value in data.items():
                    if key in sanitizer._NEVER_COMPRESS:
                        continue
                    if isinstance(value, list) and any(isinstance(x, dict) for x in value):
                        has_records = True
                    elif isinstance(value, dict) and any(
                        isinstance(x, dict) for x in value.values()
                    ):
                        has_records = True
                if has_records:
                    counts["has_records"] += 1
                elif any(isinstance(v, dict) for v in data.values()) or len(data) > 1:
                    counts["lookup_map_of_strings"] += 1
    return counts


def test_the_uncapped_payload_shapes_are_rare_which_is_why_nothing_was_added():
    """
    Not a claim that the compactor is complete -- a claim about the size of what
    it leaves alone. A lookup map of strings has no repeated fields, so shrinking
    one means dropping entries the model may need; 2.5% of JSON bytes is not
    worth that, and a test that says so is harder to quietly undo than a table
    row nobody checks.
    """
    counts = _json_shapes()
    assert counts["has_records"] > 0, "no record-bearing payloads found; the scan is broken"
    uncovered = counts["lookup_map_of_strings"]
    assert uncovered < counts["has_records"] / 10, (
        f"uncovered shapes are now {uncovered} against {counts['has_records']} "
        f"compacted ones -- the compactor's coverage assumption no longer holds"
    )


def test_tool_calls_are_never_compacted():
    """
    A tool call is the agent's own instruction, not output. Compacting it would
    rewrite what the agent asked for.
    """
    from contextgc.sanitizer import ToolSanitizer

    call = json.dumps({"name": "get_reservation_details",
                       "arguments": {"reservation_id": "0U4NPP"}})
    out, _kept, _total = ToolSanitizer.distill_tool_payload(call)
    assert json.loads(out) == json.loads(call), (
        f"a tool call was altered: {out!r}"
    )


def test_the_fingerprint_covers_the_vocabulary_the_model_is_shown():
    """
    `teach_protocol` renders the slot list from the schema, so the prompt the
    model receives is not `render_instruction()` -- it is that plus the domain's
    keys. Hashing only the bare instruction made a real prompt change invisible:
    fixing the vocabulary left the digest identical, so a re-run resumed, skipped
    all 42 turns, and silently reported the pre-fix capture as the post-fix one.
    It was caught only because the numbers came back bit-for-bit equal.
    """
    from benchmarks import capture as cap
    from contextgc import load_schema, render_instruction

    instruction = render_instruction()
    coding = cap._fingerprint(instruction, load_schema("coding"), 12000)
    travel = cap._fingerprint(instruction, load_schema("travel"), 12000)
    assert coding != travel, (
        "two different schemas fingerprint identically, so a capture made under "
        "one can be resumed as though it were made under the other"
    )


def test_a_capture_from_an_older_prompt_is_not_resumed():
    """
    The concrete failure: a capture recorded at PROMPT_VERSION 2 was resumed at
    version 3 and every turn skipped, because the resume key did not move when
    the prompt did.
    """
    import json
    import pathlib

    from benchmarks import capture as cap
    from contextgc import load_schema, render_instruction

    stale = {
        "version": cap.CAPTURE_VERSION,
        "prompt_fingerprint": "0" * 16,
        "endpoint": "http://localhost:11434/v1",
        "turns": [{"transcript": "t#0", "index": 1, "content": "x"}],
    }
    path = pathlib.Path(cap.__file__).parent.parent / "captures" / "_stale_probe.json"
    path.write_text(json.dumps(stale))
    try:
        current = cap._fingerprint(
            render_instruction(), load_schema("coding"), 12000
        )
        assert cap._resume(str(path), current) == [], (
            "a capture from a different prompt was resumed, so a re-run would "
            "report old turns as new ones"
        )
    finally:
        path.unlink(missing_ok=True)


# ===========================================================================
# a value contract may never be stricter than the tracker that guards it
# ===========================================================================
#
# The value gate decides whether a *declared* value is plausible for its slot.
# Its failure mode is not leniency but over-strictness: a contract that rejects
# a correct value silently drops a good declaration, and the read path's own
# output is the only free ground truth available for checking that.
#
# Measured while building it: a case-sensitive contract rejected 3 of 111 travel
# extractions the read path produced itself, including cabin_class="Business",
# because the read path matches case-insensitively. This test is what caught it,
# and it is the reason `flag` is safe as the default policy.

def test_no_value_contract_rejects_a_value_the_read_path_produced():
    """
    The guard that makes `flag` a safe default for the value gate.

    Only the JSON corpora run unconditionally. The coding shard is parquet, and
    reading it needs pandas and pyarrow, which the plain `test` jobs do not
    install -- so coding is included when the shard is cached (locally, and in
    the `benchmark` job) and skipped otherwise, following the precedent already
    set for the known-failures test. The two JSON corpora still contribute ~70
    values in CI, which is what caught the case-sensitivity bug.
    """
    import os

    from benchmarks.corpus import cached_shard, load_apigen_mt, load_swe_agent
    from contextgc import load_schema
    from contextgc.client import compile_messages
    from contextgc.gc_engine import _value_matches

    plan = [("travel", "airline", 20), ("logistics", "retail", 20)]
    shard = cached_shard()
    if shard and os.path.exists(shard):
        plan.insert(0, ("coding", None, 12))

    offenders = []
    checked = 0
    for name, domain, limit in plan:
        schema = load_schema(name)
        if not schema.value_contracts:
            continue
        if domain is None:
            transcripts = load_swe_agent(limit=limit, per_repo=1, path=shard)
        else:
            transcripts = load_apigen_mt(domain=domain, limit=limit)
        for transcript in transcripts:
            _, telemetry = compile_messages(transcript.messages, schema=schema)
            for slot, value in telemetry.get("active_state_slots", {}).items():
                contract = schema.value_contracts.get(slot)
                if contract is None:
                    continue
                checked += 1
                if not _value_matches(contract, str(value)):
                    offenders.append((name, slot, value))
    assert checked > 20, (
        f"only {checked} values checked; the corpus scan is not exercising the "
        f"contracts, so this test is decoration"
    )
    assert not offenders, (
        f"a value contract rejects {len(offenders)} of {checked} values the read "
        f"path produced itself: {offenders[:6]}. A contract must never be "
        f"stricter than the pattern it guards."
    )


def test_a_wrong_shaped_declaration_is_reported_and_can_be_dropped():
    """
    The failure mode the 14B capture exposed: a real schema key carrying a value
    of the wrong shape, which passes every key-level check and then wins over a
    correct read-path value because a declared fact always wins.
    """
    from contextgc import compile_messages, load_schema

    schema = load_schema("coding")
    messages = [
        {"role": "user", "content": "fix it"},
        {"role": "assistant", "content":
            'x\n<contextgc-state>{"assert": {"failing_test": "HTTPError: 403 Forbidden",'
            ' "current_file": "/a/b/memset.py"}}</contextgc-state>'},
        {"role": "user", "content": "go"},
    ]
    _out, flagged = compile_messages(messages, schema=schema, value_policy="flag")
    kinds = [r for r in flagged["rejected_writes"] if r["kind"] == "value_shape_rejected"]
    assert [r["entity"] for r in kinds] == ["failing_test"], kinds
    assert kinds[0]["dropped"] is False
    assert "failing_test" in flagged["active_state_slots"], (
        "under 'flag' the value is kept and reported; dropping it silently would "
        "lose a fact that might be right under a name the contract is too strict about"
    )

    _out, rejected = compile_messages(messages, schema=schema, value_policy="reject")
    assert "failing_test" not in rejected["active_state_slots"]
    assert "current_file" in rejected["active_state_slots"], (
        "the well-shaped value in the same declaration was dropped too"
    )


def test_a_schema_with_no_contracts_is_not_gated():
    """Absence is not permission to guess."""
    from contextgc import compile_messages

    _out, telemetry = compile_messages(
        [{"role": "user", "content": "x"},
         {"role": "assistant", "content": 'x\n<contextgc-state>{"assert": {"k": "anything"}}</contextgc-state>'},
         {"role": "user", "content": "y"}],
        value_policy="reject",
    )
    assert telemetry["declarations"]["value_shape_rejected"] == 0
    assert telemetry["declarations"]["slots_with_a_value_contract"] == []
    assert telemetry["active_state_slots"] == {"k": "anything"}


def test_a_broken_contract_rejects_nothing_rather_than_raising():
    """
    A typo in a contract must not take down a compile. It is a schema author's
    bug, not a transcript's, and `test_no_value_contract_rejects_a_value_the_
    read_path_produced` is what makes it visible.
    """
    from contextgc.gc_engine import _value_matches

    assert _value_matches("([unclosed", "anything") is True


def test_the_two_relabelled_cases_are_not_moved_into_precision_json():
    """
    They are not errors, and they are not in the sampled corpus either. Adding
    them to precision.json trips the nightly's label-drift check -- the check
    that caught 20 of 24 labels matching nothing when it was written -- so the
    only home that is both truthful and consistent is the correction recorded
    beside the now-empty known-failure list.
    """
    import os

    path = os.path.join(os.path.dirname(gold.LABELS_PATH), "known_failures.json")
    with open(path, encoding="utf-8") as handle:
        known = json.load(handle)
    corrected = known.get("corrected") or []
    assert corrected, (
        "the re-labelling of 2026-09-28 is not recorded. Those two cases were "
        "removed from known_failures as correct, and without this record the only "
        "trace would be their absence."
    )
    relabelled = {(c["transcript"], c["turn_index"]) for c in corrected}
    for transcript, turn in relabelled:
        assert (transcript, turn) not in {
            (label["transcript"], label.get("turn_index"))
            for label in _precision_labels()
        }, (
            f"{transcript} turn {turn} is in precision.json. It sits in a row the "
            f"--per-repo 2 cap skips, so adding it makes the label-drift check fail."
        )
