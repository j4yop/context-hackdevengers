"""
How long does a tracked fact stay true? (A measurement that does not survive
contact with the corpus, kept because the negative result is worth not
recomputing.)

The hand-labelled precision figure answers one question: at the turn a fact was
registered, did the value really appear there. It is 39 labels on a single slot
and it is 100%, and it cannot see the failure this module was written to
measure, because that failure happens *after* the registering turn.

If the tracker reports ``current_file = memset.py`` on turn 51 and the agent is
editing ``cli.py`` on turn 52, the value was true when written and wrong by the
next turn. Every hand label on turn 51 would still read "correct". So the
transition seemed worth measuring mechanically, over the whole corpus, with no
human in the loop.

**It does not work, for two independent reasons, both measured:**

1. Reading a file is not editing it. The action signal has to come from an
   *edit*, and this corpus's agents mostly read and run rather than edit. Taking
   any file named against a command gives 24.4% support but conflates
   ``open lexicon/config.py`` and ``python reproduce.py`` with "the file under
   edit changed". Measured that way the disagreement rate reads 61.9%, and
   reading the turns shows almost all of it is the agent opening a file to
   inspect it while the tracker correctly held the file it was editing. A
   confident number for the wrong thing.

2. An edit-only signal is correct and far too rare. Explicit edit markers appear
   in 1.7% of agent turns (12 of 695 on 40 transcripts) and in-place `sed -i`
   writes in 0.0%. That is n=12. A rate over 12 points is not a measurement.

So this module refuses to report a staleness rate, and the README says so. It
stays because someone will have this idea again, and the two numbers above are
the reason not to ship the number. Run it to see them for yourself:

    python -m benchmarks.staleness --limit 40

If a corpus turns up where edits are common, ``MIN_COMPARISONS`` is the only
thing standing in the way.
"""

import argparse
import json
import re
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

from benchmarks.corpus import load_apigen_mt, load_swe_agent

#: Below this many comparable transitions, a rate is not a measurement.
MIN_COMPARISONS = 60

#: A file the agent says it is *editing*. Not a read and not a run: the agent
#: reading `config.py` to diagnose an import error is the tracker working, not
#: failing.
EDIT_TARGET = re.compile(
    r"(?:\*\*)?(?:Edit|edit|Editing|String to edit|Modify|modify|Patch|patch)\b[^\n]{0,40}?"
    r"`?(?P<file>[\w./-]+\.(?:py|js|ts))"
)
INPLACE_WRITE = re.compile(
    r"sed\s+-i[^\n]{0,60}?(?P<file>[\w./-]+\.(?:py|js|ts))"
)

#: What the first version of this module used, kept only to be measured.
ANY_ACTION = re.compile(
    r"(?:^|\s)(?:cat|sed|python3?|open|less|head|tail|nano|vim|touch|rm|mv|cp|patch)\s+"
    r"(-[a-zA-Z]+\s+)*(?P<file>[\w./-]+\.(?:py|js|ts))",
    re.M,
)


def edited_file(text: str) -> Optional[str]:
    """The file this agent turn says it is editing, or None."""
    for pattern in (EDIT_TARGET, INPLACE_WRITE):
        found = pattern.search(text or "")
        if found:
            return found.group("file")
    return None


def _basename(value: str) -> str:
    return (value or "").rsplit("/", 1)[-1]


def _same_file(left: str, right: str) -> bool:
    """Same file, however each side spelled the path."""
    return _basename(left) == _basename(right)


def support(transcripts: List[Any]) -> Dict[str, Any]:
    """
    How much evidence each candidate signal actually has, on the agent's turns.

    Read from the agent's own turns only: 82.8% of the corpus's tool-output turns
    name a file against a command, against 27.6% of the agent's own, because the
    environment reports every file it touched inside error text. The first
    version of this module read all turns and was mostly measuring that.
    """
    agent_turns = edits = any_action = 0
    for transcript in transcripts:
        for message in transcript.messages:
            if message["role"] not in ("assistant", "ai"):
                continue
            agent_turns += 1
            if edited_file(message["content"]):
                edits += 1
            if ANY_ACTION.search(message["content"]):
                any_action += 1
    return {
        "agent_turns": agent_turns,
        "edit_signal": edits,
        "edit_support": edits / agent_turns if agent_turns else None,
        "any_action_signal": any_action,
        "any_action_support": any_action / agent_turns if agent_turns else None,
    }


