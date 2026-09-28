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
from .schemas import list_schemas, load_schema, schema_summary
from .state_dag import SOURCE_DECLARED, SOURCE_INFERRED, FactNode, StateDAG
from .state_protocol import (
    DECLARING_ROLES,
    StateDeclaration,
    escape_value,
    normalise_key,
    parse_declaration,
    render_instruction,
    strip_blocks,
)
from .transcript import parse_transcript
from .vector_tier import RetiredTurnArchive, VectorMemoryTier


def _resolve_version() -> str:
    r"""
    The version, resolved from whichever source describes *this* copy.

    This used to be a string literal. It was still "0.4.0" after 0.4.1 shipped,
    which was found by installing the published wheel and asking it -- the only
    check that exercises the published artifact rather than the checkout. Two
    sources of truth for a version is one too many: the moment anyone bumps
    pyproject.toml, a hardcoded string silently becomes a lie, and the same class
    of drift made this README claim `pip install contextgc` for a package that had
    never been published.

    Order matters, and getting it wrong is its own bug. Installed metadata is what
    was actually uploaded, so it is authoritative for a wheel -- but a source
    checkout usually carries a stale ``*.egg-info`` from an earlier
    ``pip install -e .``, and metadata-first answers 0.4.0 forever in exactly the
    directory where you are editing. A pyproject.toml sitting next to the package
    is therefore authoritative, and metadata is the fallback for when there isn't
    one, which is what an installed copy looks like.
    """
    try:
        import re as _re
        from pathlib import Path

        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        found = _re.search(
            r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), _re.M
        )
        if found:
            return found.group(1)
    except (OSError, ValueError):
        pass

    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("contextgc")
        except PackageNotFoundError:
            pass
    except ImportError:  # pragma: no cover - stdlib since 3.9
        pass

    # Neither source is readable. Say so rather than invent a version, so the
    # failure is visible instead of being a number that looks right.
    return "unknown"


__version__ = _resolve_version()

__all__ = [
    "compile_messages",
    "compile_transcript",
    "patch_openai",
    "ContextGCEngine",
    "StateDAG",
    "FactNode",
    "SOURCE_DECLARED",
    "SOURCE_INFERRED",
    "ToolSanitizer",
    "PolicyInvariantAnchor",
    "InvariantAuditor",
    "parse_transcript",
    "list_schemas",
    "load_schema",
    "schema_summary",
    "StateDeclaration",
    "DECLARING_ROLES",
    "parse_declaration",
    "render_instruction",
    "strip_blocks",
    "normalise_key",
    "escape_value",
    "RetiredTurnArchive",
    "VectorMemoryTier",
    "__version__",
]
