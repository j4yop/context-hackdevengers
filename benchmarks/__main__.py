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
from .report import (
    render,
    render_extraction_sample,
    render_shadow,
    render_truncation_notice,
)
from .shadow import replay_source, run_corpus


def _load(args):
    if args.corpus == "synthetic":
        if not args.corpus_path:
            sys.exit("synthetic corpus needs --corpus-path")
        return load_synthetic(args.corpus_path)
    if args.corpus == "apigen":
        from .corpus import load_apigen_mt
        return load_apigen_mt(
            limit=args.limit, path=args.corpus_path,
            domain=getattr(args, "domain", None),
        )
    return load_swe_agent(
        limit=args.limit,
        min_turns=args.min_turns,
        path=args.corpus_path,
        per_repo=getattr(args, "per_repo", None),
    )


def _schema(path):
    """Resolve ``--schema`` to a pattern mapping.

    A bare name resolves against the schemas the library ships, so the harness
    measures the same patterns a user would get from ``load_schema`` rather than
    a private copy that can drift away from them.
    """
    if not path:
        return None
    if not path.endswith(".json") and not os.path.exists(path):
        from contextgc.schemas import load_schema
        return load_schema(path)
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
    result = run_harness(
        transcripts, schema=_schema(args.schema),
        max_extractions=getattr(args, "max_extractions", None) or 100_000,
    )
    from contextgc import load_schema

    from .gold import labels_path_for

    def _slot_names(name):
        """The slots a schema name defines, so unlabelled ones can be named."""
        if not name:
            return None
        try:
            loaded = load_schema(name)
        except Exception:
            return None
        return {slot: [] for slot in loaded}

    # The schema name is the better key: a label judges one schema's extractions,
    # and APIGen-MT is sliced two ways.
    precision = score_precision(
        result.extractions,
        labels_path=labels_path_for(
            (result.corpus or {}).get("corpus_source"), args.schema
        ),
        # So the report can name the slots nobody labelled. Without it a slot
        # with no labels is simply absent from the breakdown, and absent reads
        # as "not applicable" rather than "not done" -- which is how a figure
        # covering one slot of two came to read as a statement about a schema.
        schema=_slot_names(args.schema),
    )
    print(render(result))
    notice = render_truncation_notice(result)
    if notice:
        print()
        print(notice)
    print()
    print(render_precision(precision))
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
        payload = result.as_dict()
        # Precision belongs in the machine-readable output. It used to exist only
        # in the printed report, which meant the one number a reviewer would want
        # to check could not be checked by anything -- including CI, which is how
        # a label file was able to drift out of sync with the corpus unnoticed.
        payload["precision"] = precision
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        print(f"\nfull results -> {args.json}")
    return 0


def _load_capture_schema(payload):
    """
    The schema a capture was made under, so its summary can say whether the model
    declared anything the tracker had asked for.

    A capture made before the field existed has no ``schema`` key. Guessing one
    from the transcript path would be inventing provenance, and defaulting to
    the coding schema would report an in-schema ratio for a capture that never
    had one. Returns None, which leaves the ratio unreported rather than wrong.
    """
    name = payload.get("schema")
    if not name:
        return None
    try:
        from contextgc import load_schema

        return load_schema(name)
    except (OSError, ValueError):
        return None


def cmd_capture(args):
    """
    Record what a real model declares, so `shadow` has something honest to
    replay. Refuses rather than inventing: a synthetic declaration set would
    measure this harness, not the write path.
    """
    from .capture import capture, summarise, verify

    if args.verify:
        if not os.path.exists(args.out):
            sys.exit(
                f"no capture at {args.out}\n"
                "  one is produced by: python -m benchmarks capture "
                "--transcript <file> --out captures/run1.json\n"
                "  which needs a real model; see benchmarks/capture.py"
            )
        with open(args.out, encoding="utf-8") as handle:
            payload = json.load(handle)
        schema = _load_capture_schema(payload)
        problems = verify(payload, schema=schema)
        print(render_capture_summary(
            summarise(payload.get("turns", []), schema=schema), payload
        ))
        if problems:
            print()
            print("CAPTURE NOT USABLE:")
            for problem in problems:
                print(f"  - {problem}")
            sys.exit(1)
        print()
        print("capture is usable: `benchmarks shadow --captures` can replay it")
        return 0

    if not args.transcript and getattr(args, "corpus", None) in (None, "synthetic"):
        sys.exit("capture needs --transcript (a transcript file) or --verify")
    payload = capture(
        args.transcript, args.out, limit=args.limit, schema_path=args.schema,
        legacy_prompt=getattr(args, "legacy_prompt", False),
        corpus=getattr(args, "corpus", None) or "synthetic",
        domain=getattr(args, "domain", None),
        corpus_path=getattr(args, "corpus_path", None),
    )
    print(render_capture_summary(
        summarise(payload["turns"], schema=_load_capture_schema(payload)), payload
    ))
    print(f"\nwritten -> {args.out}")
    return 0


