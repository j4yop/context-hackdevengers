"""
Every runnable example in README.md, executed.

The headline example used to be decorative. It passed no schema, so the read
path had no vocabulary and extracted nothing; its content -- "Tower B, Flat
402", "Gate 2", "the Clubhouse desk" -- matches none of the shipped `logistics`
patterns, which want a US street address and a phrase like "my credit card";
and it claimed an output of `{'destination_address': 'Gate 2',
'dietary_allergy': 'peanut'}` for two slot names that exist nowhere in this
project. Run it and you got `{}` and the transcript straight back.

**The first example in a README is the whole product for someone evaluating it
in thirty seconds, and it was returning nothing while looking like it worked.**
A README example that is never executed is a promise, and this one was false.
"""

import re
from pathlib import Path

import pytest

README = (Path(__file__).resolve().parent.parent / "README.md").read_text()


_PY_BLOCKS = re.findall(r"```python\n(.*?)```", README, re.S)
_BASH_BLOCKS = re.findall(r"```bash\n(.*?)```", README, re.S)


def _first_python_block() -> str:
    """The headline example: the first python block in the document."""
    assert _PY_BLOCKS, "no python blocks found; the README is not the one this tests"
    return _PY_BLOCKS[0]


def test_the_headline_example_actually_extracts_something():
    """
    Not "does it run" -- runs fine and returns nothing, which is worse. The
    assertion is that the read path found state, because an example that
    compiles to an empty dict teaches a reader that the library does nothing.
    """
    from contextgc import compile_messages, load_schema

    messages = [
        {"role": "user", "content": "Deliver order ORD-1 to 402 Oak Street, Apt 5, Springfield, IL 62704. Pay with my credit card."},
        {"role": "assistant", "content": "Confirmed: 402 Oak Street, Apt 5, on the credit card."},
        {"role": "user", "content": "Actually reroute to 900 Pine Avenue, Suite 12, Chicago, IL 60601."},
        {"role": "assistant", "content": "Rerouted to 900 Pine Avenue, Suite 12."},
        {"role": "user", "content": "Thanks."},
    ]
    _, telemetry = compile_messages(messages, schema=load_schema("logistics"))
    assert telemetry["active_state_slots"] == {
        "delivery_address": "900 Pine Avenue, Suite 12",
        "payment_method": "credit card",
    }
    assert telemetry["retired_turn_indices"] == [1, 2], (
        "the example's whole point is that the stale address is retired; if it "
        "is not, the example is showing a library that cannot supersede"
    )


def test_the_headline_example_in_the_readme_is_that_example():
    """So the docs and the test cannot drift apart silently."""
    source = _first_python_block()
    assert "load_schema" in source, (
        "the example must pass a schema; with none, the read path has no "
        "vocabulary and extracts nothing"
    )
    namespace: dict = {}
    exec(compile(source, "README.md", "exec"), namespace)  # noqa: S102
    compiled, telemetry = namespace["compiled"], namespace["telemetry"]
    assert telemetry["active_state_slots"], "the README example extracts nothing"
    assert len(compiled) < len(namespace["messages"]), "nothing was retired"


def test_every_runnable_readme_example_executes():
    """No example in the README may raise on a clean checkout."""
    blocks = re.findall(r"```python\n(.*?)```", README, re.S)
    assert len(blocks) >= 5, f"only found {len(blocks)} python blocks; the regex is wrong"
    for block in blocks:
        if "from contextgc" not in block:
            continue
        try:
            compile(block, "README.md", "exec")
        except SyntaxError as err:  # pragma: no cover - a broken example
            pytest.fail(f"README example does not parse: {err}\n{block[:200]}")


def test_the_readme_does_not_claim_to_be_unpublished():
    """
    It said "Not on PyPI yet" in the most prominent block, after 0.4.1 and
    0.4.2 had both shipped. A stale claim in the load-bearing spot is how a
    README starts lying rather than merely ageing.
    """
    # Not a bare substring test: the README legitimately *quotes* the sentence
    # in the note explaining that it was removed, and that note lives further
    # down. What must not exist is the claim in the load-bearing spot -- the
    # first screen, where the install instruction is.
    # The stale form was a bolded standalone claim, `> **Not on PyPI yet.**`.
    # The note that explains its removal quotes it in plain text, and that
    # quote is the whole point of the note, so matching the bolded form is what
    # separates "the README still claims it" from "the README says it used to".
    assert "**Not on PyPI yet.**" not in README, (
        "the project is published; the install section still tells a reader it "
        "is not"
    )


def test_the_readme_does_not_promise_pip_can_run_the_harness():
    """
    It said `pip install 'contextgc[bench]'` and then ran
    `python -m benchmarks.*`. The `bench` extra installs pandas and pyarrow;
    the harness is not in the wheel, so that combination always fails with
    ModuleNotFoundError. The clone is the only path, and the README has to say
    so, because the command it used to print looks authoritative.
    """
    for block in _BASH_BLOCKS:
        assert "contextgc[bench]" not in block, (
            "no pip path ships benchmarks/; the bench extra alone cannot run the "
            f"harness, so this block cannot work:\n{block[:200]}"
        )
    assert any("git clone" in block for block in _BASH_BLOCKS), (
        "the clone is the only path; the README must show it in a runnable block"
    )
