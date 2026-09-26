# Changelog

All notable changes. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.2.0] — the write path

### Added

- **State protocol.** The agent can declare what it concluded as a structured
  side-effect of the turn it was already making. No extra model call, no extra
  latency: the block rides along in a completion that was going to happen
  anyway, and is stripped before the transcript is sent onward so a model never
  sees its own markup.
  - `assert` — assert a value, superseding any earlier one.
  - `pin` — assert and mark immutable. Only a *declared* re-assertion may lift a
    pin; an inferred match never can.
  - `revoke` — void a key. This is the operation supersession cannot express: a
    revoked fact is not replaced, it is invalid, and there is no value to replace
    it with. A revoked key is not resurrected by a later regex match.
  - `unsure` — a low-confidence assertion, tracked and flagged rather than
    presented as settled.
- **Provenance on every fact.** `FactNode.source` is `declared` or `inferred`, and
  an inferred match can never overwrite a declared fact. The state register tags
  each value with its origin so the model can tell what it asserted itself from
  what a pattern guessed.
- **`authority_ratio` telemetry** — the share of tracked facts that came from the
  agent rather than a regex. `1.0` means nothing is guessed; `0.0` means the
  protocol is not being adopted. `None`, not `0.0`, when nothing is tracked.
- `compile_messages(..., teach_protocol=True)` and `patch_openai(...,
  teach_protocol=True)`.
- `confidence_from_logprobs()` — converts an OpenAI-compatible `logprobs`
  response into a normalised confidence, the seam for probabilistic extraction
  and for gating an agent loop on a number rather than a vibe.

### Fixed

- `kv_cache_prefix_intact` was computed as "the shared prefix is unaltered",
  which is true even when everything after message[0] was rewritten. It now means
  the entire input prefix is byte-identical, which is the question a caller
  actually has about their cache.

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
