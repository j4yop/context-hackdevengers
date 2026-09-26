"""
The measurement harness.

Runs the compiler over a corpus and reports what happened. Every number carries
the sample size it was measured on, because a percentage without ``N`` is
decoration.

What is measured, and what each number does and does not mean:

``extraction``
    How many facts the state tracker found, and from what proportion of
    transcripts. **Coverage, not quality.** A transcript yielding a fact is not
    evidence the fact is right.

``precision``
    Measured only against hand-labelled expectations (see ``gold.py``). Without
    a labelled sample this is ``None`` and the report says so rather than
    guessing. This is the number that matters and the one hardest to obtain.

``supersession``
    How often a key was re-asserted, i.e. whether the dead-branch case the
    project exists to solve actually occurs in this corpus. A corpus with no
    re-assertion cannot demonstrate the mechanism, only its absence.

``reduction``
    Token counts, measured with the same ``chars/4`` estimator the library uses.
    This is a *ratio between two numbers from the same estimator*, so it is
    comparable across runs. It is not a billing figure and not a latency proxy.

``latency``
    Wall-clock compile time, measured. Not inference latency -- nothing here
    calls a model.
"""

from typing import Any, Dict, List, Optional

from .corpus import Transcript, describe


class Measurement:
    """One number plus the sample it came from and what it does not mean."""

    __slots__ = ("name", "value", "n", "unit", "means", "does_not_mean")

    def __init__(
        self,
        name: str,
        value: Any,
        n: int,
        unit: str = "",
        means: str = "",
        does_not_mean: str = "",
    ):
        self.name = name
        self.value = value
        self.n = n
        self.unit = unit
        self.means = means
        self.does_not_mean = does_not_mean

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "n": self.n,
            "unit": self.unit,
            "means": self.means,
            "does_not_mean": self.does_not_mean,
        }


class HarnessResult:
    def __init__(self, corpus: Dict[str, Any]):
        self.corpus = corpus
        self.measurements: List[Measurement] = []
        self.per_transcript: List[Dict[str, Any]] = []
        self.extractions: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []

    def as_dict(self) -> Dict[str, Any]:
        return {
            "corpus": self.corpus,
            "measurements": [m.as_dict() for m in self.measurements],
            "per_transcript": self.per_transcript,
            "extractions": self.extractions,
            "errors": self.errors,
        }


