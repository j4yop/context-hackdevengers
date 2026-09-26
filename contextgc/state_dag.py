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

from .state_protocol import escape_value

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

    #: Entity patterns, keyed by slot name.
    #:
    #: **Empty by default, and that is a measured decision rather than caution.**
    #: The previous default shipped a logistics schema -- `destination_address`,
    #: `refund_claim`, `gate_code` -- and applied it to everything. Run against
    #: 60 real SWE-agent trajectories it produced 75 facts, of which every
    #: sampled one was prose matched by accident:
    #:
    #:     destination_address = "of parentheses"
    #:     destination_address = "it, otherwise do a lookup using type"
    #:     destination_address = "a placeholder dictionary"
    #:
    #: The patterns were written to match a fixture, and a coding transcript is
    #: full of the words they look for. Shipping them as defaults meant any user
    #: outside that one scenario got confident nonsense for free.
    #:
    #: Opt in per domain:
    #:
    #:     dag.register_entity_schema("target_port", [r"port (?:to|is) (\d{2,5})"])
    #:
    #: or pass a schema mapping to the benchmark harness. The shipped schemas in
    #: See :func:`contextgc.load_schema` -- those are the ones that were
    #: actually measured against real transcripts.
    ENTITY_PATTERNS: Dict[str, List[str]] = {}

    #: Slots protected from being overwritten. Kept even though the default
    #: schema is empty, because a caller opting into ``dietary_allergy`` or
    #: ``security_invariant`` should get the protection without re-deriving it.
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
        #: Keys the agent explicitly pinned. Separate from ``is_immutable``,
        #: which also covers structural guardrails: a declared pin is lifted only
        #: by an explicit re-pin or a revoke, never by a bare assert.
        self.pinned_keys: Set[str] = set()
        #: Nodes of revoked keys, kept so :meth:`rollback_to` can restore them.
        self._revoked_history: Dict[str, List[FactNode]] = {}

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

    def register_turn(
        self,
        turn_index: int,
        role: str,
        content: str,
        skip_entities: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """
        Processes a turn, extracts fact mutations, and performs graph-level dead-branch invalidation.

        Args:
            skip_entities: keys already accounted for by an explicit declaration
                on this turn. A declared key lives inside a JSON payload, and
                without this the generic key-value and JSON extractors would match
                it out of its own markup and then supersede the declaration with
                a value inferred from the declaration.

        Returns a summary of active assertions and invalidated turns.
        """
        extracted = self.extract_entities(content, turn_index, role=role)
        if skip_entities:
            extracted = [n for n in extracted if n.entity not in skip_entities]
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

        **Precedence, independent of key order in the JSON:**
        ``revoke`` > ``unsure`` > ``pin`` > ``assert``.

        A key listed in more than one operation ends up governed by the highest.
        This is deliberate: a model that marks something both ``pin`` and
        ``assert`` is uncertain about its status, and uncertainty is the safer
        direction to resolve it in. A key in both ``assert`` and ``unsure`` is
        treated as unsettled, because the model said it was not sure.
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
        pinned_now = set((pins or {}).keys())
        return self._apply(
            nodes, turn_index, default_source=SOURCE_DECLARED, repinned=pinned_now
        )

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

        if entity in self.immutable_entities:
            # A structural guardrail cannot be voided by a declaration. The read
            # path protected these structurally; letting one JSON string delete
            # a safety constraint would be a strict downgrade.
            self.invalidation_log.append({
                "entity": entity,
                "turn": turn_index,
                "kind": "revoke_refused",
                "reason": f"refused to revoke {entity}: structural guardrail",
            })
            return False

        was_tracked = entity in self.active_state
        if not was_tracked:
            # Voiding a key the compiler never tracked is a no-op, not a tombstone.
            # Otherwise a stray revoke permanently disables inference for a key
            # that was never live.
            return False
        previous = self.active_state.pop(entity, None)
        # History is archived, not destroyed, so rollback_to can restore the key.
        # Deleting it here made the documented rollback behaviour impossible.
        self._revoked_history[entity] = list(self.nodes.get(entity, []))
        self.nodes.pop(entity, None)
        self.revoked_keys[entity] = {
            "turn": turn_index,
            "reason": reason,
            "was": previous.value if previous else None,
        }
        self.pinned_keys.discard(entity)
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
        repinned: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """Merge extracted nodes into the graph, honouring immutability and provenance."""
        superseded_turns = set()
        new_assertions = []
        rejected = []
        repinned = repinned or set()

        for node in extracted:
            if default_source and node.source == SOURCE_INFERRED:
                node.source = default_source

            # A revoked key stays revoked unless the agent re-asserts it on
            # purpose -- and then the tombstone goes away, so the register never
            # claims a key is both live and retired.
            if node.entity in self.revoked_keys:
                if node.source != SOURCE_DECLARED:
                    continue
                self.revoked_keys.pop(node.entity, None)

            if node.entity not in self.nodes:
                self.nodes[node.entity] = []

            if node.entity in self.active_state:
                prev_node = self.active_state[node.entity]

                # A protected key -- a structural guardrail (dietary_allergy,
                # security_invariant) or one the agent pinned -- is writable only
                # by an explicit re-pin in this same declaration. A bare assert
                # does not lift a pin: the model was told "later turns cannot
                # overwrite it", and honouring that is the whole point of pinning.
                if prev_node.is_immutable and node.entity not in repinned:
                    rejected.append({
                        "entity": node.entity,
                        "attempted_value": node.value,
                        "turn": turn_index,
                        "kind": "pinned_write_blocked",
                        "reason": (
                            f"{node.entity} is pinned; blocked a {node.source} write"
                        ),
                    })
                    self.invalidation_log.append(dict(rejected[-1]))
                    continue

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

            if node.entity in self.pinned_keys and node.entity not in repinned:
                # Keep the pin; the value changed but the protection did not.
                node.is_immutable = True
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
            if entry.get("new_turn", entry.get("turn", 0)) <= target_turn
        ]

        # A revocation is a state mutation like any other. Rolling back to a turn
        # *before* the revoke must bring the key back; rolling back to one after
        # it must leave it void.
        for entity, revoked_at in list(self.revoked_keys.items()):
            if revoked_at.get("turn", 0) <= target_turn:
                continue  # the revoke predates the target; it stands
            history = [
                n for n in self._revoked_history.get(entity, [])
                if n.turn_index <= target_turn
            ]
            self.revoked_keys.pop(entity, None)
            self.pinned_keys.discard(entity)
            if not history:
                continue
            self.nodes[entity] = list(history)
            for node in history:
                node.superseded_by = None
            self.active_state[entity] = history[-1]
            reverted_entities.append({
                "entity": entity,
                "restored_value": history[-1].value,
                "turn": history[-1].turn_index,
                "status": "revocation_rolled_back",
            })

        # The generic pass above already pruned `active_state` for keys with no
        # surviving node, so re-apply the restored ones.
        for entity in [e["entity"] for e in reverted_entities
                       if e.get("status") == "revocation_rolled_back"]:
            if entity not in self.active_state and self.nodes.get(entity):
                self.active_state[entity] = self.nodes[entity][-1]
        return {
            "rollback_target_turn": target_turn,
            "active_state": {k: v.value for k, v in self.active_state.items()},
            "reverted_entities": reverted_entities
        }

    def get_prunable_turns(self) -> Set[int]:
        """
        Turn indices that may be dropped from the prompt without losing evidence.

        A turn qualifies only if it holds no fact that is still the live value
        for its entity. Evicting a turn that uniquely supports a current fact
        would delete the conversational evidence while the fact stayed in the
        prompt as authoritative -- a half-pruned dead branch, where the model
        holds a value with no visible support for it.

        The converse error is just as bad and was the original defect: retiring
        a turn while its uniquely-asserted fact survives promotes that fact to
        authoritative with nothing behind it. Both directions are now measured
        by :meth:`get_retirement_violations`, which is a real check rather than
        an identity.
        """
        live_turns = {node.turn_index for node in self.active_state.values()}
        prunable = set()
        for entity, history in self.nodes.items():
            for node in history:
                if node.superseded_by is not None and not node.is_immutable:
                    if node.turn_index not in live_turns:
                        prunable.add(node.turn_index)
        return prunable

    def get_retirement_violations(self, proposed: Set[int]) -> List[Dict[str, Any]]:
        """
        Check a *proposed* set of retirements against the live state.

        This is a genuine invariant check, unlike its predecessor. The earlier
        ``get_orphaned_facts`` compared the prunable set against the live set
        and could therefore only ever return ``[]`` -- it asserted an identity,
        not a property, so the test suite "proving" it could not fail.

        Given the turns a caller intends to remove, this reports any live fact
        that would be left without conversational support. An empty list means
        the retirement is safe. A non-empty list means the caller must either
        keep those turns or drop the facts.

        Args:
            proposed: turn indices the caller is about to remove.
        """
        violations = []
        for entity, node in self.active_state.items():
            if node.turn_index in proposed:
                violations.append({
                    "entity": entity,
                    "value": node.value,
                    "sole_supporting_turn": node.turn_index,
                    "source": node.source,
                })
        return violations

    def would_orphan(self, turn_index: int) -> List[str]:
        """Entities whose only support is ``turn_index``. Cheap pre-flight check."""
        return [
            entity for entity, node in self.active_state.items()
            if node.turn_index == turn_index
        ]

    def get_active_state_summary(self, include_provenance: bool = True) -> str:
        """
        Render the current state for injection at the head of the context.

        Every value carries its provenance, so the model can tell a fact it
        declared itself apart from one a pattern guessed. This is load-bearing
        rather than decorative: the whole safety argument for the write path is
        that a *declared* fact is more trustworthy than a *guessed* one, and the
        model cannot act on that distinction if the register does not state it.

        An unsettled assertion is marked so it is not treated as settled, and
        values are escaped against both bracket and tag forgery -- this block is
        re-parsed on every compile, so an unescaped ``<contextgc-state>`` in a
        declared value would round-trip back in as a fresh declaration.
        """
        if not self.active_state:
            return ""
        lines = ["[ACTIVE_AGENT_STATE]"]
        for entity, node in sorted(self.active_state.items()):
            flags = []
            if node.is_immutable:
                flags.append("pinned")
            if node.confidence == UNSETTLED:
                flags.append("unsure")
            if include_provenance:
                flags.append("declared" if node.source == SOURCE_DECLARED else "inferred")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            lines.append(
                f"  - {escape_value(entity)} = \"{escape_value(node.value)}\""
                f" (turn {node.turn_index}{suffix})"
            )
        if self.revoked_keys:
            voided = ", ".join(escape_value(k) for k in sorted(self.revoked_keys)[:10])
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
