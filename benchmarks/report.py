"""
Rendering, with the honesty constraints enforced in code rather than by intent.

The rules this module exists to make hard to violate:

1. Every percentage is printed next to the ``N`` it came from.
2. Every measurement prints what it does **not** mean.
3. A corpus summary is printed above the numbers, including its source.
4. A precision number is never printed unless it was measured against a labelled
   sample, and the sample size goes with it.
5. If the corpus is synthetic, the output says so in the first line.

A benchmark whose own report is careful is rarer than it should be.
"""

from typing import Any, Dict, List, Optional

#: Shown for any measurement whose N is small enough that a percentage would
#: imply more than the data supports.
SMALL_N = 20

#: Shown when a measurement could not be taken.
UNMEASURED = "not measured"


def render(result: Any, width: int = 78) -> str:
    """Render a :class:`benchmarks.harness.HarnessResult`."""
    lines: List[str] = []
    corpus = result.corpus

    if corpus.get("count") == 0:
        return "No transcripts were compiled. Nothing to report."

    synthetic = corpus.get("source") == "synthetic"
    lines.append("!" * width if synthetic else "=" * width)
    if synthetic:
        lines.append("SYNTHETIC CORPUS -- written alongside the patterns.")
        lines.append("These are not independent evidence of anything. Use them")
        lines.append("for regression only.")
    else:
        lines.append(f"CORPUS  {corpus.get('source')}")
    lines.append("=" * width)
    lines.append(f"  transcripts      {corpus.get('count')}")
    lines.append(f"  turns            total {corpus.get('turns_total')}, "
                 f"median {corpus.get('turns_median')}, "
                 f"range {corpus.get('turns_min')}-{corpus.get('turns_max')}")
    lines.append(f"  characters       {corpus.get('chars_total'):,}")
    if corpus.get("models"):
        models = ", ".join(f"{k} x{v}" for k, v in sorted(corpus["models"].items()))
        lines.append(f"  models           {models}")
    if corpus.get("note"):
        lines.append(f"  !! {corpus['note']}")
    lines.append("")

    if result.errors:
        lines.append(f"  !! {len(result.errors)} transcript(s) failed to compile:")
        for error in result.errors[:5]:
            lines.append(f"     {error.get('transcript')}: {error.get('error')}")
        if len(result.errors) > 5:
            lines.append(f"     ... and {len(result.errors) - 5} more")
        lines.append("")

    lines.append("MEASUREMENTS" + " " * (width - 12) + "value          n")
    lines.append("-" * width)
    for measurement in result.measurements:
        lines.extend(_render_measurement(measurement, width))
    lines.append("")

    lines.extend(_render_findings(result, width))
    return "\n".join(lines)


def render_run(result: Any, precision: Optional[Dict[str, Any]] = None, width: int = 78) -> str:
    """The standard report: corpus, measurements, findings, then precision."""
    from .gold import render as render_gold

    parts = [render(result, width)]
    parts.append(render_gold(precision or {}))
    return "\n\n".join(parts)


def _render_measurement(measurement: Any, width: int) -> List[str]:
    value = measurement.value
    if isinstance(value, float):
        rendered = f"{value:g}{measurement.unit}"
    elif isinstance(value, int):
        rendered = f"{value:,}{measurement.unit}"
    else:
        rendered = str(value)

    flag = ""
    if measurement.n < SMALL_N and isinstance(value, (int, float)) and value:
        flag = f"  (n<{SMALL_N}: too small to generalise)"

    lines = [f"  {measurement.name:<28} {rendered:>12}  {measurement.n:>6}{flag}"]
    if measurement.means:
        lines.append(f"      means: {measurement.means}")
    if measurement.does_not_mean:
        lines.append(f"      NOT:   {measurement.does_not_mean}")
    return lines


