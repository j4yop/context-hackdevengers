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

> **Not on PyPI yet.** This line was here before the project had ever been
> published, which made it a lie in the most load-bearing spot in the README.
> Publishing is wired up (`.github/workflows/release.yml`, tag `v0.4.0`) and
> verifies the artifacts before uploading, but until a tag is pushed the
> install has to come from the repository:
>
> ```bash
> pip install git+https://github.com/j4yop/context-hackdevengers
> ```

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

**Two corpora, because one is not evidence of generalisation.**

| | coding | airline support | retail support |
|---|---|---|---|
| corpus | `nebius/SWE-agent-trajectories` | `APIGen-MT-5k` (airline) | `APIGen-MT-5k` (retail) |
| what it is | SWE-agent bug-fixing | reservation tool use | order / exchange tool use |
| sample | 40 transcripts, 20 repos | 60 conversations | 80 conversations |
| facts tracked | 39 | 72 | 47 |
| key re-assertions | 77 | 10 | 2 |
| token reduction | **66.5%** | **59.0%** | **62.5%** |
| turns retired | 161 | 9 | 2 |
| tool payloads compacted | 668 | 138 | 275 |
| retirement violations | 0 | 0 | 0 |
| contexts that grew | 0 | 0 | 0 |
| precision (independent units) | 100% (n=36, CI 90–100%) | 100% (n=72, CI 95–100%) | 100% (n=47, CI 92–100%) |

Run with `--corpus swe-agent`, or `--corpus apigen --domain airline|retail`.

**Reduction transfers. Supersession does not.** Coding re-asserts a key 77 times
across 40 transcripts; retail does it twice across 80. That is the honest limit of
this library: compaction of bulky tool output helps everywhere, but the
last-write-wins state register only earns its keep where a conversation keeps
changing its mind about one thing.

```bash
pip install 'contextgc[bench]'
python -m benchmarks fetch          # 85 MB parquet shard
python -m benchmarks run --limit 40 --schema contextgc/schemas/coding.json
```

```
CORPUS  swe-agent-trajectories
  transcripts      40
  turns            total 1390, median 32, range 12-92
  characters       1,958,156
  models           swe-agent-llama-70b x38, swe-agent-llama-8b x2

  facts_extracted            40   n=40
  keys_reasserted            77   n=40
  token_reduction          66.5%  n=40
  tool_payloads_compacted   668   n=40
  turns_retired              161   n=40
  retirement_violations       0   n=40
  compile_ms_p50            2.96  n=40
  compile_ms_p95           11.97  n=40

PRECISION (hand-labelled sample)
  labels supplied        39
  matched an extraction  39
  JUDGED                 39   <- the denominator
    correct              39
    incorrect             0
  PRECISION (rows)       100%   (n=39)
  n is inflated          39 rows collapse to 36 independent units
  PRECISION (clusters)   100%   (n=36, 95% CI 90-100%)
  repositories covered  20
```

Every count above is deterministic and reproduces exactly. The two `compile_ms`
figures are wall-clock on one machine and move run to run — treat them as "single
-digit milliseconds", not as a benchmark.

**The interval is the finding, not the point estimate.** 36 independent judgements
cannot distinguish 95% from 100%, and one repository contributes a handful of them.
This still catches gross regression; it is not a claim about unseen transcripts. The
labels and the loader settings that produced them are committed
(`benchmarks/labels/`), so the number can be regenerated and argued with.

### Using it in a loop

The library is a compiler plus a wrapper. The wrapper is the part you wire in,
and it is worth knowing that the state register is re-derived per call rather
than carried in memory -- so a multi-turn agent does not need a session object
to keep track of anything:

```python
from openai import OpenAI
from contextgc import load_schema, patch_openai

client = patch_openai(OpenAI(), schema=load_schema("coding"))
# every client.chat.completions.create(...) call now compiles first,
# and the response carries what it did as `.context_gc`
```

`tests/test_agent_loop.py` drives exactly this shape -- a growing history
through the real wrapper -- and asserts the property that matters: across 40
turns in which the agent moves between ten files and contradicts itself, the
register always names the file the previous turn announced, never two at once,
and no retirement ever strands a value. The same file also checks that a
declaration arriving in a user or tool turn is stripped rather than believed.

### When it does *not* help

Two behaviours worth knowing before you point this at a live agent. Both are
deliberate; neither was documented until they were measured.

**The last two turns are never retired.** A correction that arrives immediately
after the wrong claim leaves both turns in place, because the trailing turns are
the model's most recent exchange and cutting them would strip the reply it is
about to continue. So a short session can hold a visible contradiction and still
report `retired_turn_count: 0`; there, the state register is what resolves it.

```python
# adjacent: nothing retired, but the register states the current value
H + [asst("editing `wrong.py`."), asst("actually editing `right.py`.")]
#   -> retired 0, register says current_file = "right.py"

# one turn between them: the wrong claim is gone
H + [asst("editing `wrong.py`."), user("ok"), asst("actually editing `right.py`.")]
#   -> retired 1, "editing `wrong.py`" no longer reaches the model
```

**A short session can cost more than it saves.** The state register is a fixed
header plus one line per slot. On a 7-turn transcript the compiled output is
*larger* than the input, and the telemetry says so rather than rounding it away:
`compression_ratio_pct: 0.0`, `context_grew: True`. The 70% figure comes from
40 real transcripts averaging 48 turns. If your sessions are shorter than that,
measure before you adopt this.

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
`contextgc/schemas/logistics.json` with the measurement that condemns them.

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

