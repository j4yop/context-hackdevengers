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
from typing import Any, Dict, List, Optional

#: Opening and closing fences. Deliberately unlikely to occur in prose.
OPEN_TAG = "<contextgc-state>"
CLOSE_TAG = "</contextgc-state>"

_BLOCK_RE = re.compile(
    re.escape(OPEN_TAG) + r"\s*(?P<body>.*?)\s*" + re.escape(CLOSE_TAG),
    re.DOTALL,
)

#: Keys the protocol understands. Anything else is ignored rather than guessed at.
_ASSERT_KEYS = ("assert", "pin", "revoke", "unsure")

#: Only the assistant may declare state.
#:
#: This is the load-bearing security boundary of the whole feature. A `tool`
#: message is a fetched web page, a file read, or an MCP result -- all of it
#: attacker-influenced. A `user` message is a human quoting documentation, or a
#: prompt-injection payload someone pasted. A `system` message is a summarised
#: transcript, which inherits whatever the turns it summarised contained. If any
#: of those can emit a declaration, then anything the agent reads can rewrite its
#: authoritative state, and provenance "declared" becomes a mark of forgery
#: rather than of authority.
#:
#: `user` is excluded too, and that costs us: a human cannot directly correct the
#: agent's state. They do not need to -- the agent reads their correction and
#: re-declares on its next turn, which is the whole point of the write path.
DECLARING_ROLES = frozenset({"assistant"})


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


def normalise_key(raw: Any) -> str:
    """
    Canonicalise a declared key so casing and separator variants cannot fork state.

    Without this, ``destination_address``, ``destinationAddress`` and
    ``destination-address`` become three independent live keys for one field, and
    the register asserts three different current values. A model that varies its
    capitalisation between turns is normal, not adversarial.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    # Split camelCase / PascalCase before lowering, so the boundary survives.
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_").lower()
    return text[:64]


def escape_value(value: Any) -> str:
    """
    Make a value safe to embed in the state register.

    Escapes the two delimiter families that matter: brackets, which could close
    our block and forge a new one, and angle brackets, which could open a
    protocol tag and re-enter the parser on the next compile. Brackets alone are
    not enough -- the state register is re-parsed every turn, so an unescaped
    ``<contextgc-state>`` in a declared value is a round-trip injection.
    """
    text = str(value)
    for char in ("\\", "\n", "\r", "[", "]", "<", ">"):
        text = text.replace(char, {"\\": "\\\\", "\n": " ", "\r": " ",
                                   "[": "(", "]": ")", "<": "&lt;", ">": "&gt;"}[char])
    return text[:512]


def _spans(text: str) -> List[tuple]:
    """
    Locate innermost-first protocol blocks by scanning, not by regex.

    Regex with ``.*?`` across an unbalanced tag pairs the *outer* open with the
    *first* close, so a nested block swallows everything between them and the
    JSON parse fails. Scanning with a depth counter and emitting on the way down
    removes the inner block first and leaves the outer one intact, which is the
    only ordering that can be correct.

    Unterminated blocks are not treated as blocks at all (see
    :func:`has_block`): a dangling tag is prose someone typed, and silently
    deleting the rest of their message is worse than ignoring it.
    """
    closed = []
    stack = []
    i = 0
    n = len(text)
    while i < n:
        nxt_open = text.find(OPEN_TAG, i)
        nxt_close = text.find(CLOSE_TAG, i)
        if nxt_open != -1 and nxt_open <= nxt_close:
            stack.append(nxt_open)
            i = nxt_open + len(OPEN_TAG)
        elif nxt_close != -1:
            if stack:
                # Record *every* balanced pair, then keep only the innermost.
                closed.append((stack.pop(), nxt_close + len(CLOSE_TAG)))
            i = nxt_close + len(CLOSE_TAG)
        else:
            break

    # A span that strictly contains another is an outer wrapper, not a block.
    # Only the innermost pairs are real blocks; their parents are containers
    # whose own JSON is malformed anyway.
    return [
        (a, b) for a, b in closed
        if not any(a2 < a and b < b2 for a2, b2 in closed)
    ]


def find_blocks(text: Optional[str]) -> List[str]:
    """Return the JSON body of every innermost protocol block in ``text``."""
    if not text:
        return []
    return [text[a + len(OPEN_TAG):b - len(CLOSE_TAG)].strip() for a, b in _spans(text)]


def has_block(text: Optional[str]) -> bool:
    """True when ``text`` contains a *complete* protocol block.

    A lone opening tag is not a block. Treating it as one would delete the rest
    of a human's message on the assumption that a close tag was coming.
    """
    return bool(text) and bool(_spans(text))


def strip_blocks(text: Optional[str]) -> str:
    """
    Remove every innermost protocol block, leaving the human-readable remainder.

    Called before content is sent to a model. Without this, a compliant agent's
    output would feed its own markup back into the next turn's context and the
    transcript would accumulate protocol noise forever.

    A markdown code fence that wrapped the block is closed too, so the model is
    not left with a dangling ``` . A turn that was *only* a block becomes a
    single space rather than an empty string, because several providers reject
    empty assistant content outright.
    """
    if not text:
        return text or ""

    cleaned = text
    for start, end in reversed(_spans(text)):
        cleaned = cleaned[:start] + "\u0000" + cleaned[end:]

    # Close a fence the block was sitting inside.
    cleaned = re.sub(r"```[a-zA-Z0-9_+-]*[ \t]*\n?[ \t]*\u0000", "```", cleaned)
    cleaned = cleaned.replace("\u0000", " ")

    # An emptied turn still needs a body; "" is rejected by some providers.
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned if cleaned.strip() else " "


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
                name = normalise_key(entity)
                if not name:
                    merged.malformed = True
                    continue
                # A `{value, confidence}` object is rejected rather than
                # silently flattened. It used to parse and then throw the number
                # away, which made a "calibrated" claim that reached nothing.
                if isinstance(val, dict):
                    merged.malformed = True
                    continue
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
