"""
``python -m benchmarks`` -- run the harness.

    # measure the read path on real agent trajectories
    python -m benchmarks run --limit 200

    # same, but against a custom entity schema
    python -m benchmarks run --limit 50 --schema benchmarks/schemas/logistics.json

    # compare the read path against replayed declarations
    python -m benchmarks shadow --captures captures/run1.json --limit 50

    # dump a labelled sample for human precision labelling
    python -m benchmarks sample --limit 25

Nothing here prints a percentage without the sample size it came from, and
nothing prints a precision figure unless one was measured against labels.
"""

from .corpus import SWE_AGENT_HF_URL, load_swe_agent, load_synthetic
from .harness import run as run_harness
from .report import render, render_extraction_sample, render_shadow
from .shadow import replay_source, run_corpus, shadow_compare

__all__ = [
    "load_swe_agent",
    "load_synthetic",
    "run_harness",
    "render",
    "render_extraction_sample",
    "render_shadow",
    "shadow_compare",
    "run_corpus",
    "replay_source",
    "SWE_AGENT_HF_URL",
]