**6. A repeat was being treated as a contradiction.** There was no value
comparison at all: any new extraction for a live entity superseded the previous
one. An agent that said `**Cabin Class:** Business` and then `business class` had
not changed its mind, yet the earlier turn was retired as superseded — taking
whatever else it carried with it. A repeat is now a reaffirmation, and a value
that differs only in case is recorded as one rather than acted on. Genuinely
different values supersede as before.

This one is worth stating plainly because it changed the headline. Fixing it
removed phantom supersession that had been inflating every figure: coding
re-assertions fell from 187 to 77 and retirements from 271 to 161, and travel
retirements from 58 to 9. The numbers above are the corrected ones. The earlier
figures were not wrong arithmetic — they were measuring repeats as changes.

**7. A schema-free extractor survived the rewrite.** Behind the registered
patterns sat a generic `set <key> to <value>` scraper and a harvester that turned
any `{"k": "v"}` in any turn into a `slot_k` fact. Both contradicted claims this
README makes: that the default schema is empty *because* a default matching
everything produces confident nonsense, and that state is never inferred from
machine output. The JSON harvester's only guard was `role not in ("tool",
"system")`, and every corpus measured here files tool results under `user`. It
was found by extracting `slot_symbol = "€"` out of `currency = {"symbol": "€"}`.
One extraction in 40 transcripts, so removing it barely moved any aggregate —
which is exactly why it survived: the numbers never showed it.

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
`(repository, turn)` — 39 rows, which collapse to 36 independent units, across 20
repositories. The
report now prints the row count *and* the clustered count, so a reader can see
when `n` is inflated, plus a 95% Wilson interval so a point estimate is not
mistaken for a measurement.

This changed the headline: the previous **88% (n=16)** was, on independent units,
**100% (n=36, 95% CI 90–100%)** from a far wider sample — and a naive re-run of
the old labels against the widened corpus collapsed to **n=2**, which is what
exposed the problem in the first place. It then had to be re-read a second time,
because fixing the repeat bug in defect 6 changed what the compiler extracts.

The 100% is not a claim that the tracker is perfect. It is 100% of what was
labelled, and labelling is the bottleneck. Concretely, the limit is that **all 39
labels are one slot**: precision is currently a statement about the
`current_file` regex and nothing else. (`coding.failing_test` cannot be measured
at all — it has 0 speech observations, so the read path never produces it.)

#### A ground truth that is not a person: the booking database

Every airline tool result in the corpus is the environment's own record of a
reservation — `{"reservation_id": "0U4NPP", "origin": "PHL", "cabin": "economy",
"flights": [{"flight_number": "HAT076", "date": "2024-05-09", ...}]}`. That is
ground truth for exactly the slots the travel schema tracks, and it is already in
the conversation.

It is worth being precise about why using it is legitimate when the read path
refuses to. The library must not *infer* state from a machine payload — a booking
record is a database dump, not a statement of what the customer wants. Scoring
against it is the opposite operation: the payload is the answer key, held aside
from the system under test. Refusing to read the key and refusing to score
against the key would be one and the same mistake.

`python -m benchmarks.ground_truth travel --limit 200` puts an extraction in one
of three buckets, and reports them apart:

| | count | share |
|---|---|---|
| corroborated by the record | 557 | 90.6% |
| **contradicted by the record** | **5** | **0.8%** |
| unverifiable (no record for that slot) | 53 | 8.6% |

The rate is over corroborated + contradicted. The unverifiable column is **not** a
pass — it is extractions this check says nothing about, and folding it in would
flatter the number.

**This is a different measurement from the hand-labelled one, and it is not
interchangeable with it.** It asks "is this value consistent with what the
environment recorded", not "did a person read the turn and judge it true". It is
stricter in one way, because the record is authoritative rather than a reader's
impression, and looser in another, because it cannot see whether the customer had
*moved on* by that turn. It scores a real but out-of-date value as correct — the
same limitation that sank the staleness attempt.

It also found two defects that 39 single-slot hand labels had not:

- **`abella_anderson_9682`.** The `passenger_id` pattern's optional verb
  `(?:is|:)?` matched the leading `is` of the *name*, so the read path produced a
  corrupted user id that passed every key-level check. 15 occurrences in the
  corpus, and the mechanical worksheet suggestion read `correct` on all of them,
  because the string is in the turn. It now needs a word boundary after the verb.
- **`cabin_class = "first"`.** "rescheduling my return flight to **the first**
  one-stop option" matched `to\s+(?:the\s+)?(first)` and recorded a First Class
  cabin. The database holds only `economy`, `business` and `basic_economy` across
  3,030 records and never `first`. This is row 051 of the worksheet, where the
  suggestion again said `correct`.

**What is left, honestly.** 4 of the 5 remaining contradictions are
`cabin_class`, and they are the residue of three fixes that were **measured
rather than reasoned about**. Two were tried and reverted because they were worse:

| attempt | effect |
|---|---|
| require the mention near "your" / "you are flying" | lost 50 of 122 corroborated to fix 4 of 6 |
| take the **last** mention in a turn as the conclusion | contradictions 6 → **10** |
| treat 2+ distinct cabins in a turn as an enumeration | lost 16 of 122 corroborated to fix 3 of 6 |
| **negative lookahead for policy framing** | contradictions 7 → **5**, coverage unchanged |

That last one is the keeper: "basic economy **flights cannot be modified**" is a
rule about the category, not the passenger's cabin. It removes 69 of 1,361
`basic economy` matches, and reading all 69 found every one is a policy statement
with no genuine mention among them — which is why it cost nothing in coverage
while the other three cost a lot.

The last-wins result is the instructive one. Taking the final mention as the
turn's conclusion is intuitively right — an agent lists categories, then states
the answer — and it made things worse, because agents state the current cabin and
*then* offer an upgrade: "you are in economy, would you like business?" First-wins
happens to suit this corpus, and the reason is a property of airline
conversations rather than a principle.

The 4 that remain are two turns where the correct value is also present and the
wrong one was picked, one hypothetical ("would two separate bookings work, one in
economy and one in business?"), and **one genuine agent-versus-record
disagreement** where the agent says Economy, the record says `basic_economy`, and
the read path faithfully recorded what the agent said. That last one is not a
pattern bug at all, and it is the most interesting row in the table.

#### Making labelling cheap enough to stop being the bottleneck

`python -m benchmarks.label_worksheet travel --limit 200 --per-entity 12` writes
a worksheet a human can fill in, and
`python -m benchmarks.label_worksheet travel --merge <file>` folds the judged
rows into the committed label file. Three things it does that hand-picking does
not:

- **It spreads the budget across slots.** Sampling "the extractions" reproduces
  the existing shape, because `current_file` is the easiest slot to sample and
  the others are not. The worksheet samples round-robin, so 12 per slot is 12
  per slot — 80 rows across all seven travel slots, of which 60 are for the five
  slots that have **no labels at all**.
- **It quotes the registering turn and its neighbours.** Both "confirmed errors"
  this project once carried were mislabelled by someone reading a value without
  the sentence that said the agent had moved on. The quote is the fix, and the
  merge refuses a row that does not carry one.
- **It will not invent a verdict.** Every row ships `unlabelled`, and the merge
  exits while any row is unlabelled, so a precision number can never acquire a
  denominator nobody judged. Rows are de-duplicated by value and by transcript
  first, because inflating `n` with repeats was this project's first precision
  bug.

`--suggest` additionally attaches a **mechanical suggestion** to each row — a
text check, with its evidence recorded (is the value in the registering turn, what
role is that turn, did the sanitizer call it machine output). It is not a
judgement and it cannot become one: `verdict` stays `unlabelled`, the merge exits
while anything is unlabelled and says so explicitly, and a suggestion that was on
offer is recorded *as offered* on the committed label so a later reader can see the
reviewer was not working blind. Its own limitation is stated on every row: the
"confirmed errors" this project once carried were all cases where the value *was*
in the turn and the judgement was still wrong, because the agent had already moved
on. A string check cannot see that.

The committed label file is the only thing that produces a number. The worksheet
carries none until a person fills it in.

#### One precision question the labels structurally cannot answer

All 39 labels are `current_file`, and every one judges a value at the turn it was
*registered*. That design cannot see the failure a fact tracker is actually
judged on: whether it followed the agent afterwards. If the tracker says
`current_file = memset.py` on turn 51 and the agent is editing `cli.py` on turn
52, the value was true when written and wrong by the next turn — and every hand
label on turn 51 still reads "correct".

So there is a second, mechanical precision question, and it was attempted and
**does not survive contact with the corpus**. `python -m benchmarks.staleness`
keeps the attempt and the reason:

- The action signal has to be an **edit**, because reading a file is not editing
  it. Taking any file named against a command gives 28.6% support, and reports a
  44.9% disagreement rate. Reading the turns shows most of it is the agent
  opening a file to diagnose an import error, or running a script to verify a
  fix, while the tracker correctly holds the file it is working on. `open
  lexicon/config.py` is a read; `python reproduce.py` is a run.
- An **edit-only** signal is correct and rare: explicit edit markers appear in
  1.7% of agent turns and in-place `sed -i` writes in 0.0%. On 60 transcripts
  that leaves 69 comparable transitions — and **25 of the 31 disagreements come
  from a single transcript**, an agent ping-ponging between `api.py` and
  `common_types.py`. Drop it and the rate falls from 44.9% to 14.3%.

**So no staleness figure is quoted anywhere.** A rate that one transcript moves
by 30 points is that transcript's behaviour, not the tracker's, and the tool now
reports the concentration instead of the average rather than letting a
convenient number through. The honest position is that this dimension is
currently unmeasured: it needs either a corpus where agents announce their edits
in a parseable way, or a human reading pairs of turns. The read path's refusal
to infer from tool output is a large part of why — it holds no value on the
`user` turn preceding an agent action, so the comparison has to be between
consecutive agent actions, which is a definition chosen here and not given by
the data.

**The two "confirmed errors" this project carried were mislabelled.** Both were
recorded as `current_file` extractions judged incorrect because the turn's earlier
prose discussed a different file. Re-reading the turns against the doctrine the
labels themselves state — *"agent opens/edits/creates or restates this exact
value"* — shows the opposite. At each turn the agent says it is navigating to
`dispatcher.py`, emits

```
open azure_functions_worker/dispatcher.py
```

and **the very next turn is the tool result confirming the open happened**:
`[File: .../dispatcher.py (717 lines total)]`. By the doctrine, both extractions
are correct. The label judged the turn by the file its prose discussed; the
doctrine asks what the agent *did*, and the next turn answers that.

This mattered beyond tidying, because it is also the answer to why a proposed fix
had to be abandoned. Stripping fenced blocks before pattern matching — treating a
shown command as a quotation rather than an action — cost **48% of the measured
supersession signal** (77 → 40 re-assertions). In this corpus a fenced command
in an assistant turn *is* the action, not a hypothetical, and the measurement was
right to stop that change.

`benchmarks/labels/known_failures.json` is now empty, with the correction
recorded beside it. Neither file is the right home for the two cases: they are
not errors, and they sit in rows `--per-repo 2` skips, so adding them to
`precision.json` would trip the label-drift check — the same check that caught 20
of 24 labels matching nothing when it was written. The file and its tests stay,
so the first real error is checkable from the moment it is recorded.

### What the corpus says the problem actually is

The measurable, high-frequency mutable entity in real coding transcripts is
**which file the agent is working on** — across 77 re-assertions,
with the agent moving between them and correcting itself:

> *"It seems that I attempted to edit the wrong file again. I need to edit the
> `memset.py` file instead of the `reproduce.py` file."*

That is precisely the last-write-wins case the library exists for, and 77 key
re-assertions fired across the 40 transcripts. `contextgc/schemas/coding.json`
is derived from that observation, not from what would have been convenient.

The logistics scenario in the demo is not representative of coding work. This is
a domain-specific mechanism, and the corpus says which domain it actually
applies to.

### Retail: the original sin, measured at scale

`contextgc/schemas/logistics.json` used to be the library's *default*. On 80 real
retail conversations it extracted 46 facts, and **every one read in context was
wrong**:

```
destination_address = "perfectly suit my needs"
destination_address = "for any price difference"
destination_address = "my existing PayPal account"
destination_address = "the Visa card ending in 2364"
```

The `use` trigger is the cause: in a retail conversation "use" is nearly always
about money. The original evidence for emptying the default schema was three
examples on 60 *coding* transcripts; this is the same defect at scale, on data
that is actually the domain the schema was written for. The patterns are kept at
`benchmarks/schemas/condemned/logistics-original.json`, and a nightly job asserts
they still fail, so a future reader can reproduce the claim rather than take it
on trust.

The replacement was derived by measuring 400 retail conversations, and **the
result is mostly negative**:

| entity | spoken | machine output | machine share | supersedes |
|---|---|---|---|---|
| `delivery_address` | 51 | 1,048 | 95% | 15% (26 convs) |
| `payment_method` | 141 | 3,701 | 86% | 1% |
| `order_id` | 625 | 2,340 | 79% | 5% |
| `refund_amount` | 2,280 | — | — | 93% |

`refund_amount` is deliberately **absent** despite being the most-mentioned
quantity in the data. It "changes" in 93% of conversations because a retail
conversation contains many different dollar amounts — item prices, totals, price
differences — not because one is being corrected. Putting them in a single
last-write-wins slot would be the same error as modelling origin and destination
as one airport code, and the same error as the schema it replaces. A slot that
changes constantly because it means several things at once tracks nothing.

So retail ships two slots, and the supersession rate stays in the schema file
where it cannot be quietly forgotten.

### What the compactor actually covers

"It compacted 668 payloads" says nothing about *which* payloads. Measuring every
shape in the three corpora:

| payload shape | n | share of JSON bytes | saved | compacted |
|---|---|---|---|---|
| dict wrapping records under any key | 370 | **84%** | 56% | yes |
| a tool **call** | 507 | 14% | 0% | no, by design |
| a lookup map of strings | 8 | **2.5%** | 0% | no — see below |
| text listings, test output, stack traces | — | — | 36–93% | yes |

Counted over 60 airline + 80 retail conversations. The coding corpus contains
**no JSON payloads at all** (2,976 candidates, none parse), so its compaction
figure comes entirely from the non-JSON shapes above.

**The uncovered shapes are 2.5% of the bytes, and that is deliberate.** A
lookup map of strings — a product catalogue, a currency table — has no repeated
fields, so there is genuinely nothing to summarise; the only way to shrink one is
to drop entries, and a model that needed the catalogue would then be reasoning
from a truncated one. Trading 2.5% of JSON payload bytes, about 0.4% of tokens,
for silently discarding lookup data is the wrong side of this project's own
rule. Earlier revisions of this table listed "dict wrapping a map of strings" as
an uncovered *shape*; measuring it showed the 507 instances of that shape in the
corpora are all tool calls, which are deliberately untouched, and the genuine
case is 8 payloads.

Two things that table changed.

**The dict branch guessed key names.** It looked for a list under one of eight
hardcoded keys — `items`, `products`, `records`, `data` and so on — and fell
through to a flat distillation for anything else. The airline payloads wrap their
flights under `flights` and their search results under `results`; neither is on
the list. So **18% of airline and 27% of retail payloads went uncompressed for no
reason other than the spelling of a key.** It now finds the largest collection
under any key. Guessing key names is a list of tomorrow's bugs.

**A tool call is not tool output.** A `function_call` turn is the agent stating
what it did, and compressing its `arguments` would obscure the action rather than
the output it describes. That is exempt however large it is.

Corrected on the corpora: airline +10.3% and retail +18.9% of payload characters
saved, coding unchanged because its payloads are text and the JSON branch
correctly never fires.

### What the second domain settled about the write path

A capture now exists (see below), so the write path is no longer unmeasured. But
the second domain answers the question that motivated it, and the answer is not
subtle. In customer-service transcripts, **82–99% of every mutable entity's
mentions live in tool output**, not in speech:

| entity | in speech | in machine output | machine share |
|---|---|---|---|
| `reservation_id` | 610 | 2,922 | **83%** |
| `airport` | 1,060 | 4,768 | **82%** |
| `payment_method` | 18 | 1,395 | **99%** |
| `cabin_class` | 271 | 96 | 26% |

The read path is forbidden to infer state from machine output — a grep listing is
not a statement about intent, and that rule was measured on the coding corpus. So
a pattern-based tracker structurally *cannot* see reservation ids or payment
methods here. That is a property of tool-heavy domains, not a defect in the
tracker, and it remains the strongest argument for the write path that this project
has produced: the agent knows those values, and only the agent can say them.

The caveat is now a measurement rather than a hope. A model that *can* state those
values still has to state them correctly: the coding capture below shows a model
filling 19 slots with invented keys, none of them schema fields. An agent that
declares a `payment_method` wrongly is worse than an agent that declares nothing,
because the compiler will treat it as authoritative. Making declarations earn their
place in the schema is a prerequisite for the travel case, not a detail.

What is left reachable is cabin class, which is spoken often and changes in 41% of
conversations.

#### What the corpus could actually reach, and what it cost

The first capture on this domain was refused by `benchmarks capture --verify`: only
**7 of 19** declared keys (37%) named a slot the two-slot travel schema defined.
Not because the model was wrong — an airline conversation is about
`flight_number`, `origin`, `destination`, `flight_date` and `passenger_id`, and
the schema had no pattern for any of them, so the read path could not corroborate
what the model said. The fix is to derive those slots from the corpus, **not**
from the model's output, which would be fitting the schema to the metric.

Five slots were added, each fitted to the APIGen airline corpus and each carrying
its own observation count. Two precision defects surfaced in the process, both
found by measuring rather than by reading:

- An airport pattern written as `to ([A-Z]{3})` is compiled case-insensitively, so
  **"to the" was read as the airport `the`**, and the slot produced 52 distinct
  values where the corpus has 20 IATA codes. This is the same defect the schema
  already documents for reservation ids, so the fix is the same: scope the class
  case-sensitively with `(?-i:...)`.
- `passenger_id` written as a bare `name_name_1234` token fired **543 times
  inside tool output**, contradicting this schema's own rule that a pattern must
  require a phrasing and never a bare token. It survived only because the
  sanitizer happened to catch those messages.

A third defect was pre-existing and is described next, because it is the more
interesting one: an agent's *options menu* was becoming state.

#### An options menu is a listing, and a listing is not a booking

The shipped `cabin_class` pattern has `(?<!Seats: )` and `(?<!Prices: )`
lookbehinds, added when a turn listed every cabin with its price and the pattern
took `Basic Economy` off the price list as the passenger's cabin. Those guards
cover one layout. The airline corpus also writes `Price: $142` and
`**Flight 1:**`, and across 134 menu-shaped agent turns the shipped schema leaked
**905 extractions**; the new slots would have added about 1,470 more.

The obvious fix — a content-based "this is a listing" guard — was measured and
rejected. A content-only guard **deletes the single most important turn in the
corpus**: 2 customer turns contain option-menu markers and both are a booking,
including "Let's go with Option 1: Flight HAT148 from Miami to Denver". The same
strings in an agent turn mean it is listing what it could offer, and nothing in
the content tells the two apart.

So the guard is conditioned on the role, in `ToolSanitizer.looks_like_option_menu`:
only an *assistant* turn can be an agent listing its own options, so a customer
turn is never claimed. Measured on the airline corpus that suppresses 440 of 6,538
agent turns (6.7%) and **0** customer turns. An options menu is a listing in
exactly the sense a search listing is — "flights from DFW to SEA are available"
does not mean the passenger is flying DFW to SEA — and what the menu *does* support,
that these routes exist, is not what this library tracks.

#### A birthdate read as a flight date, found by a disagreement

The shadow replay's single disagreement on the airline capture was the read path
producing `August 10, 1995` against a declared `2024-05-07T13:04:42`. The read
path was right about the disagreement existing and wrong about the value: it had
matched a passenger's *date of birth*. No aggregate had shown this. A bare
month-name date pattern matched 1,494 dates of which 93 (6.2%) were birthdates.

Requiring flight context, plus a lookbehind for "born", took that to 11 hits whose
matched date was a genuine flight date with a birthdate nearby — and dropped the
slot from 82 distinct values to 32, while keeping 1,636 observations. Filtering
on the year would have been easier and wrong: it fits the corpus's fixed "current
time" rather than the slot's meaning. After the fix the replay reports 0 changed
keys and 16 agreements.

The travel schema is now 7 slots, 18,800 read-path observations.

#### The second capture, on the airline corpus

With the corpus-derived slots in place, the same model on the same domain
(`qwen2.5:14b`, 6 transcripts, 36 turns) goes from **37%** of declared keys
naming a schema slot to **76%** — 80 of 105. Every turn declared, and the six
off-schema keys it invents are genuine airline entities the schema still does not
cover (`total_baggages`, `nonfree_baggages`, `passenger_check_in_status`).

Two numbers here are worse than on the coding corpus, and both are findings rather
than noise:

- **6 of 36 blocks do not parse as JSON**, so `capture --verify` still refuses
  this capture. On the coding corpus it was 0 of 42. Malformed output is worse in
  a domain with longer, more structured turns.
- **16 of 37 shadow additions are off-schema**, so nothing can say whether any of
  them is true. That fraction is the same problem as before, smaller.

### Measuring the write path, when there is a model

`benchmarks shadow` replays captured declarations. Producing a capture needs a real
model, and one will not be invented here — a synthetic declaration set would
measure the harness rather than the write path. There is one committed capture at
`captures/run1.json`, and these are the commands that produced the numbers below:

```bash
# any OpenAI-compatible endpoint; a local ollama works and needs no key
export CONTEXTGC_CAPTURE_BASE_URL=http://localhost:11434/v1
export CONTEXTGC_CAPTURE_MODEL=qwen2.5:7b
python -m benchmarks capture --transcript benchmarks/corpus/sample.txt \
    --out captures/run1.json --limit 6 --schema coding