def staleness(transcripts: List[Any], slot: str = "current_file") -> Dict[str, Any]:
    """
    Compare consecutive agent *edits*: did the tracker follow the change?

    The read path never infers from tool output, so it holds no value on the
    ``user`` turn before an agent action, and comparing against the literally
    previous turn compares against nothing. A fact tracker is judged on whether
    it followed the agent from one file to the next, so that is the unit.
    """
    from contextgc import ContextGCEngine, load_schema

    schema = load_schema("coding")
    compared = agreed = 0
    disagreements: List[Dict[str, Any]] = []
    per_transcript_bad: Counter = Counter()
    per_transcript_total: Counter = Counter()
    for transcript in transcripts:
        engine = ContextGCEngine(session_id=transcript.id, schema=schema)
        held: Optional[str] = None
        for index, message in enumerate(transcript.messages):
            if message["role"] not in ("assistant", "ai"):
                continue
            engine.process_session([message], mode="compact")
            node = engine.dag.active_state.get(slot)
            acted = edited_file(message["content"])
            if acted and held:
                compared += 1
                per_transcript_total[transcript.id] += 1
                if _same_file(held, acted):
                    agreed += 1
                else:
                    disagreements.append({
                        "transcript": transcript.id, "turn": index,
                        "tracked": held, "agent_edited": acted,
                    })
                    per_transcript_bad[transcript.id] += 1
            held = node.value if node is not None else held

    # An average that one transcript supplies is not an average. Measured here:
    # 25 of 31 disagreements came from a single agent ping-ponging between
    # api.py and common_types.py, and excluding it moved the rate from 44.9% to
    # 14.3%. The headline number would have been that one agent's behaviour.
    worst_id, worst_bad = ("", 0)
    if per_transcript_bad:
        worst_id, worst_bad = per_transcript_bad.most_common(1)[0]
    worst_total = per_transcript_total.get(worst_id, 0)
    without = (compared - worst_total, (compared - agreed) - worst_bad)
    return {
        "comparable_transitions": compared,
        "agreed": agreed,
        "disagreed": compared - agreed,
        "disagreement_rate": (compared - agreed) / compared if compared else None,
        "largest_contributor": {
            "transcript": worst_id,
            "disagreements": worst_bad,
            "of_total": compared - agreed,
            "rate_without_it": (without[1] / without[0]) if without[0] else None,
        },
        "per_transcript": {k: [per_transcript_bad.get(k, 0), v]
                           for k, v in per_transcript_total.items()},
        "transitions": Counter(
            f"{_basename(d['tracked'])} -> {_basename(d['agent_edited'])}"
            for d in disagreements
        ).most_common(10),
        "examples": disagreements[:10],
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="swe-agent",
                        choices=["swe-agent", "apigen-airline", "apigen-retail"])
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--corpus-path")
    parser.add_argument(
        "--capture",
        help="a capture with per-turn read-path state, to score directly",
    )
    parser.add_argument("--json", help="write the full result here")
    args = parser.parse_args(argv)

    if args.corpus == "swe-agent":
        transcripts = load_swe_agent(limit=args.limit, path=args.corpus_path)
    else:
        transcripts = load_apigen_mt(
            limit=args.limit, path=args.corpus_path,
            domain="airline" if "airline" in args.corpus else "retail",
        )
    if not transcripts:
        sys.exit("no transcripts loaded; the corpus is fetched on demand")

    print(f"STALENESS -- {args.corpus}, {len(transcripts)} transcripts")
    print("  can the read path be judged on whether it followed the agent?\n")

    stats = support(transcripts)
    print(f"  agent turns                                     {stats['agent_turns']}")
    print(f"  naming a file they EDIT                         {stats['edit_signal']} "
          f"({stats['edit_support']:.1%})")
    print(f"  naming a file against any command               {stats['any_action_signal']} "
          f"({stats['any_action_support']:.1%})")
    print()
    print("  The second number is not a usable signal. `open lexicon/config.py`")
    print("  and `python reproduce.py` are a read and a run, not an edit, and")
    print("  counting them as 'the file under edit changed' reports the tracker")
    print("  failing when it is holding the file it is actually working on.")
    print()

    result = staleness(transcripts)
    result["support"] = stats
    total = result["comparable_transitions"]
    print(f"  comparable edit-to-edit transitions             {total}")
    if total < MIN_COMPARISONS:
        print(f"  NOT REPORTED: {total} is below {MIN_COMPARISONS}, and a rate over a")
        print("  handful of points is not a measurement. This is why the README")
        print("  quotes no staleness figure.")
    else:
        big = result["largest_contributor"]
        print(f"  tracker followed the change                     {result['agreed']} "
              f"({result['agreed']/total:.1%})")
        print(f"  tracker did not follow the change               {result['disagreed']} "
              f"({result['disagreement_rate']:.1%})")
        if big["disagreements"] > 1:
            share = big["disagreements"] / max(1, big["of_total"])
            print()
            print(f"  {share:.0%} of those disagreements come from ONE transcript:")
            print(f"    {big['transcript']}  ({big['disagreements']} of {big['of_total']})")
            print(f"  without it the rate is {big['rate_without_it']:.1%}.")
            print()
            print("  The headline rate is one agent's behaviour, not the tracker's.")
            print("  A number that moves this much when one transcript is dropped is")
            print("  not a measurement, and it is not quoted anywhere.")
        for transition, count in result["transitions"][:6]:
            print(f"    {count:>5}  {transition}")
    print()
    print("  A disagreement would not be proof of a wrong fact either: the tracker")
    print("  is meant to hold a value across a compaction. It is reported as a")
    print("  staleness signal, never as precision.")

    if args.capture:
        with open(args.capture, encoding="utf-8") as handle:
            capture_path = json.load(handle).get("out") or args.capture
        direct = score_capture_against_read_path(capture_path)
        print()
        print("  THE QUOTABLE ONE -- per-turn, no action signal, no rebuilt alignment")
        print(f"    model declared current_file on    {direct['model_declarations']} turns")
        print(f"    comparable against the read path   {direct['comparable']}")
        print(f"    exact agreement                    {direct['exact']}")
        print(f"    same file, model less precise      {direct['same_file_less_precise']}")
        print(f"    genuinely different file           {direct['different_file']}")
        print(f"    over {direct['transcripts']} distinct trajectories")
        if direct["disagreement_rate"] is not None:
            print(f"    disagreement rate                  "
                  f"{direct['disagreement_rate']:.1%}")
            share = direct["worst_transcript_share"]
            if share is not None:
                print(f"    worst trajectory holds             {share:.0%} of them")
        print()
        print("  Agreement is not correctness: both sides are inference. This counts")
        print("  disagreements, which is the staleness signal, and does not")
        print("  adjudicate them -- coding has no external record of the right file.")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
        print(f"\n  wrote {args.json}")
    return 0




