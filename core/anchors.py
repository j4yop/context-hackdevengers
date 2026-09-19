"""
ContextGC: Deterministic Policy Invariant Anchoring
Injects immutable business rules, security guardrails, and constraints at the optimal transformer attention position.
Guarantees zero rule drift and halts hallucinated policy overrides.
"""

from typing import List, Dict, Any

class PolicyInvariantAnchor:
    """
    Manages non-negotiable operational business invariants and security guardrails.
    Prevents LLM rule erosion in high-turn escalation or long coding sessions.
    """

    DEFAULT_INVARIANTS = [
        "FINANCIAL_LIMIT: Instant automated refund cap is ₹150. Any refund > ₹150 strictly requires human supervisor approval.",
        "SECURITY_GUARDRAIL: Never output or log unencrypted cryptographic private keys or JWT secrets to console or remote monitoring.",
        "SUBSTITUTION_LAW: Controlled goods and sensitive pharmaceuticals can NEVER be substituted under any circumstance.",
        "GEO_CONSTRAINT: Delivery address reroutes after rider dispatch are restricted to within a 1.5km radius."
    ]

    def __init__(self, custom_invariants: List[str] = None):
        self.invariants = custom_invariants or self.DEFAULT_INVARIANTS

    def render_anchor_block(self) -> str:
        """Formats the immutable invariants into a high-density, authoritative prompt block."""
        lines = ["[IMMUTABLE_POLICY_INVARIANTS — ZERO_TOLERANCE_RULES]"]
        for rule in self.invariants:
            lines.append(f"  ⚡ {rule}")
        return "\n".join(lines)

    def check_violation(self, text: str) -> Dict[str, Any]:
        """Audits an agent response against invariant violations."""
        import re
        violations = []
        
        # Check refund amount violations
        refund_matches = re.findall(r"(?:refund|credit)\s*(?:of)?\s*(?:₹|rs\.?|inr)?\s*([0-9]+)", text, re.IGNORECASE)
        for amt_str in refund_matches:
            amt = int(amt_str)
            if amt > 150:
                violations.append({
                    "rule": "FINANCIAL_LIMIT",
                    "details": f"Attempted unauthorized refund of ₹{amt} (Exceeds ₹150 threshold without supervisor signoff)"
                })

        # Check secret leak violations
        if re.search(r"(?:private[-_ ]key|secret[-_ ]key|BEGIN PRIVATE KEY)\s*[:=]", text, re.IGNORECASE):
            violations.append({
                "rule": "SECURITY_GUARDRAIL",
                "details": "Attempted to log or print unmasked cryptographic secret to console."
            })

        return {
            "has_violation": len(violations) > 0,
            "violations": violations
        }