def _render_findings(result: Any, width: int) -> List[str]:
    """
    Draw the conclusions the numbers actually support, and refuse the rest.

    This is where a benchmark usually starts arguing for itself. These lines are
    derived mechanically from the measurements, so they cannot drift from them.
    """
    lines = ["WHAT THIS RUN SUPPORTS", "-" * width]
    by_name = {m.name: m for m in result.measurements}

    facts = by_name.get("facts_extracted")
    yielding = by_name.get("transcripts_yielding_a_fact")
    reasserted = by_name.get("keys_reasserted")
    grew = by_name.get("contexts_that_grew")
    violations = by_name.get("retirement_violations")
    reduction = by_name.get("token_reduction")

    if facts and yielding:
        lines.append(
            f"  The state tracker produced {facts.value} fact(s) across "
            f"{yielding.value} of {yielding.n} transcript(s)."
        )
        lines.append("  That is COVERAGE. It says nothing about whether any of them")
        lines.append("  is correct -- see the precision note below, which is absent")
        lines.append("  unless a labelled sample was supplied.")

    if reasserted:
        if reasserted.value == 0:
            lines.append("")
            lines.append("  No key was ever re-asserted in this corpus. The dead-branch")
            lines.append("  mechanism this library exists for was never exercised, so this")
            lines.append("  run cannot speak to it at all.")
        else:
            lines.append("")
            lines.append(f"  {reasserted.value} key re-assertion(s) occurred, so the superseded-branch")
            lines.append("  case is present in the data and the retirement logic ran.")

    if reduction and reduction.value:
        lines.append("")
        lines.append(f"  Token reduction measured {reduction.value}% on this corpus with the")
        lines.append("  library's own chars/4 estimator on both sides. It is a ratio, not a")
        lines.append("  cost saving and not a latency claim.")

    if grew and grew.value:
        lines.append("")
        lines.append(f"  {grew.value} of {grew.n} compile(s) produced MORE tokens than they consumed.")
        lines.append("  The injected state register costs more than it saves on a short")
        lines.append("  transcript. This is a real cost, not a rounding artefact.")

    if violations and violations.value:
        lines.append("")
        lines.append(f"  !! {violations.value} retirement violation(s). This is a BUG, not a metric:")
        lines.append("     a fact was left in the register with its supporting turn removed.")

    return lines


def render_extraction_sample(extractions: List[Dict[str, Any]], limit: int = 25) -> str:
    """
    Show extracted (entity, value) pairs for human labelling.

    This is the raw material for precision. A reader can look at twenty of these
    and see immediately whether the tracker is finding facts or matching prose.
    """
    if not extractions:
        return "No extractions to sample."
    lines = [
        "EXTRACTED FACTS -- label these if you want a precision number",
        "-" * 78,
    ]
    for item in extractions[:limit]:
        value = item["value"]
        if len(value) > 52:
            value = value[:52] + "..."
        lines.append(f"  {item['entity']:<24} = {value!r}")
    if len(extractions) > limit:
        lines.append(f"  ... {len(extractions) - limit} more")
    lines.append("")
    lines.append("  Nothing above is checked against ground truth. If these values are")
    lines.append("  wrong, the tracker is matching prose -- which is a precision")
    lines.append("  failure, and no amount of coverage makes up for it.")
    return "\n".join(lines)


def render_shadow(summary: Dict[str, Any], width: int = 78) -> str:
    """Render an aggregate shadow-mode comparison."""
    lines = ["=" * width, "SHADOW MODE -- read path vs declared state", "=" * width]
    lines.append(f"  transcripts compared        {summary['n']}")
    lines.append(f"  errors                      {summary['errors']}")
    lines.append("")
    lines.append(f"  transcripts where the declaration ADDED a key      "
                 f"{summary['transcripts_with_added_facts']}")
    lines.append(f"  transcripts where it CHANGED an existing key       "
                 f"{summary['transcripts_with_changed_facts']}")
    lines.append(f"  transcripts with any effect at all                 "
                 f"{summary['transcripts_with_any_effect']}")
    lines.append("")
    lines.append(f"  keys added      {summary['total_added']}")
    lines.append(f"  keys changed    {summary['total_changed']}")
    lines.append(f"  keys agreed     {summary['total_agreed']}")
    lines.append("")

    changed_rows = [r for r in summary["rows"] if r.get("changed")]
    if changed_rows:
        lines.append("  DISAGREEMENTS -- each needs a human to say which is right:")
        for row in changed_rows[:10]:
            for key, pair in list(row["changed"].items())[:3]:
                lines.append(f"    {row['id'][:28]:<30} {key}")
                lines.append(f"        read path: {str(pair['read_path'])[:56]}")
                lines.append(f"        declared : {str(pair['declared'])[:56]}")
        if len(changed_rows) > 10:
            lines.append(f"    ... and {len(changed_rows) - 10} more transcripts")
        lines.append("")
        lines.append("  A disagreement is not automatically an error in either direction.")
        lines.append("  It is the signal that a declaration and the text tell different")
        lines.append("  stories, which is exactly what needs adjudicating.")

    lines.append("")
    lines.append("  Shadow mode never emits a declared context. The context it returns")
    lines.append("  is always the read-path compile.")
    return "\n".join(lines)
