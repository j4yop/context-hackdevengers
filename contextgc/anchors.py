"""
ContextGC: declared invariants, pinned in the compiled context.

An *invariant* is a rule the caller declares must survive compilation: a
refund ceiling, a "never print secrets" guardrail, a regulatory constraint.
The compiler inlines them into the emitted context and refuses to let tracked
entity state overwrite them.

Two honest limitations, stated here because they were previously papered over
with a "100% compliance" badge that this module cannot support:

1. Inlining a rule into a prompt makes it *more salient*. It does not make
   compliance *guaranteed*. No prompt-level technique can guarantee that.
2. :meth:`InvariantAuditor.scan` is a regular-expression heuristic over text.
   It catches the obvious shapes and misses the rest. It is a cheap tripwire,
   not a proof.

If you need actual enforcement, gate the action itself: reject the tool call,
not the sentence. This module's job is to make the rule present and loud.
"""

import re
from typing import Any, Dict, List, Optional


class PolicyInvariantAnchor:
    """
    Holds caller-declared invariants and renders them into the compiled context.

    There are no built-in domain rules. Shipping a hardcoded "refunds over
    ₹150 need approval" default meant the tool silently imported one demo
    scenario's business rules into every unrelated session. Declare your own.
    """

    def __init__(self, invariants: Optional[List[str]] = None):
        self.invariants: List[str] = list(invariants or [])

    def add(self, rule: str) -> None:
        self.invariants.append(rule)

    def render_anchor_block(self) -> str:
        """Render the declared invariants as a compact, labelled block."""
        if not self.invariants:
            return ""
        lines = ["[DECLARED_INVARIANTS]"]
        lines.extend(f"  - {rule}" for rule in self.invariants)
        return "\n".join(lines)

    def scan(self, text: str) -> Dict[str, Any]:
        """
        Heuristic lint of text against a small set of generic danger patterns.

        This is a tripwire, not a guarantee. It knows nothing about your
        business rules -- supply those via :meth:`scan_with` if you need them.
        """
        return InvariantAuditor().scan(text)


class InvariantAuditor:
    """Generic secret-leak / PII tripwire. Replaceable by a caller-supplied checker."""

    #: Deliberately narrow and generic. Domain policy belongs to the caller.
    PATTERNS = (
        ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
        ("assigned_secret", re.compile(
            r"\b(?:private[-_ ]?key|secret[-_ ]?key|api[-_ ]?key|access[-_ ]?token)\s*[:=]\s*\S+",
            re.IGNORECASE,
        )),
        ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    )

    def scan(self, text: str) -> Dict[str, Any]:
        findings = [
            {"rule": name, "match": m.group(0)[:60]}
            for name, pattern in self.PATTERNS
            for m in [pattern.search(text or "")] if m
        ]
        return {"has_violation": bool(findings), "violations": findings}

    def scan_with(self, text: str, invariants: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Apply caller-supplied rules. Each rule is ``{"name": str, "pattern": compiled}``.
        Lets a caller encode its own refund ceilings, allowlists, and so on
        without patching this library.
        """
        findings = []
        for rule in invariants:
            if rule["pattern"].search(text or ""):
                findings.append({"rule": rule["name"], "match": rule["pattern"].search(text).group(0)[:60]})
        return {"has_violation": bool(findings), "violations": findings}
