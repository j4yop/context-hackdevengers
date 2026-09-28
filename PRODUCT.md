# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences, in this order of how often they arrive:

**Engineers building agent features.** They are adding context management to an
agent and need to know whether it will corrupt the agent's state. They evaluate
by integrating it — `pip install contextgc`, wrap a client, compile a
transcript — and they judge it on whether the state register is correct and
whether the provenance is inspectable. Their failure mode is discovering a
silently wrong fact three weeks later.

**Teams debugging agent behaviour.** They arrive *after* an agent contradicted
itself, holding a transcript, wanting to see what the model actually received and
why. They use the console at `/console` and they need the reasoning behind every
number, not a summary. Their failure mode is a tool that says "compacted" without
saying what it dropped.

## Product Purpose

contextgc compiles an agent transcript down to what is currently true: it retires
turns whose state has been superseded and compacts bulk tool output, before the
transcript reaches the model.

It exists because long agent sessions accumulate two different values for the
same key, and a model handed both has to reconcile them — or pick one, silently.
The mechanism is deterministic, so the same input always compiles to the same
output, and every change is attributable to a specific turn.

**Success means being trusted with the state register.** A user should be able to
look at the compiled context, see which turn each fact came from, and disagree
with a specific decision. A product that is convincing but not inspectable fails
at this, because the user cannot tell the difference between "correct" and
"confident".

## Positioning

Deterministic and model-free. The same input compiles to the same output, with no
API key and no model call, in about a millisecond.

Neighbouring approaches are either a model summarising the transcript — which
costs a call per turn, is not reproducible, and cannot be reasoned about when it
is wrong — or leaving compaction to the provider's prompt cache, which saves
money but does not remove the contradiction. contextgc makes neither trade. The
claim a neighbour could not truthfully copy is the measurement: three public
corpora, 180 real trajectories, hand-labelled precision with confidence
intervals, and a documented list of what the thing cannot do.

## Operating Context

- A stateless HTTP API. Nothing is persisted, no key is required, and the website
  is a client of that same API rather than a demo of something else.
- The console is the primary surface for evaluation; the landing page is the
  primary surface for deciding whether to evaluate.
- The measurement harness (`benchmarks/`) is part of the product, not a test
  fixture. Three corpora run nightly against real trajectories.
- A committed capture (`captures/run1.json`) lets the write-path comparison replay
  deterministically without a GPU, and the nightly compares it to a baseline so a
  change in model behaviour fails a build.
- Release is via PyPI Trusted Publishing; `docs/RELEASING.md` holds the
  procedure.

## Capabilities and Constraints

- Zero runtime dependencies. The release pipeline fails the build if that changes.
- No model call, ever, in the compile path.
- Token counts are a `chars/4` heuristic, not a BPE tokenizer. Reported as a
  ratio, never as a bill.
- The read path is regular expressions. No coreference resolution, so a fact
  expressed only through pronouns is missed. The state is silently incomplete
  rather than loudly wrong — a known, accepted failure mode.
- The read path refuses to infer state from machine-generated output. Measured:
  every mislabelled extraction in the coding corpus came from a path inside a
  stack trace or a search listing.
- The write path depends on the model cooperating, and at the one model measured
  (qwen2.5:7b) it contributed zero verified information. `declaration_policy`
  exists so a deployment can hold declarations to its schema.
- Three shipped entity schemas, every one measured against a labelled corpus and
  stating its evidence in `/api/schemas` and in the console picker. A fourth,
  `devtools`, was deleted on 2026-09-28: its four patterns fired zero times
  across all 180 transcripts, so it was an untested hypothesis offering itself in
  the console beside three that work. A schema that has never fired is not a
  tuned schema.
- Supported on Python 3.9, 3.11 and 3.13. A test that cannot run on 3.9 is not a
  guard, and one did not.

**Undecided:** whether the write path is worth enabling at all. It is off by
default in spirit — the shipped default schema is empty — and the question needs
a capture from a model stronger than the one measured.

## Brand Commitments

- **Name:** contextgc. The `cg` mark.
- **Voice:** plain, specific, and willing to publish a bad number. The project's
  central commitment is that a claim arrives with its `n`, its confidence
  interval, and the failure it does not cover.
- Trustworthiness is the whole strategy, not a veneer on a growth strategy. This
  is the confirmed answer to what success means, and it has a cost: the landing
  page leads with caveats a conventional one would hide, which repels skimmers.
  That is the intended trade.

## Evidence on Hand

- **Three real corpora, measured:** 40 SWE-agent coding trajectories across 20
  repositories; 60 APIGen-MT-5k airline conversations; 80 retail. Token
  reduction 66.5% / 59.0% / 62.5%; precision 100% on every one, with n and CI.
- **A committed real-model capture:** `captures/run1.json`, 42 assistant turns,
  `qwen2.5:7b`, with the write path measured and reported as net-negative.
- **A hand-labelled sample** for the precision figures, 39 labels over 36
  independent units. `benchmarks/labels/known_failures.json` is **empty**: it held
  two entries that were re-read and found to be *correct* extractions, mislabelled
  because the turn's prose discussed a different file. The correction is recorded
  beside the empty list, and the file plus its tests remain so the first real
  error is checkable from the moment it is recorded.
- **No schema ships without evidence.** Every entry in `/api/schemas` names its
  corpus, its sample size and its precision, and a test fails if a shipped
  schema's patterns never fire.

**Must not be fabricated:** customer names, testimonials, adoption or download
figures, any performance claim not in the README, and any comparison to another
product. There are no users yet and no adoption signal at all.

## Product Principles

1. **A number without its `n` is advertising.** Every figure ships with the
   sample it came from and a confidence interval where one applies.
2. **Report the unfavourable result.** The write path measured net-negative and
   that is on the front page. A tool that only lists strengths cannot be relied
   on to tell you when it is wrong.
3. **Deterministic or it is not this product.** No model in the compile path, no
   sampling, no "usually".
4. **Silence is a defect.** A missed extraction, a dropped payload row, an
   off-schema declaration and a conflict all surface in telemetry and in the
   console. If it is not visible, it is not fixed.
5. **A correction is a deletion.** When a measurement falsifies a published
   claim, the claim goes, even when it was the project's own headline.

## Accessibility & Inclusion

WCAG AA for text contrast, measured in a browser rather than asserted — the dark
theme's primary button was 2.5:1 before it was checked. Interactive state must be
legible in both themes, tables must remain readable at 320px, and focus and
selection must ship styled rather than as browser defaults.
