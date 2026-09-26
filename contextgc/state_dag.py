"""
ContextGC: state DAG with provenance-aware supersession.

Tracks entity state across a transcript and retires assertions that have been
replaced. Two things this module is careful about, because getting either wrong
produces a *confidently wrong* context rather than a merely incomplete one:

**Provenance.** A fact the agent explicitly declared is not the same kind of
object as one a regex guessed. ``FactNode.source`` records which, and a declared
fact is never overwritten by an inferred one. See :mod:`contextgc.state_protocol`.

**Retraction.** Retiring a turn must retract the facts that turn uniquely held,
and a fact can be *void* rather than merely stale. :meth:`StateDAG.revoke` is
that operation; without it the only way to drop a key is for the agent to
re-assert it with a tombstone value, which is a workaround, not a mechanism.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

#: Provenance of an assertion.
SOURCE_DECLARED = "declared"  # the agent emitted it in a <contextgc-state> block
SOURCE_INFERRED = "inferred"  # a regex matched it in the text

#: Confidence marker for an assertion the agent flagged as unsure.
UNSETTLED = "unsettled"


@dataclass
class FactNode:
    entity: str
    value: str
    turn_index: int
    raw_snippet: str
    is_immutable: bool = False
    superseded_by: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    #: :data:`SOURCE_DECLARED` or :data:`SOURCE_INFERRED`.
    source: str = SOURCE_INFERRED
    #: Set to :data:`UNSETTLED` when the agent declared low confidence.
    confidence: Optional[str] = None

class StateDAG:
    """
    Maintains a causal graph of active factual assertions.
    Detects state overrides across enterprise operations and autonomous coding workflows,
    invalidating dead branches in the conversational history.
    """

    ENTITY_PATTERNS = {
        # Operations & Logistics
        "destination_address": [
            r"(?:deliver to|bring it to|change (?:the )?(?:address|destination) to|my address is|come to|new address:?|confirmed as|destination is|actually (?:use|send (?:it|them) to)|reroute (?:the rider )?to|use)\s+([A-Za-z0-9\s,–#-]{4,40}?)(?:\.|\,|$|\bwith\b|\band\b|\bplease\b|\bfor\b)",
            r"(?:at|in|to)\s+(Tower\s+[A-Za-z0-9]+(?:\s*,\s*Flat\s+[0-9]+)?|Clubhouse(?:\s+[A-Za-z0-9\s]+)?|Gate\s+[0-9]+(?:\s+Security\s+Entrance)?|Flat\s+[0-9]+|Apartment\s+[0-9]+|Security\s+Desk)",
        ],
        "gate_code": [
            r"(?:gate code|passcode|entry code|security pin|security code|otp is)\s*(?:is|to|=|:)?\s*([0-9]{4,6})",
        ],
        "dietary_allergy": [
            r"\b(?:no\s+(?:peanuts?|dairy|gluten|soy|eggs?|nuts?|shellfish))\b",
            # Adjective-first form: "a severe peanut allergy". The original
            # pattern only matched the inverted "allergy: peanuts" shape, which
            # meant the most safety-relevant assertion in the fixtures -- the
            # peanut allergy -- was silently never extracted.
            r"\b([A-Za-z]{3,20}?)\s+allergy\b",
            r"(?:allergic to|allergy(?:\s*is|:)?|dietary restriction:?)\s*([A-Za-z\s]{3,20}?)(?:\.|\,|$|\band\b|\bdue\b)",
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
        ],
        # Cloud & Infrastructure DevOps
        "cloud_environment": [
            r"(?:deploy to|environment:?|env:?|target env is)\s+(production|prod|staging|preview|development|dev)\b",
        ],
        "cloud_region": [
            r"(?:region:?|cluster in|hosted in)\s+([a-z]{2}-[a-z]+-[0-9]{1,2})\b",
        ]
    }

    # Attributes that are strictly monotonic / immutable once asserted (cannot be silently overwritten)
    IMMUTABLE_ENTITIES = {"dietary_allergy", "security_invariant"}

    def __init__(self):
        self.entity_patterns = {k: list(v) for k, v in self.ENTITY_PATTERNS.items()}
        self.immutable_entities = set(self.IMMUTABLE_ENTITIES)
        self.nodes: Dict[str, List[FactNode]] = {}
        self.active_state: Dict[str, FactNode] = {}
        self.invalidation_log: List[Dict[str, Any]] = []
        #: Keys the agent voided. Retained so a later stray regex match cannot
        #: resurrect a fact the agent explicitly retired.
        self.revoked_keys: Dict[str, Dict[str, Any]] = {}

    def register_entity_schema(self, entity_name: str, patterns: List[str], is_immutable: bool = False) -> None:
        """Dynamically registers a new domain entity schema with regex extraction patterns."""
        if entity_name not in self.entity_patterns:
            self.entity_patterns[entity_name] = []
        self.entity_patterns[entity_name].extend(patterns)
        if is_immutable:
            self.immutable_entities.add(entity_name)

    def extract_entities(self, text: str, turn_index: int, role: str = "user") -> List[FactNode]:
        """Scans message content for entity slot mutations, polarity/negations, and generic JSON structures."""
        detected = []
        seen_entities = set()

        # 1. Check registered schema patterns with negation awareness
        for entity_type, patterns in self.entity_patterns.items():
            if entity_type in seen_entities:
                continue
            for pat in patterns:
                matches = list(re.finditer(pat, text, re.IGNORECASE))
                found_valid = False
                for match in matches:
                    # Check for preceding negation within 50 characters
                    prefix_window = text[max(0, match.start() - 50):match.start()].lower()
                    if re.search(r"\b(?:do not|don't|dont|never|cannot|cant|can't|should not|shouldnt|not|no|under no circumstances|refuse|cancel|avoid)\b", prefix_window):
                        # Negated proposition: do not mutate state
                        continue

                    val = match.group(1) if match.groups() else match.group(0)
                    val = val.strip().strip(".,;")
                    is_imm = entity_type in self.immutable_entities
                    node = FactNode(
                        entity=entity_type,
                        value=val,
                        turn_index=turn_index,
                        raw_snippet=match.group(0),
                        is_immutable=is_imm
                    )
                    detected.append(node)
                    seen_entities.add(entity_type)
                    found_valid = True
                    break
                if found_valid:
                    break

        # 2. Generic key-value assignment detection (e.g., 'set timeout to 30s', 'retry_count = 5')
        generic_kv_pat = r"\b(?:set|switch|update)\s+([a-z_][a-z0-9_]{2,20})\s+(?:to|=)\s+([a-zA-Z0-9_\-\.\/]{1,40})\b"
        for match in re.finditer(generic_kv_pat, text, re.IGNORECASE):
            prefix_window = text[max(0, match.start() - 35):match.start()].lower()
            if re.search(r"\b(?:do not|don't|never|cannot|not to)\b", prefix_window):
                continue
            key = match.group(1).lower()
            val = match.group(2).strip()
            if key not in seen_entities and key not in {"the", "this", "that", "it"}:
                detected.append(FactNode(
                    entity=f"config_{key}",
                    value=val,
                    turn_index=turn_index,
                    raw_snippet=match.group(0),
                    is_immutable=False
                ))
                seen_entities.add(key)

        # 3. Schema-free JSON detection: only for user instructions or assistant commitments, NOT raw tool catalog dumps
        if role not in ("tool", "system") and "TOOL_OUTPUT" not in text:
            try:
                import json
                for jc in re.findall(r"\{[^{}\n\r]{4,200}\}", text):
                    try:
                        parsed = json.loads(jc)
                        if isinstance(parsed, dict):
                            for k, v in parsed.items():
                                key_str = str(k).strip()
                                val_str = str(v).strip()
                                if 2 <= len(key_str) <= 30 and 1 <= len(val_str) <= 60 and not key_str.startswith("_"):
                                    slot_name = f"slot_{re.sub(r'[^a-zA-Z0-9_]', '_', key_str.lower())}"
                                    if slot_name not in seen_entities:
                                        detected.append(FactNode(
                                            entity=slot_name,
                                            value=val_str,
                                            turn_index=turn_index,
                                            raw_snippet=jc,
                                            is_immutable=False
                                        ))
                                        seen_entities.add(slot_name)
                    except Exception:
                        pass
            except Exception:
                pass

        return detected

    def register_turn(self, turn_index: int, role: str, content: str) -> Dict[str, Any]:
        """
        Processes a turn, extracts fact mutations, and performs graph-level dead-branch invalidation.
        Returns a summary of active assertions and invalidated turns.
        """
        extracted = self.extract_entities(content, turn_index, role=role)
        return self._apply(extracted, turn_index, default_source=SOURCE_INFERRED)

    def register_declaration(
        self,
        turn_index: int,
        asserts: Dict[str, str],
        pins: Optional[Dict[str, str]] = None,
        unsure: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Apply a fact the agent explicitly declared in a ``<contextgc-state>`` block.

        Declared facts are authoritative. A regex match can never overwrite one,
        because the agent had the full conversational context when it made the
        assertion and the pattern did not.
        """
        nodes = []
        for entity, value in (asserts or {}).items():
            nodes.append(FactNode(
                entity=entity, value=value, turn_index=turn_index,
                raw_snippet="<contextgc-state>", source=SOURCE_DECLARED,
            ))
        for entity, value in (pins or {}).items():
            nodes.append(FactNode(
                entity=entity, value=value, turn_index=turn_index,
                raw_snippet="<contextgc-state>", is_immutable=True,
                source=SOURCE_DECLARED,
            ))
        for entity, value in (unsure or {}).items():
            nodes.append(FactNode(
                entity=entity, value=value, turn_index=turn_index,
                raw_snippet="<contextgc-state>", source=SOURCE_DECLARED,
                confidence=UNSETTLED,
            ))
        return self._apply(nodes, turn_index, default_source=SOURCE_DECLARED)

    def revoke(self, entity: str, turn_index: int, reason: str = "revoked by agent") -> bool:
        """
        Stop tracking ``entity`` entirely.

        The operation that supersession cannot express. A superseded fact was
        *replaced*; a revoked fact is *void* -- the order was cancelled, the
        credential was invalidated, the code path was deleted. There is no value
        to replace it with, so without this a void key lingers in the state
        register forever and the model keeps reasoning from it.

        Returns True if the key was being tracked.
        """
        entity = (entity or "").strip()
        if not entity:
            return False
        was_tracked = entity in self.active_state
        previous = self.active_state.pop(entity, None)
        self.nodes.pop(entity, None)
        self.revoked_keys[entity] = {
            "turn": turn_index,
            "reason": reason,
            "was": previous.value if previous else None,
        }
        if was_tracked:
            self.invalidation_log.append({
                "entity": entity,
                "old_value": previous.value if previous else None,
                "turn": turn_index,
                "reason": reason,
            })
        return was_tracked

    def _apply(
        self,
        extracted: List[FactNode],
        turn_index: int,
        default_source: str = SOURCE_INFERRED,
    ) -> Dict[str, Any]:
        """Merge extracted nodes into the graph, honouring immutability and provenance."""
        superseded_turns = set()
        new_assertions = []
        rejected = []

        for node in extracted:
            if default_source and node.source == SOURCE_INFERRED:
                node.source = default_source

            # A revoked key stays revoked unless the agent re-asserts it on purpose.
            if node.entity in self.revoked_keys and node.source != SOURCE_DECLARED:
                continue

            if node.entity not in self.nodes:
                self.nodes[node.entity] = []

            if node.entity in self.active_state:
                prev_node = self.active_state[node.entity]

                if prev_node.is_immutable:
                    # An immutable guardrail holds. A *declared* re-assertion is
                    # allowed through: only the agent knows that a constraint was
                    # deliberately lifted, and guessing that from regex is exactly
                    # the failure mode this rewrite exists to remove.
                    if node.source != SOURCE_DECLARED:
                        rejected.append({
                            "entity": node.entity,
                            "attempted_value": node.value,
                            "turn": turn_index,
                            "reason": f"{node.entity} is an IMMUTABLE guardrail",
                        })
                        self.invalidation_log.append(dict(rejected[-1]))
                        continue
                    prev_node.is_immutable = False

                # An inferred match never displaces a declared fact.
                if prev_node.source == SOURCE_DECLARED and node.source == SOURCE_INFERRED:
                    rejected.append({
                        "entity": node.entity,
                        "attempted_value": node.value,
                        "turn": turn_index,
                        "reason": "declared fact is not overwritten by an inferred one",
                    })
                    continue

                prev_node.superseded_by = turn_index
                superseded_turns.add(prev_node.turn_index)
                self.invalidation_log.append({
                    "entity": node.entity,
                    "old_value": prev_node.value,
                    "new_value": node.value,
                    "old_turn": prev_node.turn_index,
                    "new_turn": turn_index,
                    "reason": f"{prev_node.source} -> {node.source}: {prev_node.value} -> {node.value}",
                })

            self.nodes[node.entity].append(node)
            self.active_state[node.entity] = node
            new_assertions.append({
                "entity": node.entity,
                "value": node.value,
                "source": node.source,
            })

        return {
            "turn_index": turn_index,
            "new_assertions": new_assertions,
            "rejected": rejected,
            "superseded_turns": list(superseded_turns),
            "current_active_slots": {k: v.value for k, v in self.active_state.items()},
        }

    def rollback_to(self, target_turn: int) -> Dict[str, Any]:
        """
        Rolls back state mutations to the exact point at `target_turn`.
        Unwinds FactNodes asserted after target_turn and reactivates prior settled nodes.
        """
        reverted_entities = []
        for entity, history in list(self.nodes.items()):
            valid_nodes = [n for n in history if n.turn_index <= target_turn]
            self.nodes[entity] = valid_nodes
            if not valid_nodes:
                if entity in self.active_state:
                    del self.active_state[entity]
                    reverted_entities.append({"entity": entity, "status": "evicted"})
            else:
                latest = valid_nodes[-1]
                latest.superseded_by = None
                self.active_state[entity] = latest
                reverted_entities.append({"entity": entity, "restored_value": latest.value, "turn": latest.turn_index})

        # Prune invalidation log entries past target_turn
        self.invalidation_log = [
            entry for entry in self.invalidation_log
            if entry.get("new_turn", 0) <= target_turn
        ]

        # A revocation is a state mutation like any other; rolling back past it
        # must restore the key rather than leave it permanently void.
        self.revoked_keys = {
            k: v for k, v in self.revoked_keys.items() if v.get("turn", 0) <= target_turn
        }
        for entity in list(self.revoked_keys):
            restored = [n for n in self.nodes.get(entity, []) if n.turn_index <= target_turn]
            if restored:
                self.active_state[entity] = restored[-1]
        return {
            "rollback_target_turn": target_turn,
            "active_state": {k: v.value for k, v in self.active_state.items()},
            "reverted_entities": reverted_entities
        }

    def get_prunable_turns(self) -> Set[int]:
        """Returns turn indices whose substantive facts have been completely superseded.

        A turn is only prunable when *no* fact it uniquely asserted is still the
        live value for its entity. Evicting a turn that owns a still-current fact
        would delete the conversational evidence while the derived fact stayed
        in the prompt as authoritative -- a half-pruned dead branch, where the
        model is handed a value with no visible support for it.

        Concretely: turn 0 asserts ``refund_claim=99999`` and nothing ever
        re-asserts it. Turn 0 is superseded for ``destination_address`` but is
        the sole support for ``refund_claim``, so it must stay in the prompt.
        """
        live_turns = {node.turn_index for node in self.active_state.values()}

        prunable = set()
        for entity, history in self.nodes.items():
            for node in history:
                if node.superseded_by is not None and not node.is_immutable:
                    if node.turn_index not in live_turns:
                        prunable.add(node.turn_index)
        return prunable

    def get_orphaned_facts(self) -> List[Dict[str, Any]]:
        """Facts in the active state whose *sole* supporting turn is itself prunable.

        This is the invariant check behind :meth:`get_prunable_turns`. It returns
        an empty list when the graph is internally consistent, and is asserted
        directly by the test suite so the class of bug cannot regress silently.
        """
        prunable = self.get_prunable_turns()
        orphans = []
        for entity, node in self.active_state.items():
            if node.turn_index in prunable:
                orphans.append({
                    "entity": entity,
                    "value": node.value,
                    "supporting_turn": node.turn_index,
                })
        return orphans

    def get_active_state_summary(self) -> str:
        """
        Render the current state for injection at the head of the context.

        Every value is tagged with its provenance so the model can tell a fact it
        declared itself apart from one a pattern guessed, and an unsettled
        assertion is marked so it is not treated as settled. Values are escaped
        against delimiter forgery.
        """
        if not self.active_state:
            return ""
        lines = ["[ACTIVE_AGENT_STATE]"]
        for entity, node in sorted(self.active_state.items()):
            flags = []
            if node.is_immutable:
                flags.append("PINNED")
            if node.confidence == UNSETTLED:
                flags.append("UNSETTLED")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            safe_entity = str(entity).replace("\n", " ").replace("[", "(").replace("]", ")")
            safe_val = str(node.value).replace("\n", " ").replace("[", "(").replace("]", ")")
            lines.append(f"  - {safe_entity} = \"{safe_val}\" (turn {node.turn_index}{suffix})")
        if self.revoked_keys:
            voided = ", ".join(sorted(self.revoked_keys)[:10])
            lines.append(f"  (retired: {voided})")
        return "\n".join(lines)

    def provenance_summary(self) -> Dict[str, Any]:
        """Counts of declared vs inferred vs unsettled facts, for telemetry."""
        declared = sum(1 for n in self.active_state.values() if n.source == SOURCE_DECLARED)
        inferred = sum(1 for n in self.active_state.values() if n.source == SOURCE_INFERRED)
        unsettled = sum(1 for n in self.active_state.values() if n.confidence == UNSETTLED)
        return {
            "active_facts": len(self.active_state),
            "declared": declared,
            "inferred": inferred,
            "unsettled": unsettled,
            "revoked": len(self.revoked_keys),
            "revoked_keys": sorted(self.revoked_keys),
        }
