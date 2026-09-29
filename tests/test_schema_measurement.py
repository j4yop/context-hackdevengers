"""
A schema's recorded precision must equal the precision it actually has.

Found during a trial: the console's schema panel told a user the `travel` schema
was measured at **100% (n=72)**. The README, three hundred lines earlier, said
**99% (n=149)** for the same schema. Both were in the same repository and they
contradicted each other, and the one a trial user reads first -- the number next
to the schema name in the UI -- was the stale one.

So the number that decides whether somebody trusts the tool was wrong in the
direction that flatters it, and had been wrong long enough that fixing the
400-extraction cap elsewhere in the project moved the real figure without
touching the string that displays it.

The string is the part that goes stale. The measurement is cheap to recompute and
never recomputed on its own, so a number in a JSON field drifted from the labels
next to it in the same repository.

These tests recompute and compare. They are corpus-dependent and skip without
the cached corpora, because a check that cannot run is not a check.
"""

import json
from pathlib import Path

import pytest

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "contextgc" / "schemas"
LABELS = Path(__file__).resolve().parent.parent / "benchmarks" / "labels"

#: schema name -> label file. Coding's is `precision.json` because it was the
#: first; the others took their schema's name.
LABEL_FILES = {
    "coding": "precision.json",
    "travel": "travel.json",
    "logistics": "logistics.json",
}


def _corpus(name: str):
    """
    The corpus the CLI loads, with its defaults.

    `per_repo=2` is the whole point and it is easy to lose. Uncapped, the same
    shard packs 200 trajectories out of 13 repositories and the label set
    matches 23 independent units; capped, it spreads over 20 and matches 36. So
    a checker that loads "the same corpus" without it silently measures a
    different, narrower sample and would then have reported the *schema* as
    stale when the schema was right. It was caught here by the checker being
    wrong first, which is the only reason it is worth mentioning.
    """
    from benchmarks.corpus import load_apigen_mt, load_swe_agent

    if name == "coding":
        return load_swe_agent(limit=200, min_turns=8, per_repo=2)
    domain = "airline" if name == "travel" else "retail"
    return load_apigen_mt(limit=200, domain=domain)


@pytest.mark.parametrize("name", sorted(LABEL_FILES))
def test_a_schema_does_not_display_a_stale_precision(name):
    """
    Recompute the figure and compare it to the string the console renders. A
    schema whose displayed number disagrees with its own labels is worse than
    one that displays nothing, because the reader has no way to tell.
    """
    from benchmarks.gold import score
    from benchmarks.harness import run
    from contextgc import load_schema

    label_file = LABELS / LABEL_FILES[name]
    if not label_file.exists():
        pytest.skip(f"no labels for {name}")
    try:
        result = run(_corpus(name), schema=load_schema(name))
    except BaseException as err:  # pragma: no cover - corpus unavailable
        # BaseException, not Exception: the corpus loader signals a missing
        # pandas/pyarrow with `sys.exit`, which is a BaseException, so an
        # `except Exception` here let it escape and the three CI jobs without a
        # cached shard all failed on a check that is supposed to skip when it
        # cannot run. A check that cannot run must not be a failure.
        if isinstance(err, (KeyboardInterrupt, SystemExit)) and "corpus" not in str(err):
            raise
        pytest.skip(f"{name} corpus not usable here: {err}")
    if not result.extractions:
        pytest.skip(f"{name} corpus produced no extractions")

    scored = score(result.extractions, labels_path=str(label_file))
    if scored["cluster_precision"] is None:
        pytest.skip(f"{name}: no labels matched an extraction")

    computed = f"{scored['cluster_precision'] * 100:.0f}% (n={scored['n_clusters']}"
    stored = json.loads((SCHEMA_DIR / f"{name}.json").read_text())["_measurement"]["precision"]
    assert stored.startswith(computed), (
        f"{name} schema displays {stored!r} but its own labels compute to "
        f"{computed}... -- the console shows this string, so a stale one tells a "
        f"trial user the tool is better than it is"
    )


def test_a_schema_never_overstates_its_own_precision():
    """
    A weaker check that needs no corpus: a schema may not claim 100% while any
    of its own label rows is marked incorrect. This is the direction that
    matters, and it is the direction the travel figure was stale in.
    """
    for name, filename in LABEL_FILES.items():
        path = LABELS / filename
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        rows = data["items"] if isinstance(data, dict) and "items" in data else data
        incorrect = [r for r in rows if r.get("verdict") == "incorrect"]
        stored = json.loads((SCHEMA_DIR / f"{name}.json").read_text())
        displayed = stored.get("_measurement", {}).get("precision", "")
        if incorrect and displayed.startswith("100%"):
            pytest.fail(
                f"{name} displays {displayed!r} while {len(incorrect)} of its "
                f"label rows are marked incorrect"
            )


def test_the_readme_and_the_schemas_agree_about_precision():
    """
    They disagreed once, and nothing caught it, because each was checked against
    itself. A string in one file and a string in another are only consistent if
    something compares them.
    """
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text()
    for name in LABEL_FILES:
        stored = json.loads(
            (SCHEMA_DIR / f"{name}.json").read_text()
        )["_measurement"]["precision"]
        # The README writes the CI with an en dash and a comma; normalise.
        needle = stored.replace(",", ",").replace(" (", " (")
        n = needle.split("n=")[1].split(",")[0].split(")")[0]
        pct = needle.split(" (")[0]
        assert f"n={n}" in readme, (
            f"{name}: schema says {stored!r} but the README never quotes n={n}"
        )
        assert pct in readme, (
            f"{name}: schema says {pct} but the README never quotes {pct}"
        )