python -m benchmarks capture --verify --out captures/run1.json
python -m benchmarks shadow --corpus synthetic \
    --corpus-path benchmarks/corpus/sample.txt \
    --captures captures/run1.json --schema contextgc/schemas/coding.json
```

Note `--corpus-path` on the shadow run. Capture and replay must come from the same
corpus under the same id scheme; pointing shadow at the downloaded `--corpus
swe-agent` shard instead would replay nothing while printing a clean comparison,
so it refuses instead.

The endpoint is read from the environment rather than an argument, so a key cannot
land in a shell history or a CI log. `capture --verify` refuses a capture that
recorded no declarations, one that does not say which endpoint produced it — a
capture that cannot be attributed is an anecdote — and one whose declarations name
a schema slot less than half the time.

Capture is resumable and checkpoints after every turn, because a local server that
drops on the fortieth of forty-two calls should cost one call. A capture records a
fingerprint of everything that shapes its prompt, so a re-run after a prompt change
starts fresh rather than quietly mixing two experiments into one file.

### Is the write path worth it? Measured, and the answer is no

There is now a capture, made by a real model against a real trajectory file, and it
is committed at `captures/run1.json` so the comparison replays without a GPU. Two
more sit beside it: the 7B run before the instruction fix, and the same run after
it, because that pair is the evidence for the bug below rather than for the write
path.

```bash
python -m benchmarks capture --verify --out captures/run1.json
python -m benchmarks shadow --corpus synthetic \
    --corpus-path benchmarks/corpus/sample.txt \
    --captures captures/run1.json --schema contextgc/schemas/coding.json