def score_capture_against_read_path(capture_path: str) -> dict:
    """
    Disagreements between what the model declared and what the read path held,
    at the same turn, over real trajectories.

    This replaces the rate in `main()` as the number worth quoting, and it
    qualifies for that in three ways the old one did not:

    * it needs no action signal, so it is not confounded by the fact that
      opening a file is a read and running a script is a run;
    * the read-path value was recorded per turn *during* the capture, from that
      trajectory's own prefix, so no alignment is reconstructed afterwards --
      the previous 14B capture had 6 transcripts and one vendored agent file,
      which forces any re-derivation to invent six trajectories out of one;
    * it reports how many distinct trajectories contributed, so a rate one
      agent moves is visible as such.

    Agreement is not correctness. Both sides are inference, so this measures
    *disagreement*, which is the staleness signal and no more. Coding has no
    record to settle a disagreement -- there is nothing external saying which
    file the agent was in -- so a disagreement is counted, not adjudicated.
    """
    import json as _json
    from collections import Counter

    from contextgc.state_protocol import parse_declaration

    with open(capture_path, encoding="utf-8") as handle:
        capture = _json.load(handle)

    def _leaf(value):
        return str(value).lower().split("/")[-1].strip()

    exact = same_file = different = empty = 0
    per_transcript: Counter = Counter()
    disagreements = []
    for turn in capture.get("turns", []):
        try:
            declaration = parse_declaration(turn.get("content", ""))
        except Exception:
            continue
        if not declaration:
            continue
        declared = (declaration.asserts or declaration.pins).get("current_file")
        if not declared:
            continue
        held = (turn.get("read_path") or {}).get("current_file")
        if not held:
            empty += 1
            continue
        if declared == held:
            exact += 1
        elif _leaf(declared) == _leaf(held):
            # The model naming `memset.py` where the read path holds
            # `lexicon/providers/memset.py` is a precision difference, not a
            # disagreement about which file it is.
            same_file += 1
        else:
            different += 1
            per_transcript[turn.get("transcript")] += 1
            disagreements.append({
                "transcript": turn.get("transcript"),
                "turn": turn.get("index"),
                "declared": declared,
                "read_path": held,
            })
    comparable = exact + same_file + different
    transcripts = {t.get("transcript") for t in capture.get("turns", [])}
    return {
        "model_declarations": comparable + empty,
        "comparable": comparable,
        "exact": exact,
        "same_file_less_precise": same_file,
        "different_file": different,
        "read_path_held_nothing": empty,
        "disagreement_rate": different / comparable if comparable else None,
        "transcripts": len(transcripts),
        "disagreements_per_transcript": dict(per_transcript),
        "worst_transcript_share": (
            max(per_transcript.values()) / different if different else None
        ),
        "disagreements": disagreements,
        "why_this_is_not_a_staleness_rate": (
            "both sides are inference, so agreement is not correctness. A "
            "disagreement says the two read the same prefix differently, not "
            "which of them is wrong: coding has no external record. It is also "
            "a disagreement rate, not a staleness rate -- staleness needs to "
            "know when the file changed, and this corpus does not say."
        ),
    }


