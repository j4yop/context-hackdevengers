# Changelog

All notable changes. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.3.0] — measured against real agent transcripts

The previous release shipped claims. This one ships a harness and reports what it
found, including three things that were wrong.

### Measured

40 real SWE-agent trajectories from `nebius/SWE-agent-trajectories` — 1,390
turns, 1.96M characters, real model output and real tool output:

| | value | n |
|---|---|---|
| facts extracted | 40 | 40 |
| keys re-asserted | 118 | 40 |
| token reduction | 58% | 40 |
| tool payloads compacted | 371 | 40 |
| turns retired | 191 | 40 |
| retirement violations | 0 | 40 |
| compile time p50 / p95 | 2.46 / 6.71 ms | 40 |
| **precision (hand-labelled)** | **82%** | **11 judged** |

n=11 is a smell test, not a statistic, and the report says so.

### Fixed, because the measurement found them

- **`ENTITY_PATTERNS` is now empty.** The default was a logistics schema applied
  to every domain; on 60 real coding transcripts it produced 75 facts and every
  sampled one was prose matched by accident (`destination_address = "of
  parentheses"`). A schema is now opt-in per domain, via
  `compile_messages(..., schema=...)` or `StateDAG.register_entity_schema`. The
  old patterns are kept in `benchmarks/schemas/logistics.json` alongside the
  measurement that condemns them.
- **Tool-output detection is content-based, not convention-based.** The sanitizer
  keyed on a `TOOL_OUTPUT` marker and on `role in (tool, function)`; **0% of
  corpus messages carry that marker** and tool output is filed under `user`, so
  371 real tool outputs were passed through untouched. Token reduction on the
  same corpus went from 17% to 58%.
- **State is no longer inferred from machine-generated output.** A path inside a
  grep listing is not a statement about what the agent is editing, and the
  pattern was promoting it. Search, listing and pytest-output markers are now
  recognised.
- **`compile_messages` gained a `schema` parameter.** The empty default made
  opting in impossible without monkeypatching.
- The harness records a crashing transcript instead of aborting the run, and
  counts a transcript that cannot report its own length rather than dropping it.

### Added

- `benchmarks/` — corpus loader with provenance, measurement harness, shadow-mode
  comparison, hand-label precision scoring, and a report renderer.
- `python -m benchmarks run|shadow|sample|fetch`.
- `benchmarks/schemas/` — `coding.json` (derived from what the corpus actually
  contains), `logistics.json` (the old default, kept as a measured cautionary
  example), `devtools.json`.
- `benchmarks/labels/precision.json` — 20 hand labels with the reasoning for
  each, so the precision figure is auditable rather than asserted.
- `benchmarks/corpus/sample.txt` — a six-trajectory vendored slice for offline CI,
  labelled with its real source so it is never reported as synthetic.
- 19 tests for the harness itself, including that it refuses to report a
  precision it did not measure, and that shadow mode cannot leak a declaration
  into emitted context.

### Known limitations

- The write path is still unmeasured. `benchmarks shadow` exists and works, but
  it needs a capture file from a real run with a real model, and none exists. The
  command refuses rather than inventing a number.
- Precision rests on 11 judged labels. Widening it is the highest-value next
  step.
- The corpus is one domain (Python bug-fixing). Nothing here establishes that the
  mechanism transfers to other agent workloads.
- Token reduction is the library's own `chars/4` estimator on both sides. It is a
  ratio between two numbers from the same estimator, not a billing figure and not
  a latency proxy.

## [0.2.0] — the write path, and a correction

### Added

- **State protocol.** The agent can declare what it concluded as a structured
  side-effect of the turn it was already making, so there is no extra model
  call. Markup is stripped from emitted content *and* from `tool_calls`
  arguments.
  - `assert` — assert a value, superseding any earlier one.
  - `pin` — assert and mark immutable. **A bare `assert` cannot lift a pin**;
    only an explicit re-pin can, or `revoke`.
  - `revoke` — void a key. The operation supersession cannot express: a revoked
    fact is not replaced, it is invalid. **Cannot void a structural guardrail.**
  - `unsure` — a low-confidence assertion, tracked and flagged.
- **Provenance on every fact.** `FactNode.source` is `declared` or `inferred`, an
  inferred match can never overwrite a declared fact, and the state register now
  emits the provenance so the model can act on the distinction.
