"""
Hand-labelled precision.

Coverage is free; precision is not. This module holds a small set of extractions
that a human has read in context and judged, and computes precision over exactly
those -- never over anything else.

The label file is committed so the measurement is reproducible and auditable. If
you want a different answer, change the labels, not the arithmetic.

Each label records why it was judged correct or incorrect, so a future reader can
disagree with the judgement rather than having to reverse-engineer it.
"""

import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

LABELS_DIR = os.path.join(os.path.dirname(__file__), "labels")

#: Label file per corpus. ``precision.json`` predates the second domain and keeps
#: its name so the coding numbers stay where they were.
LABELS_BY_CORPUS = {
    "swe-agent-trajectories": os.path.join(LABELS_DIR, "precision.json"),
    "apigen-mt-5k": os.path.join(LABELS_DIR, "travel.json"),
}

LABELS_PATH = LABELS_BY_CORPUS["swe-agent-trajectories"]


def labels_path_for(source: Optional[str] = None) -> str:
    """
    The label file for a corpus.

    Scoring travel labels against coding extractions would report every label as
    drifted, which is noise rather than information.
    """
    if source is None:
        return LABELS_PATH
    return LABELS_BY_CORPUS.get(source, LABELS_PATH)

#: Verdict values.
CORRECT = "correct"
INCORRECT = "incorrect"
UNCLEAR = "unclear"


def load_labels(path: Optional[str] = None) -> List[Dict[str, Any]]:
    target = path or LABELS_PATH
    if not os.path.exists(target):
        return []
    with open(target, encoding="utf-8") as handle:
        return json.load(handle)


def save_labels(labels: List[Dict[str, Any]], path: Optional[str] = None) -> None:
    target = path or LABELS_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(labels, handle, indent=2)
        handle.write("\n")


def wilson_interval(correct: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """
    Wilson score interval for a binomial proportion.

    A point estimate with no interval invites a reader to treat 88% from 16
    correlated rows as 88% +/- nothing. This is the honest width on that claim.
    """
    if total <= 0:
        return (0.0, 1.0)
    phat = correct / total
    denom = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return (max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom))


def clusters_of(matched: List[Dict[str, Any]]) -> Dict[Tuple, str]:
    """
    Collapse matched labels to independent units.

    SWE-agent trajectories for one issue share near-identical opening turns, so
    two extractions from the same repository and turn are not two pieces of
    evidence. Keying on (repository, turn, entity) treats them as one, which is
    what stops ``n`` from being inflated by near-duplicates.
    """
    out: Dict[Tuple, str] = {}
    for item in matched:
        key = (
            str(item["transcript"]).split("#")[0],
            item.get("turn"),
            item["entity"],
        )
        # A cluster is correct only if every judgement in it was correct; one
        # confirmed error makes the cluster a failure, and a single "unclear"
        # keeps it out of the denominator entirely.
        verdicts = out.setdefault(key, [])
        verdicts.append(item["verdict"])
    return out


def label_key(transcript_id: str, entity: str, turn_index: Any = None) -> Tuple:
    """
    The identity of a labelled extraction.

    Includes the turn index: one trajectory can yield several extractions for the
    same key at different points, and a label must pin the one it was read
    against.
    """
    return (transcript_id, entity, turn_index)


