"""
Benchmark corpus: real agent transcripts, with provenance.

Everything this package measures is reported alongside where the data came from
and how many items it was measured on. A benchmark that cannot say ``N`` is a
story, not a measurement.

Two sources are supported.

``swe-agent-trajectories`` (default)
    Real SWE-bench trajectories: multi-turn coding conversations with genuine
    tool output, stack traces and retries. Fetched on demand from
    ``nebius/SWE-agent-trajectories`` on HuggingFace. This is the corpus the
    original ~70% claim was never tested against, and testing against it is
    what surfaced the precision problem documented in the README.

``synthetic``
    Transcripts written for tests. Useful for regression, worthless as evidence:
    they were authored by the same person who wrote the patterns, so they match
    the patterns by construction. Reports always label this source.
"""

import os
from typing import Any, Dict, Iterable, List, Optional

#: Kept in sync with the README so a reader can check the claim against the data.
SWE_AGENT_DATASET = "nebius/SWE-agent-trajectories"
SWE_AGENT_SHARD = "data/train-00000-of-00012.parquet"
SWE_AGENT_HF_URL = (
    "https://huggingface.co/datasets/"
    + SWE_AGENT_DATASET
    + "/resolve/main/"
    + SWE_AGENT_SHARD
)

#: Role vocabulary differs per source; normalise to OpenAI names.
_ROLE_MAP = {
    "ai": "assistant",
    "assistant": "assistant",
    "model": "assistant",
    "user": "user",
    "human": "user",
    "system": "system",
    "tool": "tool",
    "function": "tool",
}


class Transcript:
    """One transcript plus everything needed to interpret a measurement on it."""

    __slots__ = ("id", "messages", "source", "meta")

    def __init__(
        self,
        transcript_id: str,
        messages: List[Dict[str, Any]],
        source: str,
        meta: Optional[Dict[str, Any]] = None,
    ):
        self.id = transcript_id
        self.messages = messages
        self.source = source
        self.meta = meta or {}

    @property
    def n_turns(self) -> int:
        return len(self.messages)

    @property
    def n_chars(self) -> int:
        return sum(len(m.get("content") or "") for m in self.messages)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Transcript {self.id} {self.n_turns} turns {self.source}>"