- **`conflicts` telemetry** — the agent asserted a key and the transcript's own
  text disagrees. The only quantity here that correlates with a wrong state.
- **`rejected_writes` telemetry** — writes the compiler refused: pinned keys,
  lifted guardrails, markup from an untrusted role. Previously computed and
  thrown away.
- `compile_messages(..., teach_protocol=True)` and `patch_openai(...,
  teach_protocol=True)`.
- `get_retirement_violations(proposed)` — checks a *proposed* retirement set for
  live facts left without support.
- Key normalisation, so casing and separator variants cannot fork the state
  space, and declared register caps (`MAX_TRACKED_FACTS`, `MAX_VALUE_CHARS`).

### Removed

- **`authority_ratio`.** Renamed to `declared_share` because "authority" implied
  a quality judgement it cannot make: a declared fact always outranks an inferred
  one, so the score rises precisely when the model's opinion wins a
  disagreement. A transcript where the agent declared a stale value reads `1.0`.
  Use `conflicts`.
- **`confidence_from_logprobs()`.** A speculative seam for calibrated extraction,
  added with a fabricated example in the README (it documented `-> 0.75`; it
  returned `0.5978`), and severed at the first line of code that touched it —
  the parser discarded the `confidence` field and `FactNode.confidence` only ever
  held the string `"unsettled"`. A probabilistic component in front of a
  mechanism that cannot tell a good declaration from a forged one adds a second
  way to be wrong. The `{value, confidence}` payload shape is now rejected as
  malformed rather than silently flattened.

### Fixed

- **Only the assistant may declare state.** Tool output, user text, and system
  messages could all forge authoritative declarations — a fetched web page, a
  pasted injection, or a quote of this project's own README each became live
  state marked `declared`.
- **Pins are sticky.** A single bare `assert` silently un-pinned a key, while
  the instruction told the model "later turns cannot overwrite it".
- **`revoke` cannot delete a structural guardrail.** One JSON string removed
  `dietary_allergy`.
- **`revoke` of an untracked key no longer writes a tombstone**, permanently
  disabling inference for a key that was never live. A deliberate re-assertion
  clears the tombstone, so the register cannot claim a key is both live and
  retired.
- **`rollback_to` can now undo a `revoke`.** `revoke` destroyed the node history
  the restore path read from, so the documented behaviour was impossible. The
  log-pruning filter also keyed on `new_turn` while revoke/reject entries use
  `turn`, so those were never pruned.
- **Conflicts are detected.** The previous check read the post-apply inferred
  value, but a blocked write never lands there — so every genuine disagreement
  was invisible.
- **Rejections are surfaced.** `rejected` was built and discarded; the audit
  trail existed only for direct `StateDAG` users, not through the SDK, server,
  or web UI.
- **The state register shows provenance**, as the previous release notes claimed
  it did. It did not.
- **`strip_blocks` handles nesting, blocks inside JSON payloads, and markdown
  fences**, and leaves an emptied turn as a space rather than `""` (rejected by
  some providers). An unterminated tag is left alone instead of deleting the rest
  of a human's message.
- **Values are escaped against tag forgery, not just brackets.** The register is
  re-parsed every compile, so an unescaped `<contextgc-state>` in a declared
  value round-tripped back in as a fresh declaration.
- **Re-compiling no longer stacks registers.** It produced two, the stale one
  first, so the prompt asserted two different current values. Transcripts written
  by 0.1.0 carry the old marker and are recognised too.
- **Growth is reported.** `token_growth` and `context_grew` state when the
  register costs more than it saves; `compression_ratio_pct` is clamped at 0 and
  hid it.
- `kv_cache_prefix_intact` now means the whole input prefix is byte-identical,
  rather than "the shared prefix is unaltered", which held even when everything
  after the first message was rewritten.

### Known limitations

- The write path does **not** reliably resolve coreference. The agent has to
  notice the reference and report it; when it does not, the state is quietly
  incomplete. There is no measurement of how often.
- Compliance is unfalsifiable from inside. `conflicts` and `rejected_writes` are
  the only signals, and both are silent when the agent simply says nothing.
- Transcripts the user did not produce — imported agent logs, third-party chats —
  get nothing from this feature, since no protocol is present.

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
