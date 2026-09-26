# Contributing

## The one rule

**Do not publish a number the code does not measure.**

This project was previously built around metrics its own code did not support —
an estimated latency model presented as a benchmark, a "100% compliance" figure
produced by regex-matching a string the program had just written, a vector index
that existed only as a SQL comment. The rewrite deleted all of it. Please do not
add it back.

Concretely:

- If a number appears in the README, the UI, or a release note, there must be a
  test asserting it at a tolerance tight enough that the test fails when the
  claim becomes false.
- A metric computed by the code under test is not a benchmark. The previous
  "baseline" was derived from the system's own state tracker.
- If you cannot measure something, say so in prose. A missing number is
  defensible; a fabricated one is not.

## Setup

```bash
pip install -e ".[dev]"
pytest -q
```

Zero runtime dependencies. Please keep it that way — the value of this library
is that it is auditable in one sitting, and a dependency tree is the fastest way
to lose that. If you need real semantic recall or real tokenisation, add it
behind an optional extra, never a hard requirement.

## Tests

Tests live in `tests/test_contextgc.py` and must run without network access. A
test that needs the network is a test that should not exist.

When you change behaviour, change the README's "Honest scope" section in the same
commit if it becomes inaccurate. That section is the project's real contract.

## Reporting a bug

A transcript that makes the compiler produce a wrong result is the most valuable
bug report available, because the state tracker is regex-based and its blind
spots are the interesting part. Please include the transcript verbatim.
