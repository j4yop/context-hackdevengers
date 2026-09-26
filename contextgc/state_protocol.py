"""
contextgc state protocol — the write path.

The read path (regex extraction) has a ceiling it cannot clear: a fact expressed
through pronouns ("send it to the new place instead") is invisible to it, and a
hallucinated fact is indistinguishable from a real one. The model that produced
the claim is the only component that can resolve either.

So instead of parsing harder, we stop parsing. The agent *declares* what it
believes, as a structured side-effect of the turn it was already making. There
is no extra model call, no extra latency, and no second network hop: the
declaration rides along in the same completion the agent was going to produce.

The loop closes because the compiler already injects the current state register at
the head of the context. The agent reads it, reasons, and declares what changed::

    state register (head)  ->  agent reasons  ->  <contextgc-state> block
                                                       |
                                     compiler extracts, strips the block
                                                       |
                                        next turn's register is updated

Format
------
A single fenced block containing one JSON object::

    <contextgc-state>
    {
      "assert": {"destination_address": "Gate 2 security entrance"},
      "pin":    {"dietary_allergy": "peanut"},
      "revoke": ["gate_code"],
      "unsure": {"rider_location": "maybe the west gate"}
    }
    </contextgc-state>

All four keys are optional; an empty object is valid.

``assert``  the agent is asserting this value. Supersedes any previous value.
``pin``     assert, and mark immutable — a later turn cannot overwrite it.
``revoke``  stop tracking this key entirely. This is the operation the old
            engine was missing: retiring a turn has to retract the facts that
            turn uniquely held, and only the agent knows when a fact is void
            rather than merely stale.
``unsure``  a low-confidence assertion. Tracked and surfaced, but flagged so a
            caller can route on it instead of treating it as settled. This is the
            seam where calibrated probabilities plug in later — see
            :func:`confidence_from_logprobs`.

Provenance is the point. A declared fact and a regex-inferred fact are not the
same kind of object, and this library never conflates them. See
:attr:`FactNode.source`.

The block is stripped from message content before it is sent to a model. A model
never sees its own protocol markup, and the markup can never be smuggled into a
prompt as if it were prose.
"""

import json
import re
from typing import Dict, List, Optional

#: Opening and closing fences. Deliberately unlikely to occur in prose.
OPEN_TAG = "<contextgc-state>"
CLOSE_TAG = "</contextgc-state>"

_BLOCK_RE = re.compile(
    re.escape(OPEN_TAG) + r"\s*(?P<body>.*?)\s*" + re.escape(CLOSE_TAG),
    re.DOTALL,
)

#: Keys the protocol understands. Anything else is ignored rather than guessed at.
_ASSERT_KEYS = ("assert", "pin", "revoke", "unsure")


class StateDeclaration:
    """
    One parsed ``<contextgc-state>`` block.

    ``malformed`` is set when a block was present but could not be understood, so
    a caller can distinguish "the agent said nothing" from "the agent said
    something we could not read" — the second is a real signal.
    """

    __slots__ = ("asserts", "pins", "revokes", "unsure", "malformed")

    def __init__(
        self,
        asserts: Optional[Dict[str, str]] = None,
        pins: Optional[Dict[str, str]] = None,
        revokes: Optional[List[str]] = None,
        unsure: Optional[Dict[str, str]] = None,
        malformed: bool = False,
    ):
        self.asserts: Dict[str, str] = asserts or {}
        self.pins: Dict[str, str] = pins or {}
        self.revokes: List[str] = revokes or []
        self.unsure: Dict[str, str] = unsure or {}
        self.malformed = malformed

    def __bool__(self) -> bool:
        return bool(self.asserts or self.pins or self.revokes or self.unsure or self.malformed)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"StateDeclaration(asserts={self.asserts!r}, pins={self.pins!r}, "
            f"revokes={self.revokes!r}, unsure={self.unsure!r}, malformed={self.malformed!r})"
        )


def find_blocks(text: Optional[str]) -> List[str]:
    """Return the raw JSON bodies of every protocol block in ``text``."""
    if not text:
        return []
    return [m.group("body") for m in _BLOCK_RE.finditer(text)]


def has_block(text: Optional[str]) -> bool:
    """True when ``text`` contains at least one protocol block."""
    return bool(text) and OPEN_TAG in text


