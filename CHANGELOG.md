# Changelog

All notable changes. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] — a third slice, and the default schema's failure measured at scale

### Fixed

- **The shipped `logistics` schema produced only wrong answers on real data.** It
  was the library's default before the rewrite, and on 80 real APIGen-MT retail
  conversations it extracted 46 facts of which **every one read in context was
  wrong** — `destination_address = "perfectly suit my needs"`, `= "my existing
  PayPal account"`, `= "the Visa card ending in 2364"`. The `use` trigger is the
  cause: in retail, "use" is nearly always about money. The original evidence for
  emptying the default was three examples on coding transcripts; this is the same
  defect at scale, on the domain the schema was written for. Replaced by a schema
  derived from 400 measured conversations, and the original is kept at
  `benchmarks/schemas/condemned/` with a nightly job asserting it still fails.
- **A rejected alternative was recorded as the current value.** "instead of the
  credit card you have on file" names a value in order to reject it, and it became
  the payment method. The single wrong answer in a 48-judgement retail sample.
- **The negation guard is now structural rather than a character window.** The
  obvious fix — adding "instead of" to the prefix window — would have thrown away
  the *new* value in "instead of Gate 3, deliver to Gate 2", replacing one error
  with another. A negator now only governs a value it is immediately attached to:
  a comma or a fresh intent verb between them means it governs something else.
  Seven cases pinned, covering both directions.
- **A performance test was intermittently failing.** `test_compile_time_is_sub_10ms`
  timed a single cold call against a 10ms budget and went red on a loaded machine
  — 3.6ms to 13.7ms across seven runs of identical input, failing on the previous
  commit too. Now the minimum of nine warmed runs, because contamination from
  other load can only make a measurement slower. A guard that goes red at random
  is worse than no guard.

### Measured

| | condemned original | measured replacement |
|---|---|---|
| facts extracted | 46 | 47 |
| slots | `destination_address` only | `delivery_address`, `payment_method` |
| precision | 0 of 14 read in context | 100% (n=47, CI 92–100%) |

### Not fixed, and stated

- **Retail is a poor fit for a last-write-wins tracker.** 79–95% of every mutable
  entity's mentions live in tool output, which the read path may not read, and
  supersession is rare: payment method changes in 1% of conversations, the order
  in 5%, the delivery address in 15% of the 26 conversations that mention one. The
  numbers are in the schema file. No pattern tuning changes this.
- `refund_amount` is deliberately not tracked despite 2,280 spoken mentions,
  because 93% of conversations contain several different dollar amounts rather
  than one being corrected. One slot for them would track nothing.

## [Unreleased] — a second domain, and three defects it exposed

Measuring a second corpus was the last thing on the list of gaps, and it found
more than a second set of numbers.

### Added

- **A second corpus: `Salesforce/APIGen-MT-5k`.** Airline-reservation customer
  service with real tool calls, via `--corpus apigen`. Everything measured before
  this was Python bug-fixing, which is a statement about one domain rather than
  evidence of generalisation.
- **`contextgc/schemas/travel.json`**, derived by measuring 200 conversations
  rather than by choosing convenient entities.
- **Per-corpus label files.** `gold.score` picks the label file belonging to the
  corpus it is scoring, so travel labels are not checked against coding
  extractions. Travel precision: 100% on 72 independent units across 52
  conversations, 95% CI 95–100%.
- **`benchmarks capture`** — records what a real model actually declared, so
  `shadow` has something honest to replay. `capture --verify` refuses a capture
  that recorded no declarations or does not say which endpoint produced it. The
  endpoint comes from the environment, never an argument, so a key cannot land in
  a shell history or a CI log. No capture is fabricated: with no model reachable,
  the write path stays unmeasured.
- **Short JSON payloads are recognised as machine output.** APIGen files its tool
  results under `user` as compact JSON and the length-based heuristic caught none
  of them, so they were never compacted. Now 15,937 of 21,955 are detected, with
  no false positives on human or assistant turns, and an agent quoting JSON is
  still an agent.

### Fixed

- **A repeat was being treated as a contradiction.** There was no value comparison
  at all: any new extraction for a live entity superseded the previous one, so
  restating a fact retired the earlier turn and took everything else it carried.
  Found by reading registering turns in the second domain, where an agent says
  `**Cabin Class:** Business` and then `business class`. A repeat is now a
  reaffirmation; a value differing only in case is recorded as one; genuinely
  different values supersede as before; and a declaration over an identical
  inference still upgrades the recorded provenance.
- **A schema-free extractor survived the rewrite.** A generic `set <key> to
  <value>` scraper and a `{"k": "v"}` harvester sat behind the registered
  patterns, creating `slot_*` and `config_*` facts with no schema and no opt-in —
  and the JSON one read machine output, its only guard being `role not in
  ("tool", "system")` while every corpus files tool results under `user`. Found by
  extracting `slot_symbol = "€"` out of `currency = {"symbol": "€"}`. Both are
  gone; a caller who wants a slot has to declare a schema.