def render_capture_summary(summary, payload):
    lines = ["-" * 78, "CAPTURE"]
    lines.append(f"  endpoint             {payload.get('endpoint')}")
    lines.append(f"  model                {payload.get('model')}")
    lines.append(f"  schema               {payload.get('schema') or '(none recorded)'}")
    lines.append(f"  turns recorded       {summary['turns']}")
    lines.append(f"  state blocks         {summary['blocks']}")
    lines.append(f"  malformed blocks     {summary['malformed']}")
    lines.append(f"  turns that declared  {summary['declared_turns']}"
                 f"  ({summary['compliance']:.0%} of turns)")
    lines.append(f"  keys declared        {summary['declared_keys']}")
    # Compliance says the model spoke. This says it said something the tracker
    # asked for. They came apart sharply on the first real capture, and only
    # this one predicts whether the write path is worth enabling.
    if summary["in_schema_ratio"] is not None:
        lines.append(
            f"  naming a schema key  {summary['in_schema_keys']}"
            f"  ({summary['in_schema_ratio']:.0%} of declared keys)"
        )
    else:
        lines.append("  naming a schema key  (no schema recorded, ratio unknown)")
    if summary["keys"]:
        lines.append("  keys declared:")
        for key, count in list(summary["keys"].items())[:10]:
            lines.append(f"    {key:<28} {count}")
    lines.append("")
    if not summary["declared_turns"]:
        lines.append("  The model never declared anything, so this capture would measure")
        lines.append("  nothing. That is a result about the setup, not a pass.")
    return "\n".join(lines)


def cmd_shadow(args):
    if not args.captures:
        sys.exit(
            "shadow mode needs --captures: a JSON file of {transcript_id: {turn: block}}.\n"
            "Captures come from a real run with a real model; replaying them keeps the\n"
            "measurement reproducible without the model. Until such a capture exists,\n"
            "there is nothing to compare and this command says so rather than inventing it."
        )
    with open(args.captures, encoding="utf-8") as handle:
        payload = json.load(handle)
    # A capture file carries metadata and a verbatim turn list; shadow mode wants
    # the derived index. Accept either, so a hand-written index still works.
    captures = payload.get("declarations")
    if captures is None:
        captures = {
            k: v for k, v in payload.items()
            if isinstance(v, dict) and not k.startswith("_")
        }
    if not captures:
        sys.exit(
            f"{args.captures} holds no declarations.\n"
            "  A capture records the <contextgc-state> blocks a real model emitted;\n"
            "  it is produced by `benchmarks capture` and validated by\n"
            "  `benchmarks capture --verify`."
        )
    print(f"captured transcripts: {len(captures)}  "
          f"declared turns: {sum(len(v) for v in captures.values())}")

    transcripts = _load(args)
    summary = run_corpus(
        transcripts,
        source_for=lambda t: replay_source(captures.get(t.id, {})),
        schema=_schema(args.schema),
        limit=args.limit,
        captures=captures,
    )
    print(render_shadow(summary))
    return 0


def cmd_sample(args):
    transcripts = _load(args)
    result = run_harness(transcripts, keep_extractions=True)
    print(render_extraction_sample(result.extractions, limit=args.limit))
    return 0


def build_parser():
    """
    The argument parser, on its own.

    Split out of `main` so the corpus-loader defaults have one home.
    `benchmarks.label_worksheet` has to load exactly what this loads --
    a worksheet built over different transcripts produces labels that do
    not match the report's extractions, and nothing in the output says so.
    It was not: `per_repo` defaulted to `None` in the worksheet and `2`
    here, and 99 of 142 hand labels stopped matching. Reading the defaults
    off this parser is what stops that recurring; restating them is what
    caused it.
    """
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks",
        description="Measure contextgc against real agent transcripts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, with_limit=True):
        p.add_argument(
            "--corpus",
            choices=("swe-agent", "apigen", "synthetic"),
            default="swe-agent",
            help="swe-agent: coding trajectories. apigen: customer-service "
                 "tool use, a second domain. synthetic: a vendored text file.",
        )
        p.add_argument("--corpus-path", help="local parquet shard or synthetic transcript file")
        p.add_argument("--min-turns", type=int, default=8)
        p.add_argument(
            "--domain",
            help="for --corpus apigen: keep one policy domain, e.g. retail or "
                 "airline. The file interleaves both.",
        )
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
    run_parser.add_argument("--schema", help="schema name (e.g. coding) or path to a JSON file")
    run_parser.add_argument("--show-extractions", type=int, default=0, metavar="N")
    run_parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if a retirement orphaned a live fact, or a "
             "compiled context grew. Without this the run always exits 0, so "
             "it cannot fail a build no matter what regresses.",
    )
    run_parser.add_argument("--json", help="write full results here")
    run_parser.add_argument(
        "--max-extractions", type=int, default=None,
        help="cap on retained extractions. A memory guard for a large corpus, "
             "and it moves precision: fewer retained extractions means fewer "
             "labels can match, so the report says so when the cap bit",
    )
    run_parser.set_defaults(func=cmd_run)

    capture_parser = sub.add_parser(
        "capture",
        help="record what a real model declares, for shadow mode to replay",
    )
    capture_parser.add_argument("--transcript", help="transcript file to run")
    capture_parser.add_argument(
        "--corpus", default="synthetic",
        choices=["synthetic", "apigen", "swe-agent"],
        help="where the conversations come from; recorded in the capture so a "
             "report can say where the numbers came from",
    )
    capture_parser.add_argument(
        "--corpus-path", help="local APIGen JSON or SWE-agent parquet shard"
    )
    capture_parser.add_argument(
        "--domain", help="for --corpus apigen: airline or retail"
    )
    capture_parser.add_argument("--out", default="captures/run1.json")
    capture_parser.add_argument("--verify", action="store_true",
                                help="check an existing capture instead of making one")
    capture_parser.add_argument("--limit", type=int, default=20)
    capture_parser.add_argument("--schema", help="schema name, passed to the agent")
    capture_parser.add_argument(
        "--legacy-prompt", action="store_true",
        help="reproduce the duplicated-protocol prompt that the first capture used, "
             "so the before/after is reproducible. The result is stamped "
             "legacy_prompt and `capture --verify` refuses it: a valid record of a "
             "broken harness, not a measurement of the protocol.",
    )
    capture_parser.set_defaults(func=cmd_capture)

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

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
