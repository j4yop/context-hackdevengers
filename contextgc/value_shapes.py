"""
Derive a value contract for each slot from the schema's own patterns.

A schema's ``entities`` say what a slot is and how to find it in text; the read
path's values come out of those patterns by construction. What a *declared*
value may look like is a different question, and nothing answered it — which is
how a 14B model's `failing_test` could be `HTTPError: 403 Forbidden`, pass every
key-level check, and then win over a correct read-path value because a declared
fact always wins.

These contracts were first written by hand from the values one capture happened
to produce. That is a guess wearing a measurement's clothes, and it was wrong in
ways only a corpus could have caught: it omitted `first` from ``cabin_class``
while the pattern carried it, and it omitted ``basic economy`` — the single most
common value in that slot, 14 of 42 observations — because the multi-word
literal was mistaken for a structural pattern.

So they are derived here instead. The patterns were fitted to a corpus, so their
alternations *are* that corpus's vocabulary; reusing them substitutes a
measurement for a guess. Two shapes come out:

* a literal alternation (``economy|business|first``) becomes the vocabulary
* a structural group (``[\\w][\\w./-]*\\.(?:py|js)``) becomes the shape

Three refinements are applied, each because the naive derivation got a measured
case wrong:

* ``test_`` is anchored to a token start. The raw group accepts
  ``latest_file.py`` because the leading class absorbs the ``la``.
* A group that cannot contain a separator is a whole value, not a fragment, so
  it is anchored at both ends. ``[A-Z0-9]{6}`` searched also matches the
  ``HTTPError`` inside ``HTTPError: 403``.
* The match is a *search*, not a full match, so a leading ``/`` on an absolute
  path and pytest's ``::`` separator both survive.

Contracts are stored in the schema file, where a reviewer can read them, and
``test_the_stored_contracts_still_match_the_derivation`` fails if a pattern is
edited without re-deriving. Storage for inspection, derivation for provenance.
"""

import re
from typing import List, Optional, Sequence, Tuple

#: Openers that are groups but not captures: ``(?:``, ``(?=``, ``(?!``, ``(?<=``,
#: ``(?<!``, ``(?P=``, and any scoped flag group such as ``(?i:`` or ``(?-i:``.
_NOT_CAPTURE = re.compile(r"\(\?(?:[a-zA-Z]*-?[a-zA-Z]*)?[:=!]|\(\?<[=!]|\(\?P=")

#: ``(?-i:`` switches case-sensitivity *back on* inside a group. Losing it
#: silently costs a real constraint: the travel schema writes its reservation id
#: as ``(?-i:([A-Z0-9]{6}))``, and the value gate compiles contracts
#: case-insensitively, so a contract derived from the bare group accepted
#: ``memset`` and ``abcdef`` -- any six word characters -- as a reservation code.
_CASE_SCOPE = re.compile(r"\(\?-i:")

#: A literal alternative: letters, digits, spaces and address punctuation.
_LITERAL = re.compile(r"[A-Za-z0-9 .'/()-]+")


def last_capture_group(pattern: str) -> Optional[str]:
    """
    Source of the last real capture group, at any nesting depth, or ``None``.

    Reading it needs a real scan rather than a search for the last ``(``:

    * ``([\\w][\\w./-]*\\.(?:py|js|ts))`` nests a non-capturing group inside the
      capture we want, and a naive search returns the wrong span;
    * the travel schema wraps its capture in a *scoped flag group*,
      ``(?-i:([A-Z0-9]{6}))``, putting the capture one level below the top.

    A stack of open parens, each tagged with whether it captures, is the whole
    problem. A first attempt tracked only depth-zero groups and returned nothing
    for the second shape, and a second returned a stray ``)``; both are pinned by
    ``test_the_capture_scanner_handles_nesting``.

    A capture inside ``(?-i:...)`` is returned still wrapped in that scope. The
    scope is a constraint the pattern states, and the gate matches
    case-insensitively, so dropping it would hand every uppercase class to any
    lowercase string of the same length.
    """
    stack: List[Tuple[int, bool]] = []
    last: Optional[str] = None
    index = 0
    in_class = False
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if in_class:
            if char == "]":
                in_class = False
            index += 1
            continue
        if char == "[":
            in_class = True
            index += 1
            continue
        if char == "(":
            stack.append((index, _NOT_CAPTURE.match(pattern, index) is None))
        elif char == ")":
            if stack:
                start, is_capture = stack.pop()
                if is_capture:
                    last = pattern[start + 1:index]
                    # Any enclosing group may have switched case-sensitivity back
                    # on; carry the scope into the contract rather than lose it.
                    if any(_CASE_SCOPE.match(pattern, opener) for opener, _ in stack):
                        last = f"(?-i:{last})"
        index += 1
    return last