def score(
    extractions: List[Dict[str, Any]],
    labels: Optional[List[Dict[str, Any]]] = None,
    labels_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Precision over labelled items only.

    Returns a result whose ``n`` is the number of labels that matched an actual
    extraction. Unmatched labels are reported separately, because a label file
    that has drifted out of sync with the corpus is a measurement that has quietly
    stopped measuring anything.
    """
    if labels is None:
        labels = load_labels(labels_path)
    else:
        labels = labels
    by_key: Dict[Tuple, List[Dict[str, Any]]] = {}
    for label in labels:
        by_key.setdefault(
            label_key(label["transcript"], label["entity"], label.get("turn_index")), []
        ).append(label)

    correct = incorrect = unclear = 0
    matched = 0
    matched_values: List[Dict[str, Any]] = []

    used = set()
    for extraction in extractions:
        candidates = by_key.get(
            label_key(extraction["transcript"], extraction["entity"], extraction.get("turn"))
        )
        if not candidates:
            continue
        # Prefer an unused label for the same slot, so two facts from one turn
        # cannot both claim the same judgement.
        label = next(
            (c for c in candidates if id(c) not in used),
            candidates[0],
        )
        used.add(id(label))
        matched += 1
        matched_values.append({
            "transcript": extraction["transcript"],
            "entity": extraction["entity"],
            "turn": extraction.get("turn"),
            "extracted": extraction["value"],
            "label_said": label.get("value"),
            "verdict": label["verdict"],
            "value_agrees": str(label.get("value", extraction["value"]))
            == str(extraction["value"]),
        })
        if label["verdict"] == CORRECT:
            correct += 1
        elif label["verdict"] == INCORRECT:
            incorrect += 1
        else:
            unclear += 1

    judged = correct + incorrect
    precision = (correct / judged) if judged else None

    # Cluster-aware view. `n_raw` counts rows; `n_clusters` counts independent
    # units. When they diverge the raw figure is the one to distrust.
    cluster_verdicts: Dict[Tuple, List[str]] = {}
    for item in matched_values:
        key = (
            str(item["transcript"]).split("#")[0],
            item.get("turn"),
            item["entity"],
        )
        cluster_verdicts.setdefault(key, []).append(item["verdict"])

    clusters_correct = clusters_incorrect = clusters_unclear = 0
    for verdicts in cluster_verdicts.values():
        if any(v == INCORRECT for v in verdicts):
            clusters_incorrect += 1
        elif any(v == UNCLEAR for v in verdicts):
            clusters_unclear += 1
        else:
            clusters_correct += 1

    clusters_judged = clusters_correct + clusters_incorrect
    cluster_precision = (
        clusters_correct / clusters_judged if clusters_judged else None
    )
    lo, hi = wilson_interval(clusters_correct, clusters_judged)

    return {
        "n_labelled": matched,
        "n_unmatched_labels": len(labels) - matched,
        "correct": correct,
        "incorrect": incorrect,
        "unclear": unclear,
        "precision": round(precision, 3) if precision is not None else None,
        "n": judged,
        "n_clusters": clusters_judged,
        "n_clusters_unclear": clusters_unclear,
        "cluster_precision": (
            round(cluster_precision, 3) if cluster_precision is not None else None
        ),
        "ci95": [round(lo, 3), round(hi, 3)],
        "n_repos": len({str(m["transcript"]).split("#")[0] for m in matched_values}),
        "matched": matched_values,
    }


def render(result: Dict[str, Any]) -> str:
    """Render precision, or say plainly that it was not measured."""
    lines = ["-" * 78, "PRECISION (hand-labelled sample)"]
    if result["precision"] is None:
        lines.append("  Not measured. No usable labelled sample was supplied.")
        if result.get("n_unmatched_labels"):
            lines.append(f"  ({result['n_unmatched_labels']} label(s) did not match any extraction,")
            lines.append("   so the label file has drifted out of sync with the corpus.)")
        lines.append("")
        lines.append("  Coverage is not precision. A tracker that matches prose in every")
        lines.append("  transcript scores 100% coverage and 0% precision, which is exactly")
        lines.append("  what the previous default schema did on real data.")
        return "\n".join(lines)

    supplied = result["n_labelled"] + result.get("n_unmatched_labels", 0)
    lines.append(f"  labels supplied        {supplied}")
    lines.append(f"  matched an extraction  {result['n_labelled']}")
    if result["unclear"]:
        lines.append(f"  unclear                {result['unclear']}  (excluded from the ratio)")
    lines.append(f"  JUDGED                 {result['n']}   <- the denominator")
    lines.append(f"    correct              {result['correct']}")
    lines.append(f"    incorrect            {result['incorrect']}")
    lines.append(f"  PRECISION (rows)       {result['precision'] * 100:.0f}%   (n={result['n']})")

    # The row count overstates the evidence whenever trajectories for one issue
    # share opening turns. Show the clustered figure and the interval beside it.
    if result.get("n_clusters") is not None and result["n_clusters"] != result["n"]:
        lines.append(f"  n is inflated          {result['n']} rows collapse to "
                     f"{result['n_clusters']} independent units")
        lines.append("                        (same repo + turn + slot counted once)")
    if result.get("cluster_precision") is not None:
        lo, hi = result["ci95"]
        lines.append(f"  PRECISION (clusters)   {result['cluster_precision'] * 100:.0f}%   "
                     f"(n={result['n_clusters']}, 95% CI {lo * 100:.0f}-{hi * 100:.0f}%)")
    if result.get("n_repos") is not None:
        lines.append(f"  repositories covered  {result['n_repos']}")
    if result.get("n_clusters_unclear"):
        lines.append(f"  unclear clusters      {result['n_clusters_unclear']}  "
                     "(excluded from the ratio)")

    if result["n"] < 20:
        lines.append("")
        lines.append(f"  ! n={result['n']} is a small sample. Treat this as a smell test, not a")
        lines.append("    statistic. It is here to catch gross regression, not to be quoted.")
    if result.get("ci95") and (result["ci95"][1] - result["ci95"][0]) > 0.3:
        lines.append(f"  ! the 95% interval spans {(result['ci95'][1] - result['ci95'][0]) * 100:.0f}"
                     " points. The point estimate is not a measurement of anything")
        lines.append("    precise; the interval is the finding.")
    lines.append("")
    lines.append("  means: of the extractions a human read in context and judged, this")
    lines.append("         fraction named a value that was really there.")
    lines.append("  NOT:   a claim about unlabelled extractions, and not a claim about any")
    lines.append("         transcript outside this sample.")

    if result["n_unmatched_labels"]:
        lines.append("")
        lines.append(f"  ! {result['n_unmatched_labels']} label(s) did not match any extraction.")
        lines.append("    The label file has drifted from the corpus; the figure above covers")
        lines.append("    only what still lines up.")

    drifted = [m for m in result["matched"] if not m["value_agrees"]]
    if drifted:
        lines.append("")
        lines.append("  ! value drift between label and current extraction:")
        for item in drifted[:5]:
            lines.append(f"    {item['transcript'][:26]:<28} {item['entity']}")
            lines.append(f"        labelled: {str(item['label_said'])[:50]}")
            lines.append(f"        now     : {str(item['extracted'])[:50]}")
    return "\n".join(lines)
