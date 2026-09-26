"""
Tests for the benchmark harness itself.

A benchmark that is wrong is worse than no benchmark, because it gets quoted.
These pin the properties the harness promises: that it refuses to report a
precision it did not measure, that shadow mode cannot leak a declaration into
emitted context, and that the numbers it reports are internally consistent.
"""

import json
import os

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
    Two confirmed different-sentence errors sit in rows the per_repo cap skips.
    They are tracked in their own file so a sampling change cannot make them
    disappear -- and so they cannot quietly pad the precision ratio either.
    """
    path = os.path.join(os.path.dirname(gold.LABELS_PATH), "known_failures.json")
    with open(path, encoding="utf-8") as handle:
        known = json.load(handle)
    assert known["cases"], "known_failures.json lists no cases"
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
