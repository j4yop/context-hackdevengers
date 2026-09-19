"""
ContextGC: Neuro-Symbolic State DAG & Dead-Branch Invalidation Engine
Tracks entity state mutations across multi-turn agent sessions.
Identifies when new turns supersede prior facts and prunes obsolete context tokens.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any
import re
import time

@dataclass
class FactNode:
    entity: str
    value: str
    turn_index: int
    raw_snippet: str
    is_immutable: bool = False
    superseded_by: Optional[int] = None
    created_at: float = field(default_factory=time.time)

class StateDAG:
    """
    Maintains a causal graph of active factual assertions.
    Detects state overrides across enterprise operations and autonomous coding workflows,
    invalidating dead branches in the conversational history.
    """
    
    ENTITY_PATTERNS = {
        # Operations & Logistics
        "destination_address": [
            r"(?:deliver to|bring it to|change address to|my address is|come to|new address:?)\s+([A-Za-z0-9\s,–#-]{4,40})",
            r"(?:at|in)\s+(Tower\s+[A-Za-z0-9]+|Clubhouse|Gate\s+[0-9]+|Flat\s+[0-9]+|Apartment\s+[0-9]+|Security\s+Desk)",
        ],
        "gate_code": [
            r"(?:gate code|passcode|entry code|security pin|otp is)\s*(?:is|:)?\s*([0-9]{4,6})",
        ],
        "dietary_allergy": [
            r"(?:allergic to|allergy:?|no peanuts|severe allergy|dietary restriction:?)\s*([A-Za-z\s]+)",
        ],
        "substitute_choice": [
            r"(?:substitute with|replace (?:it|that) with|give me|swap for)\s+([A-Za-z0-9\s]+?(?:milk|butter|bread|paneer|curd|egg|chips|oil|rice|coke))",
        ],
        "refund_claim": [
            r"(?:refund|credit back|give my money back|chargeback)\s*(?:of|for)?\s*(?:₹|rs\.?|inr)?\s*([0-9]+)",
        ],
        # Autonomous Software Engineering & DevTools
        "signature_algorithm": [
            r"\b(RSA-256|Ed25519|HMAC-SHA256|ECDSA)\b",
        ],
        "target_port": [
            r"(?:(?:switch|change)?\s*(?:target\s*)?port\s*(?:from\s*[0-9]+\s*)?to|target (?:microservice )?port (?:to|is)?|listening on port|port\s*:?)\s*([0-9]{2,5})",
        ],
        "security_invariant": [
            r"(NEVER log (?:the )?[A-Za-z0-9_\s]+in plaintext)",
        ]

    }

    # Attributes that are strictly monotonic / immutable once asserted (cannot be silently overwritten)
    IMMUTABLE_ENTITIES = {"dietary_allergy", "security_invariant"}


    def __init__(self):
        self.nodes: Dict[str, List[FactNode]] = {}
        self.active_state: Dict[str, FactNode] = {}
        self.invalidation_log: List[Dict[str, Any]] = []

    def extract_entities(self, text: str, turn_index: int) -> List[FactNode]:
        """Scans message content for entity slot mutations."""
        detected = []
        for entity_type, patterns in self.ENTITY_PATTERNS.items():
            for pat in patterns:
                matches = re.finditer(pat, text, re.IGNORECASE)
                for match in matches:
                    val = match.group(1) if match.groups() else match.group(0)
                    val = val.strip().strip(".,;")
                    is_imm = entity_type in self.IMMUTABLE_ENTITIES
                    node = FactNode(
                        entity=entity_type,
                        value=val,
                        turn_index=turn_index,
                        raw_snippet=match.group(0),
                        is_immutable=is_imm
                    )
                    detected.append(node)
                    break
        return detected

    def register_turn(self, turn_index: int, role: str, content: str) -> Dict[str, Any]:
        """
        Processes a turn, extracts fact mutations, and performs graph-level dead-branch invalidation.
        Returns a summary of active assertions and invalidated turns.
        """
        extracted = self.extract_entities(content, turn_index)
        superseded_turns = set()
        new_assertions = []

        for node in extracted:
            if node.entity not in self.nodes:
                self.nodes[node.entity] = []

            # Check if this overrides an existing active fact
            if node.entity in self.active_state:
                prev_node = self.active_state[node.entity]
                if not prev_node.is_immutable:
                    # Invalidate previous node
                    prev_node.superseded_by = turn_index
                    superseded_turns.add(prev_node.turn_index)
                    self.invalidation_log.append({
                        "entity": node.entity,
                        "old_value": prev_node.value,
                        "new_value": node.value,
                        "old_turn": prev_node.turn_index,
                        "new_turn": turn_index,
                        "reason": f"Active state mutation: {prev_node.value} -> {node.value}"
                    })
                    self.nodes[node.entity].append(node)
                    self.active_state[node.entity] = node
                    new_assertions.append({"entity": node.entity, "value": node.value})
                else:
                    # Previous node is an immutable guardrail! Reject override!
                    self.invalidation_log.append({
                        "entity": node.entity,
                        "attempted_value": node.value,
                        "turn": turn_index,
                        "reason": f"Rejected mutation: {node.entity} is an IMMUTABLE guardrail."
                    })
            else:
                self.nodes[node.entity].append(node)
                self.active_state[node.entity] = node
                new_assertions.append({"entity": node.entity, "value": node.value})


        return {
            "turn_index": turn_index,
            "new_assertions": new_assertions,
            "superseded_turns": list(superseded_turns),
            "current_active_slots": {k: v.value for k, v in self.active_state.items()}
        }

    def get_prunable_turns(self) -> Set[int]:
        """Returns turn indices whose substantive facts have been completely superseded."""
        prunable = set()
        for entity, history in self.nodes.items():
            for node in history:
                if node.superseded_by is not None and not node.is_immutable:
                    prunable.add(node.turn_index)
        return prunable

    def get_active_state_summary(self) -> str:
        """Returns a consolidated state representation for prompt injection."""
        if not self.active_state:
            return ""
        lines = ["[ACTIVE_AGENT_STATE_DAG]"]
        for entity, node in sorted(self.active_state.items()):
            imm_flag = " (IMMUTABLE)" if node.is_immutable else ""
            lines.append(f"  • {entity}: \"{node.value}\" [Settled Turn {node.turn_index}{imm_flag}]")
        return "\n".join(lines)