def _literals(group: str) -> Optional[List[str]]:
    """
    The literal alternatives of an alternation, or ``None`` if a branch is
    structural.

    ``\\s+`` counts as a space, so ``basic\\s+economy`` is a literal value rather
    than a shape. It is the most common ``cabin_class`` in the corpus and the
    first attempt dropped it for looking structural.
    """
    out: List[str] = []
    for branch in group.split("|"):
        normalised = branch.replace("\\s+", " ").strip()
        if normalised and _LITERAL.fullmatch(normalised):
            out.append(normalised)
        else:
            return None
    return out


def derive_value_contract(patterns: Sequence[str]) -> Tuple[Optional[str], str]:
    """
    Derive one slot's value contract from its patterns.

    Returns ``(contract, basis)``. ``basis`` names what the contract came from,
    because a contract derived from a literal alternation and one derived from a
    structural group fail in different ways and a reader needs to know which
    they are looking at.
    """
    groups = [g for g in (last_capture_group(p) for p in patterns) if g]
    if not groups:
        return None, "no capture group"
    vocabulary: set = set()
    shapes: List[str] = []
    for group in groups:
        literals = _literals(group)
        if literals:
            vocabulary.update(literals)
        else:
            shapes.append(group)
    parts = [re.escape(v) for v in sorted(vocabulary, key=len, reverse=True)]
    shapes = list(dict.fromkeys(shapes))
    parts += shapes
    if not parts:
        return None, "unusable"
    if vocabulary and shapes:
        basis = "vocabulary + structure"
    elif vocabulary:
        basis = "vocabulary from the slot's own alternation"
    else:
        basis = "structure from the slot's own capture group"
    contract = "(?:" + ")|(?:".join(parts) + ")"

    # `test_` must begin a token, or the leading class absorbs the "la" in
    # "latest_file.py" and calls it a test. The boundary is "not preceded by an
    # alphanumeric", not "preceded by a separator": the read path also produces
    # `tests/mobly/base_test_test.py` and `tests.test_flask_pyoidc`, where the
    # underscore or dot in front of `test_` is part of the module name. Anchoring
    # to separators rejected 2 of 126 real values before this correction.
    lead = r"[\w./\[\]-]*test_"
    if lead in contract:
        contract = contract.replace(lead, r"(?<![A-Za-z0-9])test_")

    # A group that cannot hold a separator or a space is a whole value. Anchored,
    # `[A-Z0-9]{6}` also stops matching the `HTTPError` inside "HTTPError: 403".
    for group in shapes:
        if "/" in group or "\\s" in group:
            continue
        if "\\w" in group or "A-Z" in group or "0-9" in group:
            # Replace the loose alternative rather than adding an anchored one
            # alongside it: prepending leaves the unanchored form in the
            # alternation, where it still matches inside "HTTPError: 403".
            # `shapes` is deduplicated above, and the search is bounded to an
            # unanchored occurrence, so this cannot re-anchor its own output
            # into `^^^...$$$` -- which happened while the loop still ran once
            # per pattern and the schema's three identical groups re-wrapped.
            contract = re.sub(
                r"(?<!\^)\(\?:" + re.escape(group) + r"\)(?!\$)",
                lambda m, g=group: f"^(?:{g})$",
                contract,
            )

    return contract, basis