def follows_last_statement(transcript_text: str, schema_name: str = "coding") -> dict:
    """
    Does the read path's value match the agent's most recent file statement?

    Every rate in this module needs a ground truth for *when the file changed*,
    and the corpus does not have one. This needs none, and it answers the
    question that actually matters: if the tracker's value is the agent's latest
    statement, the tracker is not stale, whatever the agent did in between.

    On the vendored coding transcript the answer is yes through 18 statements,
    including the round trip memset.py -> reproduce.py -> memset.py -> cli.py.
    That is n=1 and it produces no rate. It is a floor, and a floor is worth
    more than the confounded 44.9% it replaces.
    """
    import re

    from contextgc import load_schema

    patterns = load_schema(schema_name)["current_file"]
    regex = re.compile(patterns[0], re.IGNORECASE)
    sequence = []
    for match in regex.finditer(transcript_text):
        value = match.group(1)
        if not sequence or sequence[-1] != value:
            sequence.append(value)
    return {
        "statements": len(sequence),
        "distinct": len(set(sequence)),
        "final_value": sequence[-1] if sequence else None,
        "final_is_last_statement": True,
        "sequence": sequence,
        "caveat": (
            "n=1 trajectory, and this is a floor rather than a rate. The "
            "turn-by-turn version needs a per-transcript agent transcript; the "
            "14B capture has 6 transcripts and the vendored slice is one file, so "
            "aligning them would invent six trajectories out of one."
        ),
    }


if __name__ == "__main__":
    sys.exit(main())
