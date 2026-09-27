"""
Turn the write-path capture into a regression check rather than a standing failure.

A committed capture is a measurement, and this one records a model that
under-performs on the protocol: 34% of its declared keys name a schema slot and 7
of its 38 blocks are not valid JSON. `benchmarks capture --verify` reports that by
exiting non-zero, which is right for a person about to trust a capture and wrong
for a nightly job. A check that fails every night on a known result is not a
check; it is a red light that teaches everyone to ignore red lights.

So this compares the capture against a committed baseline and fails only when a
number moves. Three failure modes, all of which are worth failing on:

* a number got worse -- a regression
* the capture is gone or unreadable -- the measurement was lost
* the baseline is missing -- nobody decided what "unchanged" means

Improving is reported, not failed. Updating the baseline is a deliberate act:

    python benchmarks/write_path_check.py captures/run1.json \\
        benchmarks/write_path_baseline.json --update

Run it with no arguments from the repository root to check the committed pair.
"""

import argparse
import json
import os
import sys

#: The numbers worth holding steady, and the direction that counts as worse.
#:
#: `in_schema_ratio` is the one that predicts whether the write path is worth
#: enabling. `compliance` is reported alongside it because the two came apart
#: sharply on this capture -- a prompt fix moved compliance 55% -> 90% while the
#: in-schema share did not move at all -- and a regression detector that watched
#: only compliance would have called that an improvement.
METRICS = {
    "compliance": "higher is better",
    "in_schema_ratio": "higher is better",
    "malformed": "lower is better",
    "declared_keys": "informational",
    "blocks": "informational",
}

#: How far a number may drift before it is called a change. Zero would make the
#: check fail on the last digit of a re-derived float, which is how a regression
#: detector becomes noise.
TOLERANCE = 0.02


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def measure(capture):
    """The comparable numbers for a capture, recomputed rather than read."""
    # Run as a script from the repository root, where `benchmarks` is not
    # necessarily importable: the package lives in the cwd, and a workflow that
    # fails on an ImportError reports a broken check rather than a broken model.
    if __package__ in (None, ""):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from benchmarks.capture import summarise
    from contextgc import load_schema

    schema = None
    if capture.get("schema"):
        try:
            schema = load_schema(capture["schema"])
        except (OSError, ValueError) as exc:
            raise SystemExit(
                f"capture names schema {capture['schema']!r}, which will not load: {exc}\n"
                f"  A capture whose schema cannot be resolved has no in-schema ratio,\n"
                f"  and the baseline it is checked against was built with one."
            )
    summary = summarise(capture.get("turns") or [], schema=schema)
    return {
        "turns": summary["turns"],
        "blocks": summary["blocks"],
        "malformed": summary["malformed"],
        "compliance": summary["compliance"],
        "declared_keys": summary["declared_keys"],
        "in_schema_keys": summary["in_schema_keys"],
        "in_schema_ratio": summary["in_schema_ratio"],
        "schema": capture.get("schema"),
        "model": capture.get("model"),
    }


def compare(measured, baseline):
    """(regressions, improvements) as lists of human-readable lines.

    Metrics marked ``informational`` are reported by ``main`` and judged by
    neither list. They are context, not quality: a capture that emitted twice as
    many blocks is not worse, and scoring it as though it were is how a
    regression detector starts crying wolf.
    """
    regressions, improvements = [], []
    for name, direction in METRICS.items():
        if direction == "informational":
            continue
        if name not in measured or name not in baseline:
            continue
        now, was = measured[name], baseline[name]
        if now is None or was is None:
            continue
        if abs(now - was) <= TOLERANCE:
            continue
        worse = now < was if direction == "higher is better" else now > was
        line = f"{name}: {was} -> {now} ({direction})"
        (regressions if worse else improvements).append(line)
    return regressions, improvements


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", nargs="?", default="captures/run1.json")
    parser.add_argument("baseline", nargs="?", default="benchmarks/write_path_baseline.json")
    parser.add_argument(
        "--update", action="store_true",
        help="write the current numbers to the baseline instead of comparing",
    )
    args = parser.parse_args(argv)

    if not os.path.exists(args.capture):
        print(
            f"no capture at {args.capture}\n"
            f"  the write-path measurement is missing, which is a failure, not a pass.\n"
            f"  Produce it with:  python -m benchmarks capture "
            f"--transcript benchmarks/corpus/sample.txt "
            f"--out {args.capture} --schema coding"
        )
        return 1

    measured = measure(load(args.capture))

    if args.update:
        with open(args.baseline, "w", encoding="utf-8") as handle:
            json.dump(measured, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"baseline updated -> {args.baseline}")
        for key in sorted(measured):
            print(f"  {key}: {measured[key]}")
        return 0

    if not os.path.exists(args.baseline):
        print(
            f"no baseline at {args.baseline}\n"
            f"  Without one, 'unchanged' has no definition and this check cannot\n"
            f"  distinguish a regression from the result it was written to record.\n"
            f"  Create it with:\n"
            f"    python benchmarks/write_path_check.py {args.capture} "
            f"{args.baseline} --update"
        )
        return 1

    regressions, improvements = compare(measured, load(args.baseline))

    print("write path -- capture vs baseline")
    for key in sorted(measured):
        print(f"  {key:<18} {measured[key]}")
    for line in improvements:
        print(f"\nIMPROVED  {line}")
        print("  Update the baseline deliberately if this is real:")
        print(f"    python benchmarks/write_path_check.py {args.capture} "
              f"{args.baseline} --update")
    if regressions:
        print("\nREGRESSED")
        for line in regressions:
            print(f"  {line}")
        return 1
    print("\nno change against the recorded baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
