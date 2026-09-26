"""
Command-line entry point for the benchmark harness.

    python -m benchmarks run     --limit 200
    python -m benchmarks shadow  --captures captures/run1.json --limit 50
    python -m benchmarks sample  --limit 25
    python -m benchmarks fetch
"""

import argparse
import json
import os
import sys

from .corpus import SWE_AGENT_HF_URL, cached_shard, load_swe_agent, load_synthetic
from .gold import render as render_precision
from .gold import score as score_precision
from .harness import run as run_harness
from .report import render, render_extraction_sample, render_shadow
from .shadow import replay_source, run_corpus


def _load(args):
    if args.corpus == "synthetic":
        if not args.corpus_path:
            sys.exit("synthetic corpus needs --corpus-path")
        return load_synthetic(args.corpus_path)
    return load_swe_agent(
        limit=args.limit,
        min_turns=args.min_turns,
        path=args.corpus_path,
        per_repo=getattr(args, "per_repo", None),
    )


def _schema(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if "entities" in raw:
        return raw["entities"]
    return raw


def cmd_fetch(args):
    import urllib.request

    target = args.out or cached_shard()
    if os.path.exists(target) and not args.force:
        print(f"already present: {target}")
        return 0
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    print(f"downloading {SWE_AGENT_HF_URL}\n         -> {target}")
    urllib.request.urlretrieve(SWE_AGENT_HF_URL, target)
    size = os.path.getsize(target)
    print(f"done: {size / 1e6:.1f} MB")
    return 0


def _invariants(result):
    """
    Measurements that are bugs when non-zero, as opposed to metrics.

    A retirement violation orphans a live fact, and a context that grew means the
    state register cost more than the transcript it replaced. Neither is a
    trade-off to be reported; both are defects. These are the only numbers in
    the harness that are allowed to fail a build.
    """
    by_name = {m.name: m.value for m in result.measurements}
    return [
        ("retirement_violations", by_name.get("retirement_violations")),
        ("contexts_that_grew", by_name.get("contexts_that_grew")),
    ]


def cmd_run(args):
    transcripts = _load(args)
    if not transcripts:
        sys.exit("no transcripts matched the filters")
    result = run_harness(transcripts, schema=_schema(args.schema))
    print(render(result))
    print()
    print(render_precision(score_precision(result.extractions)))
    print()
    if args.show_extractions:
        print()
        print(render_extraction_sample(result.extractions, limit=args.show_extractions))
    if getattr(args, "check", False):
        broken = [(n, v) for n, v in _invariants(result) if v]
        if broken:
            print()
            print("INVARIANT VIOLATIONS (these are bugs, not metrics):")
            for name, value in broken:
                print(f"  {name} = {value}")
            sys.exit(1)
        print()
        print("invariants: retirement_violations=0, contexts_that_grew=0")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result.as_dict(), handle, indent=2)
        print(f"\nfull results -> {args.json}")
    return 0


def cmd_shadow(args):
    if not args.captures:
        sys.exit(
            "shadow mode needs --captures: a JSON file of {transcript_id: {turn: block}}.\n"
            "Captures come from a real run with a real model; replaying them keeps the\n"
            "measurement reproducible without the model. Until such a capture exists,\n"
            "there is nothing to compare and this command says so rather than inventing it."
        )
    with open(args.captures, encoding="utf-8") as handle:
        captures = json.load(handle)

    transcripts = _load(args)
    summary = run_corpus(
        transcripts,
        source_for=lambda t: replay_source(captures.get(t.id, {})),
        schema=_schema(args.schema),
        limit=args.limit,
    )
    print(render_shadow(summary))
    return 0


def cmd_sample(args):
    transcripts = _load(args)
    result = run_harness(transcripts, keep_extractions=True)
    print(render_extraction_sample(result.extractions, limit=args.limit))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks",
        description="Measure contextgc against real agent transcripts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, with_limit=True):
        p.add_argument("--corpus", choices=("swe-agent", "synthetic"), default="swe-agent")
        p.add_argument("--corpus-path", help="local parquet shard or synthetic transcript file")
        p.add_argument("--min-turns", type=int, default=8)
        p.add_argument(
            "--per-repo",
            type=int,
            default=2,
            metavar="N",
            help="max trajectories per repository (default 2). The shard is "
                 "repo-ordered, so without this the first N transcripts come "
                 "from a couple of repos and the measurement inherits that.",
        )
        if with_limit:
            p.add_argument("--limit", type=int, default=100)

    run_parser = sub.add_parser("run", help="measure the compiler over a corpus")
    common(run_parser)
    run_parser.add_argument("--schema", help="JSON file of entity patterns to use")
    run_parser.add_argument("--show-extractions", type=int, default=0, metavar="N")
    run_parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if a retirement orphaned a live fact, or a "
             "compiled context grew. Without this the run always exits 0, so "
             "it cannot fail a build no matter what regresses.",
    )
    run_parser.add_argument("--json", help="write full results here")
    run_parser.set_defaults(func=cmd_run)

    shadow_parser = sub.add_parser("shadow", help="compare read path against declarations")
    common(shadow_parser)
    shadow_parser.add_argument("--captures", help="JSON of replayed declarations")
    shadow_parser.add_argument("--schema", help="JSON file of entity patterns; required for a meaningful diff")
    shadow_parser.set_defaults(func=cmd_shadow)

    sample_parser = sub.add_parser("sample", help="dump extractions for human labelling")
    common(sample_parser)
    sample_parser.set_defaults(func=cmd_sample)

    fetch_parser = sub.add_parser("fetch", help="download the trajectory shard")
    fetch_parser.add_argument("--out")
    fetch_parser.add_argument("--force", action="store_true")
    fetch_parser.set_defaults(func=cmd_fetch)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
