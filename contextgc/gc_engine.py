"""
ContextGC: deterministic context compiler for AI agent transcripts.

Compiles a message history into a smaller, non-self-contradicting context by
(a) tracking asserted entity state, (b) retiring superseded assertions,
(c) compacting tool payloads, and (d) pinning declared invariants.

Every number this module reports is measured at runtime. Nothing here is
estimated, projected, or modelled -- see ``telemetry`` at the bottom of
:meth:`ContextGCEngine.process_session`.
"""

import time
from typing import Any, Dict, List, Optional

from .anchors import PolicyInvariantAnchor
from .sanitizer import ToolSanitizer
from .state_dag import SOURCE_DECLARED, StateDAG
from .state_protocol import (
    declaration_counts,
    has_block,
    parse_declaration,
    render_instruction,
    strip_blocks,
)
from .vector_tier import VectorMemoryTier


class ContextGCEngine:
    """
    Compiles a conversation transcript into a bounded, high-signal context.

    Pure stdlib, no network, no model calls, deterministic for a given input.
    """

    def __init__(self, session_id: str = "contextgc", invariants: Optional[List[str]] = None):
        self.session_id = session_id
        self.dag = StateDAG()
        self.sanitizer = ToolSanitizer()
        self.vector_tier = VectorMemoryTier(session_id)
        self.anchor = PolicyInvariantAnchor(invariants)
        self.turn_counter = 0

    def _authority_ratio(self) -> Optional[float]:
        """Share of active facts that were declared rather than inferred.

        ``None`` when nothing is being tracked -- an undefined ratio is more
        honest than reporting 0.0 for "no facts exist".
        """
        total = len(self.dag.active_state)
        if not total:
            return None
        declared = sum(1 for n in self.dag.active_state.values() if n.source == SOURCE_DECLARED)
        return round(declared / total, 3)

    @staticmethod
    def _kv_prefix_len(original: List[Dict[str, Any]], compiled: List[Dict[str, Any]]) -> int:
        """Length of the byte-identical message prefix shared by both sequences."""
        n = 0
        for a, b in zip(original, compiled):
            if a.get("role") != b.get("role") or a.get("content") != b.get("content"):
                break
            n += 1
        return n

    def process_session(
        self,
        messages: List[Dict[str, str]],
        query_for_jit: Optional[str] = None,
        mode: str = "compact",
        teach_protocol: bool = False,
    ) -> Dict[str, Any]:
        """
        Compiles a message history.

        Modes:
            - ``"compact"`` (default): retire superseded turns and inline the
              current state at the head. Maximises reduction.
            - ``"cache_friendly"``: emit the input prefix byte-for-byte and append
              the state register at the tail, so a KV/prefix cache keyed on the
              untouched prefix still hits. Tool payloads are passed through
              verbatim in this mode -- distilling them would mutate the prefix and
              invalidate the very cache this mode exists to protect.

        Args:
            teach_protocol: prepend the state-protocol instruction to the system
              prompt, teaching the agent to declare its own state changes. Costs a
              few tokens per turn and buys authoritative provenance in return.

        Returns ``{"cleaned_messages", "telemetry", ...}``. Every telemetry field
        is a runtime measurement.
        """
        start_time = time.perf_counter()

        if mode not in ("compact", "cache_friendly"):
            raise ValueError(f"mode must be 'compact' or 'cache_friendly', got {mode!r}")

        # Per-invocation state. Nothing is carried across calls, so a long-lived
        # process cannot accumulate unbounded archive rows.
        self.dag = StateDAG()
        self.vector_tier = VectorMemoryTier(self.session_id)

        raw_token_count = 0
        sanitized_tools_count = 0
        evicted_turns: List[int] = []
        declarations = []
        stripped_blocks = 0

        # ---- Pass 1: read declarations, then infer what was not declared -----
        # Declarations are applied first and are authoritative. A regex match is
        # a guess about text; a declaration is the agent reporting on its own
        # reasoning, and the agent had the whole conversation when it made it.
        annotated_turns = []
        for idx, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "") or ""
            raw_token_count += max(1, len(content) // 4)

            # Protocol markup is a channel to the compiler, not to the model.
            declaration = parse_declaration(content)
            if has_block(content):
                stripped_blocks += 1
            declarations.append(declaration)

            reg_info = self.dag.register_declaration(
                idx, declaration.asserts, declaration.pins, declaration.unsure
            )
            for key in declaration.revokes:
                self.dag.revoke(key, idx, reason="revoked by agent declaration")

            # Inference sees the text with the protocol markup removed, so a
            # declared key is never also pattern-matched out of its own JSON.
            inferrable = strip_blocks(content) if has_block(content) else content
            inferred_info = self.dag.register_turn(idx, role, inferrable)

            tool_name = msg.get("name")
            if not tool_name:
                import re
                t_match = re.search(r"TOOL_OUTPUT\s*\[([a-zA-Z0-9_\-]+)\]", content)
                if t_match:
                    tool_name = t_match.group(1)

            is_tool_message = (
                role in ("function", "tool")
                or "TOOL_OUTPUT" in content
                or (role == "system" and ("{" in content or "FAIL" in content or "diff --git" in content))
            )

            # Prefix safety: only mutate tool payloads when the caller has opted
            # out of prefix preservation.
            compacted_content = content
            if is_tool_message and mode == "compact":
                compacted_content, orig_toks, new_toks = self.sanitizer.distill_tool_payload(content, tool_name)
                if new_toks < orig_toks:
                    sanitized_tools_count += 1

            annotated_turns.append({
                "index": idx,
                "role": role,
                "raw_content": content,
                "compacted_content": compacted_content,
                "tool_name": tool_name,
                "name": msg.get("name"),
                "tool_call_id": msg.get("tool_call_id"),
                "tool_calls": msg.get("tool_calls"),
                "superseded_turns": list(reg_info.get("superseded_turns", []))
                + list(inferred_info.get("superseded_turns", [])),
                "stripped": has_block(content),
            })

        # ---- Pass 2: find retired branches ----------------------------------
        prunable_indices = self.dag.get_prunable_turns()

        cleaned_messages: List[Dict[str, Any]] = []
        state_summary = self.dag.get_active_state_summary()
        anchor_block = self.anchor.render_anchor_block()

        for item in annotated_turns:
            idx = item["index"]
            role = item["role"]
            content = item["compacted_content"]
            tool_call_id = item.get("tool_call_id")
            name = item.get("name")

            if mode == "compact" and idx in prunable_indices and idx < len(annotated_turns) - 2:
                # `get_prunable_turns` already guarantees this turn supports no
                # live fact, so retiring it cannot orphan a value.
                self.vector_tier.archive_turn(
                    idx, role, item["raw_content"],
                    "Superseded entity state retired",
                )
                evicted_turns.append(idx)

                # PROTOCOL SAFETY: dropping a tool result that carries a
                # tool_call_id causes an upstream HTTP 400 (unmatched
                # tool_call_id). Keep a tombstone that preserves the id.
                if role == "tool" and tool_call_id:
                    cleaned_messages.append({
                        "role": role,
                        "content": f"[TOMBSTONE: Superseded tool call {tool_call_id} output retired]",
                        "tool_call_id": tool_call_id,
                        **({"name": name} if name else {}),
                    })
                continue

            if (
                mode == "compact"
                and (self.sanitizer.is_error_payload(content) or self.sanitizer.is_error_payload(item["raw_content"]))
                and idx < len(annotated_turns) - 2
            ):
                tombstone = self.sanitizer.create_tombstone(
                    idx, item.get("tool_name") or "Runtime/Test", len(annotated_turns) - 1
                )
                self.vector_tier.archive_turn(idx, role, item["raw_content"], "Error traceback resolved")
                evicted_turns.append(idx)
                cleaned_msg = {"role": role, "content": tombstone}
                if tool_call_id:
                    cleaned_msg["tool_call_id"] = tool_call_id
                if name:
                    cleaned_msg["name"] = name
                cleaned_messages.append(cleaned_msg)
                continue

            # The model must never see protocol markup. It is a channel to the
            # compiler, and feeding it back would grow the transcript every turn.
            cleaned_msg = {"role": role, "content": strip_blocks(content) if item.get("stripped") else content}
            if tool_call_id:
                cleaned_msg["tool_call_id"] = tool_call_id
            if name:
                cleaned_msg["name"] = name
            if item.get("tool_calls"):
                cleaned_msg["tool_calls"] = item["tool_calls"]
            cleaned_messages.append(cleaned_msg)

        # ---- Pass 3: JIT recall, now that the archive is actually populated ---
        # Previously this ran *before* the eviction loop, so on a fresh engine the
        # archive was empty and the recall block was unreachable in the SDK path.
        jit_block = ""
        if query_for_jit:
            hits = self.vector_tier.search(query_for_jit, top_k=1)
            if hits:
                # Escape: this text originates in attacker-controlled transcript
                # content and is injected into a live user turn.
                def _esc(s: str) -> str:
                    return str(s).replace("\n", " ").replace("[", "(").replace("]", ")")
                jit_block = (
                    f"\n[RETIRED_TURN_RECALL turn={hits[0]['turn_index']} "
                    f"role={_esc(hits[0]['role'])}]: {_esc(hits[0]['compact_summary'])}"
                )

        # ---- Pass 4: inject the state register -------------------------------
        if cleaned_messages:
            tail_extra = ""
            if teach_protocol:
                instruction = render_instruction(sorted(self.dag.active_state)[:12])
                if mode == "cache_friendly":
                    # Appending only: touching messages[0] would mutate the very
                    # prefix this mode exists to keep cacheable.
                    tail_extra += f"{instruction}\n\n"
                elif cleaned_messages[0]["role"] == "system":
                    cleaned_messages[0]["content"] += f"\n\n{instruction}"
                else:
                    cleaned_messages.insert(0, {"role": "system", "content": instruction})

            if mode == "cache_friendly":
                # Append only. The input prefix is never touched.
                cleaned_messages.append({
                    "role": "system",
                    "content": f"{tail_extra}[STATE_REGISTER]\n{state_summary}\n\n{anchor_block}".strip(),
                })
            else:
                head = f"{state_summary}\n\n{anchor_block}".strip()
                first = cleaned_messages[0]
                if first["role"] == "system" and "[ACTIVE_AGENT_STATE]" not in first["content"]:
                    first["content"] += f"\n\n{head}"
                else:
                    cleaned_messages.insert(0, {"role": "system", "content": head})

            if jit_block and cleaned_messages[-1]["role"] == "user":
                cleaned_messages[-1]["content"] += jit_block

        # ---- Telemetry: measurements only ------------------------------------
        final_cleaned_tokens = sum(max(1, len(m.get("content") or "") // 4) for m in cleaned_messages)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        tokens_saved = max(0, raw_token_count - final_cleaned_tokens)
        compression_pct = round((tokens_saved / max(1, raw_token_count)) * 100, 1)

        # Verified against the actual emitted sequence, not the requested mode.
        # `prefix_len` is how far the byte-identical prefix extends. The boolean
        # answers the question a caller actually has -- "is my cache still valid
        # for the whole conversation" -- not "is message[0] unchanged", which is
        # true even when everything after it was rewritten.
        prefix_len = self._kv_prefix_len(messages, cleaned_messages)
        kv_prefix_intact = prefix_len >= len(messages)

        return {
            "cleaned_messages": cleaned_messages,
            "telemetry": {
                "session_id": self.session_id,
                "mode": mode,

                # --- size, measured ---
                "raw_token_count": raw_token_count,
                "compiled_token_count": final_cleaned_tokens,
                "tokens_saved": tokens_saved,
                "compression_ratio_pct": compression_pct,
                "token_estimator": "chars/4 heuristic (not a BPE tokenizer)",

                # --- time, measured ---
                "compile_time_ms": round(elapsed_ms, 3),

                # --- structure, measured ---
                "retired_turn_indices": sorted(evicted_turns),
                "retired_turn_count": len(evicted_turns),
                "tool_payloads_compacted": sanitized_tools_count,

                # --- write-path provenance, measured ---
                "state": self.dag.provenance_summary(),
                "declarations": {
                    **declaration_counts(declarations),
                    "blocks_stripped": stripped_blocks,
                    # Share of tracked facts that came from the agent rather than
                    # a regex. 1.0 means the write path is fully adopted; 0.0
                    # means nothing declared anything and every fact is a guess.
                    "authority_ratio": self._authority_ratio(),
                    "protocol_taught": teach_protocol,
                },
                "active_state_slots": {k: v.value for k, v in self.dag.active_state.items()},
                "orphaned_facts": self.dag.get_orphaned_facts(),
                "dag": {
                    "active": [
                        {
                            "entity": k,
                            "value": v.value,
                            "turn_index": v.turn_index,
                            "is_immutable": v.is_immutable,
                            "source": v.source,
                            "confidence": v.confidence,
                        }
                        for k, v in self.dag.active_state.items()
                    ],
                    "revoked": [
                        {"entity": k, "was": v.get("was"), "turn": v.get("turn"), "reason": v.get("reason")}
                        for k, v in sorted(self.dag.revoked_keys.items())
                    ],
                    "superseded": [
                        {"entity": n.entity, "value": n.value, "turn_index": n.turn_index,
                         "superseded_by": n.superseded_by, "source": n.source}
                        for history in self.dag.nodes.values()
                        for n in history
                        if n.superseded_by is not None
                    ],
                },
                "kv_cache_prefix_messages_preserved": prefix_len,
                "kv_cache_prefix_intact": kv_prefix_intact,
            },
            "raw_messages_count": len(messages),
            "compiled_messages_count": len(cleaned_messages),
        }