```

| | |
|---|---|
| model | `qwen2.5:14b` (Q4_K_M), local, via ollama |
| transcripts | 6 real SWE-agent trajectories, 42 assistant turns |
| turns where the model emitted a state block | 42 / 42 (**100%**) |
| blocks that were not valid JSON | **0** |
| declared keys naming a schema slot | 53 / 55 (**96%**) |
| **keys the declaration added** | **9** |
| — of those, in the schema | **7** |
| — of those, outside it | 2 |
| **keys the declaration changed** | **4** |
| keys the declaration agreed with | 1 |

The first run of this used `qwen2.5:7b` and produced 34% in-schema, 19 off-schema
additions and no verified information at all. That number was a bug in the
instruction, not a property of the model — see below. Both captures are kept.

**Every one of the 19 added keys was outside the schema.** Not one was a
`current_file` or a `failing_test`. The 4 agreements were all `current_file`, and
the declaration never once corrected the read path.

That `19` used to be the headline, and it was the wrong number to lead with. It
counted `key`, `value`, `auth_token`, `line_144` and `headers_set` as recovered
facts. Shadow mode now splits it, and the split is the finding:

```
  keys added      19
      in schema    0   (the read path had patterns for these and still missed them)
      off schema   19   (nothing could corroborate these)
```

The write path's real contribution, at this model size, was confirming four facts
the read path had already found, and inventing nineteen keys nobody asked for —
including `key` and `value`, which are the literal placeholders from the format
example in the instruction, copied through as if they were entity names.

The read path found `current_file` in 5 of the 6 transcripts by pattern. The model
declared it 12 times, and the two agreed 4 times. In no transcript did the
declaration supply a `current_file` the read path had missed. **Net verified
information from the write path: zero.**

#### What this does and does not say

This is a measurement of *a 7B model's ability to use the protocol*, and it is
separable from the protocol's design in one direction only. Two things bound it:

- **It is a lower bound.** In the capture the model is a bystander inferring what
  an *observed* assistant turn changed. In real use the agent emits the block
  inline, with direct knowledge of its own actions. That is an easier task, and
  this number does not predict it.
- **It is one model.** A frontier model would very likely behave differently. The
  claim is not "declarations do not work"; it is "declarations from a 7B model do
  not survive contact with a real trajectory."

What the result established, without any model-size caveat, is that the ingestion
path accepted out-of-schema keys without complaint. The 19 junk keys were not
filtered, not flagged and not counted as a problem — they were `added`, which is
the metric that flatters the write path.

#### A second model, and a bug the first one was blaming

`qwen2.5:14b` was captured on the same six trajectories, and the first
comparison said the 34% in-schema rate was not a model-size artifact — 14b
scored 40%. That reading was wrong, and finding out why mattered more than the
number.

`teach_protocol` built the protocol instruction from `sorted(self.dag.active_state)`
— the keys **already in state**. On turn 1 nothing is in state, so a model
running the `coding` schema was told that schema had **no keys at all**, and fell
back to the format example's placeholders. Both models had been copying
`{"key":"value"}` out of the instruction as if `key` and `value` were entity
names. The schema is the definition of which keys exist; telling the model about
it is not hinting it toward an answer, it is the one thing it cannot infer.

Fixed, and re-measured on the same trajectories:

| | 7b before | 7b after | 14b after |
|---|---|---|---|
| compliance | 90% | 93% | **100%** |
| malformed blocks | 7 | 4 | **0** |
| declared keys | 29 | 39 | 55 |
| keys naming a schema slot | 10 | 34 | **53** |
| **in-schema share** | 34% | **87%** | **96%** |

So the vocabulary bug was the dominant factor and the model size a real but
smaller increment on top of it.

#### Why the ratio is not the answer

96% in-schema looks like a working write path. Adjudicating what it actually
produced says otherwise.

| 14b, shadow replay | count |
|---|---|
| keys added, in schema | 7 |
| keys changed (disagreed with the read path) | 4 |
| keys agreed | 1 |
| keys added, off schema | 2 |

**Every one of the 7 in-schema additions is a value of the wrong shape.** Three
are the literal string `None`. The rest are error messages and a method name
placed in `failing_test`, whose patterns are supposed to yield a test
identifier: `HTTPError: 403 Forbidden`, `SyntaxError: '(' was never closed`,
`mocking_memset_api_response`. The model stopped inventing *keys* and started
inventing *values shaped to look like keys*.

And one of the 4 changes is a genuine regression. In transcript 5 the agent
worked through `memset.py` and had moved on to `cli.py`; the read path's final
`current_file` is `lexicon/cli.py`, and the declaration moved it **back** to
`lexicon/lexicon/providers/memset.py`. Sending the model a file the agent has
already left is precisely the failure this project exists to prevent. The other
three are benign — the read path says `memset.py`, the declaration says the full
path, and both name the same file.

**Net verified information from the write path: still zero.** For a different,
and more insidious, reason than before. The first failure mode was caught by
asking whether the key was in the schema. The second passes that check, which is
why an in-schema ratio is necessary and not sufficient.

#### The gate that follows from it: value shape

A key check is necessary and not sufficient, and the second capture proved it by
sitting exactly on the boundary: 96% of declared keys named a real slot, and the
values were still wrong. So a schema may now state what a *declared* value for
each slot may look like.

The first contracts were written by hand from the values one capture happened to
produce, and that was a guess wearing a measurement's clothes. They are now
**derived from the schema's own entity patterns**, by
`contextgc/value_shapes.py`. The patterns were fitted to a corpus, so their
alternations *are* that corpus's vocabulary; reusing them substitutes a
measurement for a guess:

```json
"values": {
  "current_file": "(?:[\\w][\\w./-]*\\.(?:py|js|ts|tsx|jsx|go|rs|java|rb|cpp|hpp))",
  "failing_test": "(?:(?<![A-Za-z0-9])test_[\\w./\\[\\]-]+)"
}
```

Deriving them mattered more than the hand-written versions looked. The old
`logistics.delivery_address` was `[\w\s.,'/-]+` and `payment_method` was
`[\w ]+`, so on a 48-value set of wrong-shaped declarations — `None`, error
messages, `memset.py`, a bare `1234567` — the hand-written contracts accepted
**34 of 48** and the derived ones accept **0 of 48**. Every one of the **7,929**
distinct values the read path has actually produced across the three shipped
schemas is still accepted, so the tightening cost nothing in coverage.

Two bugs in the derivation were found only by running it, not by reading it, and
both are now pinned by tests in `tests/test_value_shapes.py`:

- The first version read `basic economy` — 14 of 42 observations, the most
  common value in `cabin_class` — as a structural pattern and dropped it. A
  contract that rejects the commonest value in its own slot is worse than none.
- The first version anchored `test_` to a separator and rejected 2 of 126 real
  values, because `base_test_test.py` and `tests.test_flask_pyoidc` put an
  underscore or a dot in front of `test_`. The boundary is "not preceded by an
  alphanumeric".

One false accept is left and recorded rather than fitted away: `failing_test`
still accepts `my_test_helper.py`, since a helper module's name contains `test_`
and telling it from a test would need more than the pattern carries. It is
written into the schema's `_measurement` so the limit is visible.

`value_policy` then behaves like `declaration_policy`: `flag` keeps the value and
reports it, `reject` drops it, `off` disables the check. A slot with no contract
is not gated — absence is not permission to guess.

Contracts are stored in the schema file, where a reviewer can read them, and a
test fails if an entity pattern is edited without re-deriving, so the two cannot
drift apart.

Two further properties were forced by measurement rather than chosen:

- **Contracts are never applied to the read path's own values**, which come out
  of the slot's pattern by construction, so gating them would be circular. A test
  runs every contract over the corpora's extractions and fails the build on any
  wrong rejection. It earned its place immediately: a case-sensitive contract
  rejected **3 of 111** travel extractions the tracker produced itself, including
  `cabin_class = "Business"`.
- **The match is a search, not a full match, and is case-insensitive.** A strict
  match rejects a leading `/` on an absolute path and pytest's `::` separator.

Measured on the canonical 14B capture: **47** declared string values, **45** of
them in slots that have a contract. **16** are of the wrong shape and are
reported; 29 pass. All 16 are `failing_test` values — the 14B model never once
produced a plausible test identifier in this capture, only error text and shell
commands. The remaining 2 declarations are in `auth_token` and `credentials`,
which are not schema slots and so are not gated.

**This does not make the write path proven.** It removes a failure mode that was
previously invisible, and the same standard applies to it as to the key gate: a
value that satisfies its contract can still be wrong. A future model could
satisfy the contract with a *plausible but wrong* test identifier, and nothing
here would catch that. Treat the write path as unproven rather than as working
until truth is checked against labels.

#### The prompt was wrong before it was measured

The first capture of this run scored 55% compliance. That was not the model. The
harness was handing the model the protocol twice — once as a hand-built system
message and once via `teach_protocol=True` — 801 bytes of duplication per turn.
Four of the nineteen non-compliant replies were the model faithfully echoing the
duplicated `[STATE_PROTOCOL]` wrapper back.

`--legacy-prompt` reproduces that defect on demand, so the comparison below is
measured rather than remembered. Both columns are the same model, the same six
trajectories, the same counting method:

| | `--legacy-prompt` | current |
|---|---|---|
| turns emitting a block | 23 / 42 | **38 / 42** |
| compliance | 55% | **90%** |
| blocks that were not valid JSON | 4 / 23 (17%) | 7 / 38 (18%) |
| declared keys | 22 | 29 |
| keys naming a schema slot | 8 | 10 |
| **in-schema share** | **36%** | **34%** |

Compliance went up by 35 points. The share of declarations naming something the
tracker asked for did not move.

That is the finding. A harness reporting the compliance figure would have shown a
clean improvement; the in-schema share is flat, so the extra blocks are noise. And
the malformed rate is flat too, which corrects an earlier reading of this data: a
first pass compared one run at 36% malformed against one at 18% and called it an
improvement. Re-running the legacy prompt put it at 17%. The model is sampled, so
single-run rates carry real noise and the 36%→18% comparison was two draws, not a
trend.

Compliance is not correctness, and neither is a low malformed rate. The number
that predicts whether the write path is worth enabling is the in-schema share, and
`capture --verify` now refuses a capture that scores below 50% on it.

A capture made with `--legacy-prompt` is stamped `legacy_prompt: true` and `verify`
refuses it. It is a valid record of what the broken harness did and an invalid
measurement of the protocol, and it should not sit in `captures/` looking like one.

The committed capture's `schema` field was backfilled to `coding` after the fact,
and the backfill is verifiable rather than asserted: the capture's
`prompt_fingerprint` covers the schema, and only `coding` reproduces the recorded
digest `5c5215b167ec10d4`. A capture with no recorded schema reports its in-schema
ratio as unknown instead of guessing one.

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

**A declaration the schema cannot account for is not verifiable, whichever policy
you pick.** `declaration_policy="reject"` drops it, which stops junk entering
state — and also means a correct fact under an unexpected name is dropped
silently from your point of view, visible only in `rejected_writes`. The default
`"flag"` keeps it and tells you. Neither makes it true.

And the stronger version of the same warning: even a declaration that *is* in the
schema may be unverifiable. On the 14B capture 96% of declared keys named a real
slot and every one of the resulting additions was a value of the wrong shape —
three literal `None`s, and error messages where a test identifier belongs. A key
check catches an invented key; nothing here yet catches an invented value. Treat
the write path as unproven rather than as working until value shape is checked
too.

**Token counts are `chars/4`, not a BPE tokenizer.** Read them as a ratio, not a
bill. Exact numbers need `tiktoken` against your real model.

**Retired-turn recall is lexical** — token, subword, and phrase overlap. Not
semantic. "What did we decide about billing?" will not find a turn that only
contains "invoice".

**The write-path numbers come from one 7B model on six trajectories.** They are
the project's only real measurement of the write path, and they are a lower bound
rather than a verdict on the design — see the section above for what bounds them.

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

Set `"entity_schema"` to a shipped schema name to turn state tracking on, and
`"declaration_policy"` to decide what happens when the agent declares a key that
schema does not define:

| `declaration_policy` | effect |
|---|---|
| `"flag"` *(default)* | keep it, report it in `telemetry.declarations.off_schema_keys` and `rejected_writes` |
| `"reject"` | drop it, report it as dropped |
| `"off"` | accept silently |

It has no effect without `entity_schema`: an unconfigured engine has no vocabulary
to judge a key against. Note that `"reject"` also drops a *correct* fact declared
under an unexpected name, so read `rejected_writes` rather than assuming the drop
was right.

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
pytest -q                      # 289 tests
uvicorn server.main:app --reload
```

Zero runtime dependencies. `server/` and the test tooling are optional extras.

Two pages, two jobs: `/` is the overview and `/console` is the tool. They share
one stylesheet (`web/style.css`) deliberately — duplicating the tokens is how two
pages drift into looking like two products. `web/console.html` was extracted from
the old single page rather than rewritten, so no control could go missing in the
split, and `tests/browser/page.mjs` drives both surfaces plus dark mode.

The test suite asserts the claims at tolerances tight enough to fail: the
`< 10ms` compile ceiling is enforced on a 60-turn transcript, growth is asserted
to stay roughly linear from 20 to 200 turns, a monkeypatched `socket` proves
nothing opens a network connection, and one test asserts that no fabricated
telemetry field (`latency`, `hallucination`, `estimated`, `risk_score`,
`embedding`, `ivfflat`) has crept back into the output.

## Publishing

Full procedure, including the PyPI Trusted Publishing setup that has to be done
in a browser: [`docs/RELEASING.md`](docs/RELEASING.md).

`main` is protected: a pull request with `test (3.9)`, `test (3.11)`,
`test (3.13)`, `benchmark`, `build` and `browser` green. Direct pushes and force
pushes are refused, including for admins, because several of the defects in this
project's history were mergeable and invisible until something ran.

Releases are cut by tag and go out through `.github/workflows/release.yml`:

```bash
git tag v0.4.0 && git push --tags
```

One-time setup, which has to be done by the maintainer on pypi.org:
**Publishing → add a trusted publisher** for `j4yop/context-hackdevengers`
with workflow `release.yml`. There is then no API token anywhere.

Before uploading, that workflow refuses unless the tag matches the
`pyproject.toml` version, the version is not already on PyPI, `twine check
--strict` passes, the wheel installs into an empty virtualenv and compiles a
transcript using a schema from the installed package, and the dependency list is
still empty. Run it without publishing via
`workflow_dispatch` with `dry_run=true`.

## License

MIT — see [LICENSE](LICENSE).
