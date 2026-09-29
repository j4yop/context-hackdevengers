"""
Corpus-loader defaults, owned by the thing that owns the CLI.

A worksheet and a report must load the same transcripts or a person's labels do
not match the extractions being scored, and nothing says so. That happened:
`label_worksheet` called `load_swe_agent(limit=...)` and let `per_repo` default
to `None`, which packs a window out of 13 repositories, while the CLI defaults
to `2` and spreads over 20. 99 of 142 hand labels stopped matching and the
report called the second slot UNMEASURED.

The fix is not to remember the number in two places. It is to have one place, so
this module reads the parser the CLI actually uses and the worksheet follows it.
Change the CLI default and both move together, which is the only arrangement in
which they cannot disagree again.
"""

from __future__ import annotations

from typing import Any, Dict


def _cli_defaults() -> Dict[str, Any]:
    import importlib

    module = importlib.import_module("benchmarks.__main__")
    parser = getattr(module, "build_parser", None)
    if callable(parser):
        # A subcommand is required, and `parse_args` only parses -- it never
        # calls the command -- so any of them reads the shared defaults without
        # touching the corpus.
        namespace = parser().parse_args(["sample"])
        return {
            "min_turns": getattr(namespace, "min_turns", 8),
            "per_repo": getattr(namespace, "per_repo", 2),
        }
    # No parser to read; the shipped values, which `test_the_cli_defaults_are_the_
    # ones_the_worksheet_uses` pins.
    return {"min_turns": 8, "per_repo": 2}


CLI_DEFAULTS: Dict[str, Any] = _cli_defaults()
