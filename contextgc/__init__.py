"""
contextgc -- a deterministic context compiler for AI agent transcripts.

Long agent sessions accumulate superseded assertions and bulky tool payloads.
The model then has to reconcile two conflicting values for the same key, and
pays for every token of it. contextgc compiles the transcript down to the
current facts, retires the ones that were replaced, and compacts tool output --
deterministically, in microseconds, with no model call and no network.

    >>> from contextgc import compile_messages
    >>> msgs, telemetry = compile_messages([
    ...     {"role": "user", "content": "deliver to Tower B"},
    ...     {"role": "user", "content": "actually deliver to Gate 2"},
    ... ])
    >>> telemetry["compression_ratio_pct"] > 0
    True

What it does and does not do is documented in the README under "Honest scope".
"""

from .anchors import InvariantAuditor, PolicyInvariantAnchor
from .client import (
    ContextGCEngine,
    compile_messages,
    compile_transcript,
    patch_openai,
)
from .sanitizer import ToolSanitizer
from .state_dag import FactNode, StateDAG
from .transcript import parse_transcript
from .vector_tier import RetiredTurnArchive, VectorMemoryTier

__version__ = "0.1.0"

__all__ = [
    "compile_messages",
    "compile_transcript",
    "patch_openai",
    "ContextGCEngine",
    "StateDAG",
    "FactNode",
    "ToolSanitizer",
    "PolicyInvariantAnchor",
    "InvariantAuditor",
    "parse_transcript",
    "RetiredTurnArchive",
    "VectorMemoryTier",
    "__version__",
]