def normalise_messages(raw: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Map a source-specific message list onto the OpenAI shape the compiler takes.

    Drops empty turns rather than passing them through: a message with no content
    contributes nothing but a token-count artefact.
    """
    out: List[Dict[str, Any]] = []
    for message in raw:
        role = _ROLE_MAP.get(str(message.get("role", "")).lower())
        if role is None:
            continue
        content = message.get("content")
        if content is None:
            content = message.get("text")
        if not isinstance(content, str) or not content.strip():
            continue
        out.append({"role": role, "content": content})
    return out


def load_swe_agent(
    limit: int = 200,
    min_turns: int = 8,
    max_turns: int = 200,
    path: Optional[str] = None,
    per_repo: Optional[int] = None,
) -> List[Transcript]:
    """
    Load real SWE-agent trajectories.

    Args:
        limit: stop after this many usable transcripts.
        min_turns: skip anything shorter. Very short transcripts cannot
            accumulate a contradiction, so including them would flatter the
            supersession measurement.
        max_turns: skip anything longer, to bound runtime.
        path: a local parquet shard. If absent, the shard is downloaded to the
            harness cache directory.
        per_repo: cap on trajectories taken from any one ``instance_id``. The
            shard is ordered by repository, so ``limit`` alone yields a sample
            drawn from a handful of repos and a measurement that is really a
            measurement of those repos. Capping forces breadth.

    Returns:
        Transcripts tagged ``source="swe-agent-trajectories"``, spread over as
        many distinct repositories as the shard allows.
    """
    frame = _read_shard(path)
    out: List[Transcript] = []
    taken_per_repo: Dict[str, int] = {}
    for row_index, (_, row) in enumerate(frame.iterrows()):
        if len(out) >= limit:
            break
        raw = list(row["trajectory"])
        messages = normalise_messages(raw)
        if not (min_turns <= len(messages) <= max_turns):
            continue
        # Breadth before depth: the shard is repo-ordered, so without a cap the
        # first N transcripts come from a couple of repositories and every
        # number derived from them inherits that narrowness.
        base = str(row.get("instance_id") or f"swe-{row_index}")
        if per_repo is not None and taken_per_repo.get(base, 0) >= per_repo:
            continue
        taken_per_repo[base] = taken_per_repo.get(base, 0) + 1
        # `instance_id` repeats: a SWE-bench instance has several independent
        # trajectories. Ids must be unique or a per-transcript measurement --
        # including a precision label -- cannot be attributed to one of them.
        base = str(row.get("instance_id") or f"swe-{row_index}")
        out.append(Transcript(
            transcript_id=f"{base}#{row_index}",
            messages=messages,
            source="swe-agent-trajectories",
            meta={
                "instance_id": base,
                "shard_row": row_index,
                "model": str(row.get("model_name") or "unknown"),
                "exit_status": str(row.get("exit_status") or "unknown"),
                "dataset": SWE_AGENT_DATASET,
            },
        ))
    return out


def _read_shard(path: Optional[str]):
    import os

    try:
        import pandas
    except ImportError as exc:  # pragma: no cover - dependency guidance
        raise SystemExit(
            "The corpus loader needs pandas and pyarrow:\n"
            "  pip install 'contextgc[bench]'\n"
            f"(import failed: {exc})"
        ) from exc

    if path is None:
        path = cached_shard()
    if not os.path.exists(path):
        raise SystemExit(
            f"No corpus shard at {path}.\n"
            "Pass --corpus-path, or allow the download:\n"
            f"  curl -L -o {path} {SWE_AGENT_HF_URL}"
        )
    return pandas.read_parquet(path)


def cached_shard() -> str:
    """Where a downloaded shard lives. Outside the repo, per the workspace rules."""
    import os

    cache = os.path.expanduser("~/.cache/contextgc")
    os.makedirs(cache, exist_ok=True)
    return os.path.join(cache, "swe-agent-trajectories-00000.parquet")


def load_synthetic(path: str) -> List[Transcript]:
    """
    Load newline-block transcripts from a file.

    The source is read from a ``# source:`` header in the file so that a
    vendored slice of *real* trajectories is not reported as synthetic. Getting
    this wrong in either direction is the failure mode this whole package exists
    to avoid, so the header is required: a file without one is labelled
    ``synthetic`` and the report says so loudly.
    """
    with open(path, encoding="utf-8") as handle:
        raw = handle.read()

    declared_source = "synthetic"
    for line in raw.splitlines():
        if line.lower().startswith("# source:"):
            declared_source = line.split(":", 1)[1].strip()
            break

    blocks = [b.strip() for b in raw.split("\n---\n") if b.strip()]
    out: List[Transcript] = []
    for index, block in enumerate(blocks):
        from contextgc.transcript import parse_transcript

        # Strip the comment header lines; they are provenance, not turns.
        body = "\n".join(
            line for line in block.splitlines()
            if not line.lstrip().startswith("#")
        )
        messages, _ = parse_transcript(body)
        if messages:
            out.append(Transcript(
                transcript_id=f"{declared_source}:{index}",
                messages=messages,
                source=declared_source,
                meta={"file": os.path.basename(path)},
            ))
    return out


def describe(transcripts: List[Transcript]) -> Dict[str, Any]:
    """Corpus-level provenance, printed alongside every measurement."""
    if not transcripts:
        return {"count": 0}
    turns = sorted(t.n_turns for t in transcripts)
    models: Dict[str, int] = {}
    for t in transcripts:
        models[t.meta.get("model", "unknown")] = models.get(t.meta.get("model", "unknown"), 0) + 1
    return {
        "count": len(transcripts),
        "source": transcripts[0].source,
        "turns_total": sum(turns),
        "turns_min": turns[0],
        "turns_median": turns[len(turns) // 2],
        "turns_max": turns[-1],
        "chars_total": sum(t.n_chars for t in transcripts),
        "models": models,
    }
