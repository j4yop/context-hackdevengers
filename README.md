# contextgc

**A deterministic context compiler for AI agent transcripts.**

Long agent sessions accumulate two kinds of dead weight: facts that were replaced
but never removed, and tool payloads far larger than the signal in them. The
model then has to reconcile two different values for the same key — and you pay
for every token of it.

`contextgc` compiles a transcript down to what is currently true. No model call,
no network, no API key, no dependencies. Same input, same output, microseconds.

```bash
pip install contextgc
```

```python
from contextgc import compile_messages

messages = [
    {"role": "user", "content": "Deliver order ORD-1 to Tower B, Flat 402. Severe peanut allergy."},
    {"role": "assistant", "content": "Confirmed, routing to Tower B."},
    {"role": "user", "content": "The elevator is broken. Deliver to the Clubhouse desk."},
    {"role": "assistant", "content": "Updated, routing to Clubhouse."},
    {"role": "user", "content": "Actually reroute to Gate 2. Code 4921."},
    {"role": "assistant", "content": "Rerouted to Gate 2."},
    {"role": "user", "content": "Thanks."},
]

compiled, telemetry = compile_messages(messages)

telemetry["active_state_slots"]
# {'destination_address': 'Gate 2', 'dietary_allergy': 'peanut'}

telemetry["retired_turn_indices"]
# [1, 3]  -- the two assistant turns that asserted a now-stale address
```

