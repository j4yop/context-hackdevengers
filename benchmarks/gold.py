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
import os
from typing import Any, Dict, List, Optional, Tuple

LABELS_PATH = os.path.join(os.path.dirname(__file__), "labels", "precision.json")

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
) -> Dict[str, Any]:
    """
    Precision over labelled items only.

    Returns a result whose ``n`` is the number of labels that matched an actual
    extraction. Unmatched labels are reported separately, because a label file
    that has drifted out of sync with the corpus is a measurement that has quietly
    stopped measuring anything.
    """
    labels = load_labels() if labels is None else labels
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

    return {
        "n_labelled": matched,
        "n_unmatched_labels": len(labels) - matched,
        "correct": correct,
        "incorrect": incorrect,
        "unclear": unclear,
        "precision": round(precision, 3) if precision is not None else None,
        "n": judged,
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
    lines.append(f"  PRECISION              {result['precision'] * 100:.0f}%   (n={result['n']})")
    if result["n"] < 20:
        lines.append("")
        lines.append(f"  ! n={result['n']} is a small sample. Treat this as a smell test, not a")
        lines.append("    statistic. It is here to catch gross regression, not to be quoted.")
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