- **`reservation ID corresponds` was extracted as `active_reservation = "corres"`.**
  No trailing word boundary, so six characters of a thirteen-letter word matched,
  and case-insensitive compilation let lowercase prose satisfy an uppercase-id
  class. The id group is now case-scoped and closed.
- **`basic economy` was collapsed to `economy`.** The airline domain prices them
  differently — the phrase appears 435 times in 60 conversations — so the
  extraction was confidently wrong exactly when it mattered. It is its own value
  now.
- **A flight-options menu was read as a booking.** One turn listed every cabin with
  seat counts and prices and then asked the user to choose; the pattern took
  `Basic Economy` off the price list.

### Corrected

Fixing the repeat bug removed phantom supersession, so the previously published
figures were counting repeats as changes. The corrected numbers:

| | before | after |
|---|---|---|
| coding, key re-assertions | 187 | 77 |
| coding, turns retired | 271 | 161 |
| coding, token reduction | 70.1% | 66.5% |
| travel, turns retired | 58 | 9 |
| travel, token reduction | 57.5% | 54.3% |
| coding, independent units | 35 | 39 |

The earlier figures were not arithmetic errors. They were measuring a restatement
as a change of mind.

## [0.4.0] — systems check, two more precision defects, and a corpus that was too narrow

A full pass over the package: clean-venv install from the wheel, every endpoint
exercised, the website driven end to end, and a second labelling round. Four
defects found, three of them visible only when the site was actually used.

### Fixed

- **The website was broken by the empty default schema.** Its own example produced
  zero state and zero retired turns, so the "Current state" and "What changed"
  panels rendered empty and the site silently demonstrated nothing. The site now
  has a schema picker, defaults to the schema that matches the loaded transcript,
  and states plainly *why* there is no state when none is selected — rather than
  showing an empty table that reads as "nothing found".
- **`GET /api/schemas`** exposes the shipped schemas with their slots and the note
  explaining why there is no default. `POST /api/compile` takes
  `entity_schema`; an unknown name is a **404**, not a silent empty state.
- **A weak `in <path>` trigger matched prose.** *"Upon reviewing `main.py` again
  … `dispatcher.py` uses a helper"* was recorded as `current_file = dispatcher.py`.
  Every incorrect label in the first precision pass traced to it. Patterns now
  require an explicit verb acting on the path.
- **A single-letter `c` extension parsed `example.com` as `example.c`.** Patterns
  now require a real path prefix.
- **Agent-environment responses leaked into inference.** `(Open file: …)`,
  `(Current directory: …)`, `bash-$` and the edit-rejection notice are short
  enough to miss the length heuristic, and they name the file the editor is
  sitting on — exactly the value the schema wants. Now recognised as machine
  output.

### Measured

| | before | after | n |
|---|---|---|---|
| precision, independent units | — | **100%** (95% CI 90–100%) | 35 |
| repositories in the corpus | 3 | **20** | 40 |
| key re-assertions | 118 | 187 | 40 |
| token reduction | 58% | 70.1% | 40 |
| tool payloads compacted | 371 | 668 | 40 |
| turns retired | 191 | 271 | 40 |
| retirement violations | 0 | 0 | 40 |

### The precision sample was not measuring what it claimed

Two problems, both in the measurement rather than the compiler, and both larger
than the number they were attached to:

- **The corpus was 3 repositories wide.** The shard is repository-ordered and the
  loader took the first N usable rows, so "40 transcripts" meant 40 trajectories
  from three codebases. `load_swe_agent` now takes `per_repo` (CLI default 2),
  which spreads the same 40 transcripts over **20** repositories. This changed
  every aggregate number above, not just precision.
- **The label set was 2 repositories wide and partly self-repeating.** All 24
  rows came from two repositories, and several were the *same turn* of the same
  issue read twice from two trajectories of that issue — one observation counted
  two or three times. Re-running the old labels against the widened corpus
  collapsed the sample to **n=2**, which is how this surfaced.

Fixed by re-reading the labels from scratch, one extraction per
`(repository, turn)`: 36 labels, 35 judged, across 20 repositories.
`gold.score` now reports the clustered count alongside the row count and a 95%
Wilson interval, so `n` inflation is visible and a point estimate is not mistaken
for a measurement. `benchmarks/labels/corpus.json` records the exact loader
settings, so the sample can be regenerated rather than guessed at.

### Still not fixed

The two confirmed extraction errors — a path named in one sentence while the
agent's subject is a different file in another — are **not** fixed. Knowing which
file an agent *intends* to edit needs intent, not a regex. Worse, `--per-repo`
structurally excludes the rows they came from, so a sampling change could have
hidden them. They now live in `benchmarks/labels/known_failures.json`, and
`test_known_failures_still_reproduce_as_errors` re-runs those exact rows and fails
if they stop being wrong. The entry has to be deleted on purpose.

### Added

- 16 tests covering the empty-default contract, schema survival across the
  per-invocation graph reset, the three precision defects above, and
  machine-output detection for agent-environment responses.
- `entity_schema` on both compile endpoints; `GET /api/schemas`.

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