Try it on your own transcript at **[context-hackdevengers.vercel.app](https://context-hackdevengers.vercel.app)** —
paste a conversation on the left, get the compiled context back on the right.

---

## Two ways to get state out of a transcript

### 1. Read path — infer it (default, works with any model)

Patterns scan the text for assertions. Deterministic, zero cost, works on
transcripts you did not produce. Its ceiling is hard: it cannot resolve *"send it
to the new place instead"*, because "it" and "the new place" are not patterns.
Anything it misses leaves the state silently incomplete.

### 2. Write path — the agent declares it

With `teach_protocol=True` the agent is asked to report what it concluded, as a
structured side-effect of the turn it was already making:

```
<contextgc-state>
{"assert": {"destination_address": "Gate 2"},
 "pin":    {"dietary_allergy": "peanut"},
 "revoke": ["order_id"],
 "unsure": {"rider_location": "maybe the west gate"}}
</contextgc-state>
```

**No extra model call.** The block rides along in a completion the agent was
going to make anyway. It is not free, though: the instruction is ~200 tokens
added to the system prompt on every request, and in `compact` mode that
invalidates the prefix cache for the first message. Use `cache_friendly` if you
want both.

The block is stripped before the transcript is sent onward, including from inside
`tool_calls` arguments, so a model never sees protocol markup.

#### What the write path actually buys

| | Read path | Write path |
|---|---|---|
| Provenance | guessed | **declared**, and inference cannot overwrite it |
| Void facts | inexpressible | `revoke` — void, not merely stale |
| Unsettled facts | indistinguishable | `unsure`, surfaced and flagged |
| Pinned rules | hardcoded list | `pin`, lifted only by an explicit re-pin |
| Pronoun references | **not resolved** | **not resolved either** |

That last row is the honest one. The write path was motivated by coreference,
and it does **not** reliably fix it: the agent has to notice the reference and
report it. When it does, the result is authoritative; when it does not, the
state is quietly incomplete. There is currently no measurement of how often that
happens, which is the main open question about this feature.

#### Who may declare

**Only the assistant.** Tool output is a fetched page or an MCP result, user
text may be a pasted injection or a quote of this README, and a system message
is a summarised transcript that inherits whatever those contained. If any of
them could assert state, `declared` would be a mark of forgery rather than of
authority. Markup in an untrusted role is still stripped from the prompt, but
never applied, and is counted in `blocks_in_untrusted_roles`.

#### Read `conflicts`, not `declared_share`

```python
compiled, telemetry = compile_messages(messages, teach_protocol=True)
telemetry["declarations"]["declared_share"]   # provenance mix, NOT a score
telemetry["conflicts"]                        # declared vs. what the text says
```

`declared_share` is the fraction of tracked facts that came from the agent. It is
**not** a confidence measure, and it is specifically not a safety one: a declared
fact always outranks an inferred one, so the score goes *up* when the model's
opinion wins a disagreement. A transcript where the agent declared a stale value
and was never contradicted reads `1.0`.

`conflicts` is the signal that matters. It fires when the agent asserted a key
and the transcript's own text still says something different:

```
conflicts: [{'entity': 'gate_code', 'declared': '1111', 'declared_turn': 1,
             'inferred': '9999', 'inferred_turn': 2,
             'note': 'the declaration won; verify it is still correct'}]
```

Read that as: *the agent may be quoting an older turn; the human has since said
otherwise in plain text.* A model that keeps getting this wrong is not
declaring better, it is declaring more confidently than the evidence supports.

`rejected_writes` is the other one: writes the compiler refused — pinned keys,
lifted guardrails, markup from an untrusted role.

#### Cost and bounds

An agent that re-declares its entire state every turn is the most likely real
failure: every re-assert supersedes the last, so every declaring turn becomes
prunable and the compiler deletes the conversation. The register is therefore
capped at 64 facts and 512 characters per value; `state_keys_dropped_over_limit`
reports what was cut. When the register costs more than it saves,
`context_grew` and `token_growth` say so — `compression_ratio_pct` is clamped at
0 and would hide it.

---

## Measured against real agent transcripts

Everything above is a design claim. This is what happens when the compiler is run
over 40 real SWE-agent trajectories from
[`nebius/SWE-agent-trajectories`](https://huggingface.co/datasets/nebius/SWE-agent-trajectories)
— 1,936 turns, 2.26M characters, 20 repositories, real model output and real
tool output. The shard is repository-ordered, so the loader caps trajectories per
repository (`--per-repo`); without that cap the first 40 transcripts come from three
repositories and every number below inherits that narrowness.

```bash
pip install 'contextgc[bench]'
python -m benchmarks fetch          # 85 MB parquet shard
python -m benchmarks run --limit 40 --schema benchmarks/schemas/coding.json
```

```
CORPUS  swe-agent-trajectories
  transcripts      40
  turns            total 1390, median 32, range 12-92
  characters       1,958,156
  models           swe-agent-llama-70b x38, swe-agent-llama-8b x2

  facts_extracted            40   n=40
  keys_reasserted           187   n=40
  token_reduction          70.1%  n=40
  tool_payloads_compacted   668   n=40
  turns_retired              271   n=40
  retirement_violations       0   n=40
  compile_ms_p50            2.96  n=40
  compile_ms_p95           11.97  n=40

PRECISION (hand-labelled sample)
  labels supplied        36
  matched an extraction  36
  unclear                 1  (excluded from the ratio)
  JUDGED                 35   <- the denominator
    correct              35
    incorrect             0
  PRECISION (rows)       100%   (n=35)
  PRECISION (clusters)   100%   (n=35, 95% CI 90-100%)
  repositories covered  20
  unclear clusters        1  (excluded from the ratio)
```

Every count above is deterministic and reproduces exactly. The two `compile_ms`
figures are wall-clock on one machine and move run to run — treat them as "single
-digit milliseconds", not as a benchmark.

**The interval is the finding, not the point estimate.** 35 independent judgements
cannot distinguish 95% from 100%, and one repository contributes a handful of them.
This still catches gross regression; it is not a claim about unseen transcripts. The
labels and the loader settings that produced them are committed
(`benchmarks/labels/`), so the number can be regenerated and argued with.

### What this measurement changed

Running it was not a formality. It overturned five things.

**1. The default entity schema was producing confident nonsense.** The shipped
default was a logistics schema — `destination_address`, `refund_claim`,
`gate_code` — applied to everything. On 60 real coding transcripts it produced
75 facts, and every sampled one was prose matched by accident:

```
destination_address = "of parentheses"
destination_address = "it, otherwise do a lookup using type"
destination_address = "a placeholder dictionary"
```

The patterns were written to match a fixture, and a coding transcript is full of
the words they look for. **`ENTITY_PATTERNS` is now empty**, and a schema is
opt-in per domain. The old patterns are kept in
`benchmarks/schemas/logistics.json` with the measurement that condemns them.

**2. The sanitizer never fired on real data.** It keyed on a `TOOL_OUTPUT` marker
and on `role in (tool, function)`. In the corpus, **0% of messages carry that
marker** and tool output is filed under `user`. So 668 real tool outputs were
being passed through untouched. Detection is now content-based — a stack trace
is a stack trace whatever role it is filed under — and picks up 19.9% of
messages. Token reduction on the same corpus went from **17% to 58%**.

**3. Reading state out of tool output was a precision failure.** A file path in a
grep listing (`Found 14 matches for X in /path/to/dispatcher.py:`) is not a
statement about which file the agent is editing, but the pattern promoted it
anyway. State is no longer inferred from machine-generated output.

**4. Two more precision defects, found by the second labelling pass.**
A weak `in <path>` trigger matched prose — *"Upon reviewing `main.py` again …
`dispatcher.py` uses a helper"* became `current_file = dispatcher.py` — and a
single-letter `c` extension parsed `example.com` as `example.c`. Patterns now
require an explicit verb acting on the path, and a real path prefix. Both
defects were found by hand-labelling, not by the aggregate numbers.

**5. The precision sample was too small, too narrow, and partly fake.** The
first label set drew all 24 rows from **two** repositories, and several rows were
the *same turn* of the same issue read twice from two trajectories of that issue.
Counting those as independent evidence inflated the denominator. The corpus loader
made this worse: the shard is repository-ordered, so "the first 40 transcripts"
were 40 trajectories from **3** repositories, and every aggregate number
inherited that.

Both are fixed rather than caveated. The loader takes `--per-repo` (default 2), so
a run spans as many repositories as the shard allows — **20** for the same 40
transcripts. The label set was re-read from scratch, one extraction per
`(repository, turn)`, giving 35 independent judgements across 20 repositories. The
report now prints the row count *and* the clustered count, so a reader can see
when `n` is inflated, plus a 95% Wilson interval so a point estimate is not
mistaken for a measurement.

This changed the headline: the previous **88% (n=16)** was, on independent units,
**100% (n=35, 95% CI 90–100%)** from a far wider sample — and a naive re-run of
the old labels against the widened corpus collapsed to **n=2**, which is what
exposed the problem in the first place.

The 100% is not a claim that the tracker is perfect. Two confirmed errors survive,
and `--per-repo` structurally excludes the rows they came from (it takes the first
N trajectories per repository). They live in
`benchmarks/labels/known_failures.json` — same defect, a path named in one
sentence while the agent's subject is a different file in another — and a test
re-runs those exact rows and fails if they stop being wrong. That is deliberate:
the entry should be deleted on purpose, not vanish into a sampling change.

### What the corpus says the problem actually is

The measurable, high-frequency mutable entity in real coding transcripts is
**which file the agent is working on** — across 187 mentions,
with the agent moving between them and correcting itself:

> *"It seems that I attempted to edit the wrong file again. I need to edit the
> `memset.py` file instead of the `reproduce.py` file."*

That is precisely the last-write-wins case the library exists for, and 187 key
re-assertions fired across the 40 transcripts. `benchmarks/schemas/coding.json`
is derived from that observation, not from what would have been convenient.

The logistics scenario in the demo is not representative of coding work. This is
a domain-specific mechanism, and the corpus says which domain it actually
applies to.

### Is the write path worth it? Still unmeasured

`python -m benchmarks shadow` runs both paths and reports where they disagree.
It is deliberately incapable of making things worse: it never emits a declared
context, because a stale declaration silently outranks a human's plain-text
correction.

```bash
python -m benchmarks shadow --captures captures/run1.json --limit 50 \
    --schema benchmarks/schemas/coding.json
```

It needs a capture file: declarations recorded from a real run with a real model.
**No such capture exists yet**, and the command says so rather than inventing a
number. Until one does, the honest statement is that the write path is
unmeasured — and the corpus work above is what makes measuring it possible.

### What this harness refuses to do

- Print a percentage without the `N` it came from.
- Print a precision figure unless one was measured against hand labels.
- Call a declaration "correct" — it cannot know truth, only disagreement.
- Score itself. A compiler grading its own compression is the mistake this
  project was rewritten to remove.
- Report a synthetic corpus as evidence; a vendored slice of real trajectories is
  labelled with its real source.

---

## What it actually does

Four things, in order:

**1. Tracks asserted entity state, last-write-wins.**
When a key is re-asserted, the earlier assertion is marked superseded. When a
turn has been superseded for *every* fact it touched, it is retired from the
context.

**2. Never retires the evidence.**
If a turn is superseded for one key but is still the only support for another,
it **stays in the context**. Retiring it would hand the model a value with
nothing behind it. `get_retirement_violations(proposed)` checks a *proposed*
retirement set and reports any live fact that would be left unsupported.

An earlier version of this check compared the prunable set against the live set
and could therefore only ever return `[]` — it asserted an identity, not a
property, and the test suite "proving" it could not fail. The current test
asserts that the check *can* return a violation, which is the only way to know it
means anything.

**3. Compacts tool output without losing the safety bits.**
Bulk rows are sampled down. Any row carrying an allergen, severity, PII, recall,
or expiry signal is always retained, and the number of dropped rows is reported
explicitly (`truncated=true`).

**4. Pins caller-declared invariants.**
Rules you declare are inlined into the compiled context. There are no built-in
domain rules — shipping a hardcoded "refunds over ₹150" default once meant the
tool silently imported one demo scenario's business rules into every unrelated
session.

### Two modes

| `mode` | Behaviour | Use when |
|---|---|---|
| `compact` *(default)* | Retires superseded turns, inlines state at the head. | Minimising tokens |
| `cache_friendly` | Emits the input prefix **byte-identical**, appends the state register at the tail. Tool payloads are passed through verbatim. | A prefix/KV cache is keyed on the conversation prefix |

`cache_friendly` does not compact tool payloads, because doing so would mutate
the very prefix the cache is keyed on. The reported
`kv_cache_prefix_messages_preserved` is measured by diffing the emitted output
against the input — not inferred from the mode.

---

## Honest scope

This is the part that matters more than the feature list.

**It does not make models reliable.** It removes contradictions from the input.
It cannot add judgement, and it cannot stop a model ignoring a rule you pinned.
Nothing at the prompt level can guarantee compliance.

**The problem it solves is one of three.** "Context rot" is really three separate
failures, and only one is deterministic:

| Failure | Addressable here? |
|---|---|
| **Contradiction** — a stale assertion and its replacement both in context | **Yes.** One key, two bindings, a total order picks the winner. No semantics required. |
| **Irrelevance** — bulk tokens competing for probability mass | No. Needs a relevance judgement, i.e. a model. |
| **Position** — lost-in-the-middle attention decay | No. It is a property of softmax attention over sequence length. Preprocessing cannot fix it. |

**State tracking is regular expressions on the read path.** There is no
coreference resolution, so a fact expressed only through pronouns will not be
tracked. Missed extraction is the main failure mode: the state is *silently
incomplete*. The write path can supply those facts when the agent cooperates —
`conflicts` and `rejected_writes` tell you when it did not. Extend the schema for
your domain:

```python
from contextgc import StateDAG

dag = StateDAG()
dag.register_entity_schema("order_id", [r"order (?:id |number )?([A-Z]{3}-\d+)"])
```

**Token counts are `chars/4`, not a BPE tokenizer.** Read them as a ratio, not a
bill. Exact numbers need `tiktoken` against your real model.

**Retired-turn recall is lexical** — token, subword, and phrase overlap. Not
semantic. "What did we decide about billing?" will not find a turn that only
contains "invoice".

**Nothing here is benchmarked against real agent traces yet.** The website shows
measurements of *your* input. This README quotes no performance percentage,
because none has been established against an independent baseline.

---

## What was removed, and why

This project previously published numbers that its own code did not support. The
audit that prompted the rewrite is summarised here so the change is legible:

| Was | Reality |
|---|---|
| "40–47% faster inference" | A formula: `500 + raw*0.25` vs `400 + clean*0.15`. The coefficient ratio *was* the result. Nothing measured time-to-first-token. Removed. |
| "100% policy invariant compliance" | A regex auditor run against a sentence the server had just written itself, in a code path never used in production. Removed. |
| A benchmark "vanilla agent" | The baseline state was derived from this tool's own state tracker — the system computing its own counterfactual. Removed. |
| "768-dim vector recall, IVFFlat index" | SHA-256 hashes of words, plus a ClickHouse `DDL_SCHEMA` constant referenced nowhere in the codebase, behind a UI badge. The search was ~80% lexical. Renamed to `RetiredTurnArchive` and described accurately. |
| "sub-millisecond recall" | True only because the archive held six rows in a Python `for` loop. |
| Fabricated completions from `/v1/chat/completions` | With no API key the endpoint returned a valid-looking `chat.completion` with invented `usage` and no disclosure field, silently poisoning real integrations. It now returns **503**. |
| A public endpoint that forwarded caller `Authorization` headers and fell back to the operator's key | Anonymous visitors could spend the operator's money. Removed; the proxy now uses a server-side key only. |
| `allow_origins=["*"]` with `allow_credentials=True` | Replaced with an explicit `CONTEXTGC_ALLOWED_ORIGINS` allowlist. |
| Metrics disagreeing across six files (latency as 39.1/39.8/39.9/46.3/46.8%; tests as 16/27/28/31) | There is now no hardcoded metric anywhere. Every number in the UI is computed per request. |

### Bugs fixed

- **Retiring a turn did not retract the facts it uniquely asserted.** A turn
  superseded for one key could be removed from the prompt while a fact only it
  had asserted stayed in the state summary — the model received an authoritative
  value with no visible support. `get_orphaned_facts()` is the regression test.
- **The sanitizer could drop the safety row.** A 25-item catalogue was truncated
  to the first 3 items, discarding a `PEANUT_ALLERGEN` warning on item 15 — the
  exact signal the invariant guardrail depends on. Safety-relevant rows are now
  always retained and omissions are reported.
- **`cache_friendly` mode mutated the prefix it claimed to preserve.** Tool
  payloads were distilled before the mode was read. The flag was literally
  `mode == "cache_friendly"`.
- **Retired-turn recall was unreachable in the SDK path.** It read the archive
  before the loop that populated it, and the convenience function built a fresh
  engine on every call.
- **Unbounded memory growth.** Module-global engines accumulated archive rows
  across requests (6 → 12 → 18 → 24 → 30). State is now per-invocation.
- **Injection via recalled content.** Raw archived text was interpolated into a
  live user turn without escaping, so it could forge our own bracket delimiters.
- **Three entity patterns missed natural phrasings** — "a severe peanut allergy"
  (adjective-first), "set the gate code **to** 1111", and "change **the** address
  to". The peanut-allergy pattern only matched the inverted "allergy: peanuts"
  form the fixtures happened to use.

---

## API

Two surfaces, deliberately unequal in importance.

### `POST /api/compile` — the product

Stateless. No key, no model call, nothing persisted. 256 KiB body cap,
rate-limited, `Cache-Control: no-store`.

```bash
curl -X POST localhost:8000/api/compile \
  -H 'Content-Type: application/json' \
  -d '{"transcript":"user: deliver to Tower B\nuser: actually use Gate 2, code 4921",
       "mode":"compact",
       "invariants":["refunds over 500 need supervisor approval"]}'
```

Set `"teach_protocol": true` to inject the state-protocol instruction, and
`/api/example` returns a `write_path_example` that demonstrates it.

Accepts a plain-text transcript or a JSON message array:

```
user: deliver order ORD-1 to Tower B, Flat 402
tool [inventory]: {"items": [{"name": "Milk 1L", "price": 34}]}
assistant: confirmed, routing to Tower B
user: actually reroute to Gate 2. Code 4921.
```

Unparseable input returns **422** with per-line parser warnings rather than
silently dropping turns.

### `POST /v1/chat/completions` — optional proxy

An OpenAI-shaped pass-through that compiles the history, then forwards to a real
upstream. Requires a server-side `CONTEXTGC_UPSTREAM_KEY`.

**It refuses rather than fabricating.** A `503` means the operator has not
configured a key — it does not mean you received a model response. It never
accepts a caller's key.

| Variable | Default | Purpose |
|---|---|---|
| `CONTEXTGC_UPSTREAM_KEY` | *(unset)* | Enables the proxy. Absent ⇒ `/v1` returns 503. |
| `CONTEXTGC_UPSTREAM_BASE` | `https://api.openai.com/v1` | Upstream base URL |
| `CONTEXTGC_UPSTREAM_MODEL` | `gpt-4o-mini` | Default model |
| `CONTEXTGC_ALLOWED_ORIGINS` | *(empty)* | Comma-separated CORS allowlist. Empty ⇒ no CORS headers. |
| `CONTEXTGC_RATE_LIMIT` | `60` | Requests per minute per IP |

Responses carry `X-ContextGC-Telemetry: raw=…; compiled=…; saved=…%; compile_ms=…`.

---

## Development

```bash
git clone https://github.com/j4yop/context-hackdevengers
cd context-hackdevengers
pip install -e ".[dev]"
pytest -q                      # 194 tests
uvicorn server.main:app --reload
```

Zero runtime dependencies. `server/` and the test tooling are optional extras.

The test suite asserts the claims at tolerances tight enough to fail: the
`< 10ms` compile ceiling is enforced on a 60-turn transcript, growth is asserted
to stay roughly linear from 20 to 200 turns, a monkeypatched `socket` proves
nothing opens a network connection, and one test asserts that no fabricated
telemetry field (`latency`, `hallucination`, `estimated`, `risk_score`,
`embedding`, `ivfflat`) has crept back into the output.

## License

MIT — see [LICENSE](LICENSE).