def strip_blocks(text: Optional[str]) -> str:
    """
    Remove every protocol block, leaving the human-readable remainder.

    Called before content is sent to a model. Without this, a compliant agent's
    output would feed its own markup back into the next turn's context and the
    transcript would accumulate protocol noise forever.
    """
    if not text:
        return text or ""
    cleaned = _BLOCK_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def parse_declaration(text: Optional[str]) -> StateDeclaration:
    """
    Parse all protocol blocks in ``text``.

    Never raises. A block that does not parse is reported via
    ``StateDeclaration.malformed`` so the failure is visible in telemetry rather
    than swallowed.
    """
    bodies = find_blocks(text)
    if not bodies:
        return StateDeclaration()

    merged = StateDeclaration()
    for body in bodies:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            merged.malformed = True
            continue
        if not isinstance(data, dict):
            merged.malformed = True
            continue

        for key in _ASSERT_KEYS:
            if key not in data:
                continue
            value = data[key]
            if key == "revoke":
                if isinstance(value, list):
                    merged.revokes.extend(str(v).strip() for v in value if str(v).strip())
                elif isinstance(value, str) and value.strip():
                    merged.revokes.append(value.strip())
                else:
                    merged.malformed = True
                continue
            if not isinstance(value, dict):
                merged.malformed = True
                continue
            target = {"assert": merged.asserts, "pin": merged.pins, "unsure": merged.unsure}[key]
            for entity, val in value.items():
                name = str(entity).strip()
                if not name:
                    merged.malformed = True
                    continue
                # Accept both a bare scalar and a {value, confidence} object.
                if isinstance(val, dict) and "value" in val:
                    target[name] = str(val["value"])
                else:
                    target[name] = str(val)

    return merged


def render_instruction(entities: Optional[List[str]] = None) -> str:
    """
    The system-prompt fragment that teaches an agent the protocol.

    ``entities`` optionally narrows the suggestion to keys the caller's domain
    uses. Kept terse on purpose: a long instruction in the system prompt is a
    cost on every turn, and a protocol the model half-remembers is worse than
    one it does not know, because the compiler would then trust a partial
    declaration as authoritative.
    """
    hint = ""
    if entities:
        shown = ", ".join(sorted(entities)[:12])
        hint = f"\nRelevant keys for this domain: {shown}."

    return (
        "[STATE_PROTOCOL]\n"
        "After your reply, emit one state block reporting what this turn changed.\n"
        'Format: <contextgc-state>{"assert":{"key":"value"},"pin":{"key":"value"},'
        '"revoke":["key"],"unsure":{"key":"value"}}</contextgc-state>\n'
        "- assert: a value you are now confident about. Replaces any earlier value.\n"
        "- pin: assert, and mark immutable. Later turns cannot overwrite it. Use for\n"
        "  safety rules and hard constraints (allergies, spend limits, legal caps).\n"
        "- revoke: stop tracking a key. Use when a fact is void, not merely outdated\n"
        "  (an order was cancelled, a code path was deleted, a credential was revoked).\n"
        "- unsure: a value you are not confident in. Tracked, but flagged as unsettled.\n"
        "Emit only keys this turn actually changed. Omit the block entirely if nothing\n"
        "changed. Do not restate unchanged keys." + hint
    )


def confidence_from_logprobs(logprobs: Optional[List[float]]) -> Optional[float]:
    """
    Turn token log-probabilities into a calibrated confidence in [0, 1].

    The seam for probabilistic extraction. If a model can be asked to choose
    between a fixed set of candidate values and report log-probabilities for
    each, this converts that into the number :func:`render_instruction` asks for
    under ``unsure`` — and, more importantly, into a *threshold* an agent loop
    can gate on ("re-ask the human below 0.7") instead of a vibe.

    Args:
        logprobs: log-probability of each candidate, as returned by an OpenAI-
            compatible ``logprobs`` response. Higher is more likely.

    Returns:
        Normalised confidence, or None if the input is unusable. Confidence is
        the probability mass on the best candidate after a softmax over
        ``exp(logprob)``, which is the correct reading of "these were the
        alternatives and here is how likely each was".
    """
    if not logprobs:
        return None
    try:
        values = [float(x) for x in logprobs]
    except (TypeError, ValueError):
        return None
    if not values:
        return None

    peak = max(values)
    weights = [pow(2.718281828459045, v - peak) for v in values]
    total = sum(weights)
    if total <= 0:
        return None
    return round(max(weights) / total, 4)


def declaration_counts(declarations: List[StateDeclaration]) -> Dict[str, int]:
    """Aggregate declaration activity across turns, for telemetry."""
    return {
        "turns_with_block": sum(1 for d in declarations if d),
        "asserted": sum(len(d.asserts) for d in declarations),
        "pinned": sum(len(d.pins) for d in declarations),
        "revoked": sum(len(d.revokes) for d in declarations),
        "unsure": sum(len(d.unsure) for d in declarations),
        "malformed": sum(1 for d in declarations if d.malformed),
    }