def run(
    transcripts: List[Transcript],
    schema: Optional[Any] = None,
    invariants: Optional[List[str]] = None,
    keep_extractions: bool = True,
    max_extractions: int = 400,
) -> HarnessResult:
    """
    Compile every transcript and collect measurements.

    Args:
        transcripts: the corpus. Provenance is recorded from it.
        schema: optional ``StateDAG`` subclass or pattern mapping. Pass ``{}``
            to measure the *empty* default schema, which is what ships.
        keep_extractions: retain individual (entity, value) pairs so a human can
            label them. This is the raw material for the precision number.
    """

    # `describe` touches every transcript, so a malformed one would abort the
    # whole run before the per-transcript error handling below ever runs.
    try:
        corpus_summary = describe(transcripts)
    except Exception as exc:
        corpus_summary = {
            "count": len(transcripts),
            "source": transcripts[0].source if transcripts else "unknown",
            "note": f"corpus summary incomplete: {type(exc).__name__}: {exc}",
        }
    result = HarnessResult(corpus_summary)

    totals = {
        "raw_tokens": 0,
        "compiled_tokens": 0,
        "facts": 0,
        "transcripts_with_facts": 0,
        "supersessions": 0,
        "tool_payloads": 0,
        "retired_turns": 0,
        "conflicts": 0,
        "retirement_violations": 0,
        "context_grew": 0,
    }
    compile_ms: List[float] = []
    per_turn_tokens: List[int] = []

    for transcript in transcripts:
        try:
            compiled, telemetry = _compile_one(transcript, schema, invariants)
        except Exception as exc:  # a crash is a finding, not a skip
            result.errors.append({
                "transcript": transcript.id,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        # A transcript that cannot report its own length is still worth counting;
        # it just cannot join the length distribution.
        try:
            n_turns = transcript.n_turns
        except Exception:
            n_turns = -1

        slots = telemetry["active_state_slots"]
        dag = telemetry["dag"]
        n_facts = len(slots)
        n_superseded = len(dag.get("superseded", []))
        if n_turns >= 0:
            per_turn_tokens.append(n_turns)

        totals["raw_tokens"] += telemetry["raw_token_count"]
        totals["compiled_tokens"] += telemetry["compiled_token_count"]
        totals["facts"] += n_facts
        totals["supersessions"] += n_superseded
        totals["tool_payloads"] += telemetry["tool_payloads_compacted"]
        totals["retired_turns"] += telemetry["retired_turn_count"]
        totals["conflicts"] += len(telemetry.get("conflicts", []))
        totals["retirement_violations"] += len(telemetry.get("retirement_violations", []))
        totals["context_grew"] += 1 if telemetry.get("context_grew") else 0
        if n_facts:
            totals["transcripts_with_facts"] += 1
        compile_ms.append(telemetry["compile_time_ms"])

        result.per_transcript.append({
            "id": transcript.id,
            "turns": n_turns,
            "raw_tokens": telemetry["raw_token_count"],
            "compiled_tokens": telemetry["compiled_token_count"],
            "reduction_pct": telemetry["compression_ratio_pct"],
            "growth": telemetry.get("token_growth", 0),
            "context_grew": telemetry.get("context_grew", False),
            "facts": n_facts,
            "superseded": n_superseded,
            "retired_turns": telemetry["retired_turn_count"],
            "tool_payloads": telemetry["tool_payloads_compacted"],
            "compile_ms": telemetry["compile_time_ms"],
            "model": transcript.meta.get("model"),
        })

        if keep_extractions and len(result.extractions) < max_extractions:
            for node in dag["active"]:
                result.extractions.append({
                    "transcript": transcript.id,
                    "entity": node["entity"],
                    "value": node["value"],
                    "source": node["source"],
                    "turn": node["turn_index"],
                })

    n = len(result.per_transcript)
    if n == 0:
        result.errors.append({"transcript": "*", "error": "no transcript compiled"})
        return result

    raw = max(1, totals["raw_tokens"])
    reduction = round((1 - totals["compiled_tokens"] / raw) * 100, 1)

    result.measurements = [
        Measurement(
            "transcripts_compiled", n, n, "",
            "corpus size actually measured",
            "not a claim about agent performance",
        ),
        Measurement(
            "transcripts_yielding_a_fact",
            totals["transcripts_with_facts"], n, "",
            "how often the state tracker found anything at all",
            "NOT precision: a fact can be present and wrong",
        ),
        Measurement(
            "facts_extracted", totals["facts"], n, "",
            "count of tracked entity values in the final state",
            "NOT ground truth; unlabelled",
        ),
        Measurement(
            "keys_reasserted", totals["supersessions"], n, "",
            "times a key was overwritten, i.e. the dead-branch case occurred",
            "a low count means the corpus cannot demonstrate the mechanism",
        ),
        Measurement(
            "token_reduction", reduction, n, "%",
            "compiled vs raw, same chars/4 estimator on both sides",
            "NOT a billing figure, NOT a latency proxy, NOT model quality",
        ),
        Measurement(
            "tool_payloads_compacted", totals["tool_payloads"], n, "",
            "tool outputs the sanitizer shrank",
            "compaction is lossy by design; safety rows are exempt",
        ),
        Measurement(
            "turns_retired", totals["retired_turns"], n, "",
            "turns removed from the prompt as superseded",
            "only meaningful where keys were reasserted",
        ),
        Measurement(
            "retirement_violations", totals["retirement_violations"], n, "",
            "retirements that would have orphaned a live fact",
            "must be 0; non-zero is a bug, not a metric",
        ),
        Measurement(
            "contexts_that_grew", totals["context_grew"], n, "",
            "compiles where the output was larger than the input",
            "the state register can cost more than it saves",
        ),
        Measurement(
            "compile_ms_p50", _pct(compile_ms, 50), n, "ms",
            "median wall-clock compile time, measured",
            "NOT time-to-first-token; no model is called",
        ),
        Measurement(
            "compile_ms_p95", _pct(compile_ms, 95), n, "ms",
            "95th percentile compile time, measured",
            "single-run figures on a shared machine are noisy",
        ),
        Measurement(
            "turns_p50", _pct(per_turn_tokens, 50), n, "turns",
            "median transcript length",
            "the corpus's shape, not a property of the library",
        ),
    ]
    return result


def _compile_one(
    transcript: Transcript,
    schema: Optional[Any],
    invariants: Optional[List[str]],
):
    """Compile one transcript, optionally under a caller-supplied entity schema."""
    from contextgc.client import compile_messages

    entities = None
    if schema is not None:
        entities = schema.get("entities", schema) if isinstance(schema, dict) else schema
        if isinstance(schema, dict) and schema.get("__immutable__"):
            entities = dict(entities)
            entities["__immutable__"] = tuple(schema["__immutable__"])

    return compile_messages(
        transcript.messages, invariants=invariants, schema=entities
    )


def _pct(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((percentile / 100) * (len(ordered) - 1))))
    return round(ordered[index], 2)
