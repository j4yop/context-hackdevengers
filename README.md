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

## What it actually does

Four things, in order:

**1. Tracks asserted entity state, last-write-wins.**
When a key is re-asserted, the earlier assertion is marked superseded. When a
turn has been superseded for *every* fact it touched, it is retired from the
context.

**2. Never retires the evidence.**
If a turn is superseded for one key but is still the only support for another,
it **stays in the context**. Retiring it would hand the model a value with
nothing behind it. This is enforced by `get_orphaned_facts()`, which the test
suite asserts is always empty.

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

**State tracking is regular expressions.** There is no coreference resolution, so
a fact expressed only through pronouns ("send it to the new place instead") will
not be tracked. Missed extraction is the main failure mode: the state is
*silently incomplete*. Extend the schema for your domain:

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
pytest -q                      # 57 tests
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
