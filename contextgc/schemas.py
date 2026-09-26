"""
The shipped entity schemas, and how to get one.

The library defaults to no patterns at all, because the default it used to ship
was measured producing nonsense on real transcripts. A caller who wants state
tracking therefore has to pick a domain -- and until now there was no way for an
installed user to do that: the schemas lived under ``benchmarks/``, which is a
measurement harness, and were not in the wheel at all.

So they live here, inside the package, and this module is the supported way to
reach them::

    from contextgc import compile_messages, load_schema

    compiled, telemetry = compile_messages(messages, schema=load_schema("coding"))

Every schema is a JSON file with a ``_comment`` recording how its patterns were
arrived at. That prose is documentation, not a pattern; :func:`load_schema`
returns the normalised ``{slot: [pattern, ...]}`` mapping ready to pass in, with
the comment left behind.
"""

import json
import os
from typing import Any, Dict, List

#: Directory holding the shipped schemas, inside the package.
SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas")

#: Suffix for a schema file.
_SUFFIX = ".json"


def list_schemas() -> List[str]:
    """
    Names of the shipped schemas, sorted.

    Returns an empty list rather than raising if the package data is missing, so
    a broken install degrades to "no schemas offered" instead of taking down the
    caller at import time.
    """
    try:
        return sorted(
            name[: -len(_SUFFIX)]
            for name in os.listdir(SCHEMA_DIR)
            if name.endswith(_SUFFIX) and not name.startswith("_")
        )
    except OSError:  # pragma: no cover - only on a broken install
        return []


def schema_path(name: str) -> str:
    """
    Absolute path to a shipped schema.

    Raises:
        KeyError: if there is no such schema. The message lists what there is,
            because "unknown schema" with no alternatives is a dead end.
    """
    available = list_schemas()
    if name not in available:
        raise KeyError(f"unknown schema {name!r}; have {available}")
    return os.path.join(SCHEMA_DIR, name + _SUFFIX)


def schema_summary(name: str) -> Dict[str, Any]:
    """
    What a schema tracks, and why its patterns look the way they do.

    Returns the slot names plus the first line of the schema's ``_comment``, which
    is what the website shows next to the picker.
    """
    with open(schema_path(name), encoding="utf-8") as handle:
        raw = json.load(handle)
    comment = str(raw.get("_comment", "")).strip()
    return {
        "name": name,
        "entities": sorted(raw.get("entities", {})),
        "summary": comment.split("\n")[0] if comment else "",
        "detail": comment,
    }


def load_schema(name: str) -> Dict[str, Any]:
    """
    Load a shipped schema, ready to pass to ``compile_messages(schema=...)``.

    Args:
        name: a name from :func:`list_schemas`, e.g. ``"coding"``.

    Returns:
        ``{slot: [pattern, ...]}``. The ``entities`` wrapper and the ``_comment``
        documentation key are both resolved here, so the caller never has to know
        how the file is laid out.

    Raises:
        KeyError: if there is no such schema.
    """
    from .gc_engine import _normalise_schema

    with open(schema_path(name), encoding="utf-8") as handle:
        raw = json.load(handle)
    return _normalise_schema(raw)
