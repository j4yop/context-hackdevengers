# Changelog

All notable changes. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0]

First release after an audit that found most of the previously published metrics
were not supported by the code. The rewrite removes those claims rather than
defending them.

### Removed

- Fabricated latency model (`500 + raw*0.25` vs `400 + clean*0.15`) and every
  metric derived from it. Nothing in the project measured time-to-first-token.
- "100% policy invariant compliance" claim. The auditor behind it was a regex run
  against text the server had just generated, in a path unused in production.
- The benchmark "vanilla agent", whose state was derived from contextgc's own
  state tracker.
- `VectorMemoryTier`'s 768-dim pseudo-embeddings (SHA-256 word hashing) and the
  `ivfflat` `DDL_SCHEMA` constant, which was referenced nowhere. The class is now
  `RetiredTurnArchive` and its lexical recall is documented as lexical.
- Hardcoded business invariants ("refunds over ₹150") that shipped as defaults.
- Synthesized completions from `/v1/chat/completions`. The endpoint now returns
  503 when no upstream key is configured.
- Forwarding of caller-supplied `Authorization` headers to the upstream model.
- All hardcoded metrics from the README, pitch deck, and slide deck. Every number
  in the UI is now computed per request.
- Presentation, slidev deck, demo scripts, benchmark scenarios, and the
  hackathon submission manifest.

### Fixed

- Retiring a turn did not retract the facts it uniquely asserted, leaving an
  authoritative value in the prompt with no supporting turn. `get_orphaned_facts()`
  is the invariant; it is asserted empty on every compile.
- Tool-payload compaction could discard safety-relevant rows — a 25-item
  catalogue truncated to 3 items dropped a `PEANUT_ALLERGEN` warning on item 15.
  Safety-signalled rows are now always retained and omissions are reported.
- `cache_friendly` mode mutated the prefix it claimed to preserve, because tool
  payloads were distilled before the mode was read. Prefix preservation is now
  verified by diffing emitted output against input.
- Retired-turn recall read the archive before the loop that populated it, making
  it unreachable via `compile_messages`.
- Module-global engines accumulated archive rows across requests without bound.
  State is now per-invocation.
- Archived content was interpolated into a live user turn unescaped, allowing
  forged bracket delimiters.
- Three entity patterns missed common phrasings: "a severe peanut allergy",
  "set the gate code to 1111", "change the address to X".

### Added

- `contextgc` distribution with a real build backend, `py.typed`, and working
  `pip install`. The importable package is `contextgc`, not `core`.
- `compile_transcript` / `parse_transcript`: accept pasted plain-text transcripts
  or JSON, with per-line parser warnings instead of silent drops.
- `POST /api/compile` — stateless, no key, no model call, 256 KiB cap,
  rate-limited, `Cache-Control: no-store`.
- Website rewritten around a real input: paste a transcript, see the compiled
  context, the current state, what was superseded, and which turns were retired.
- `StateDAG.register_entity_schema()` for domain-specific entities.
- `InvariantAuditor` with caller-supplied rules via `scan_with`.
- 57 tests that assert the published claims at falsifying tolerances, including
  a network-isolation test and a no-fabricated-telemetry test.
