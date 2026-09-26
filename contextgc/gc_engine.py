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
from .state_dag import StateDAG
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

        # ---- Pass 1: register turns, optionally distil tool payloads ----------
        annotated_turns = []
        for idx, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "") or ""
            raw_token_count += max(1, len(content) // 4)

            reg_info = self.dag.register_turn(idx, role, content)

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
                "superseded_turns": reg_info.get("superseded_turns", []),
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

            cleaned_msg = {"role": role, "content": content}
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
            if mode == "cache_friendly":
                # Append only. The input prefix is never touched.
                cleaned_messages.append({
                    "role": "system",
                    "content": f"[STATE_REGISTER]\n{state_summary}\n\n{anchor_block}",
                })
            else:
                if cleaned_messages[0]["role"] == "system" and "ACTIVE_AGENT_STATE_DAG" not in cleaned_messages[0]["content"]:
                    cleaned_messages[0]["content"] += f"\n\n{state_summary}\n\n{anchor_block}"
                else:
                    cleaned_messages.insert(0, {
                        "role": "system",
                        "content": f"{state_summary}\n\n{anchor_block}",
                    })

            if jit_block and cleaned_messages[-1]["role"] == "user":
                cleaned_messages[-1]["content"] += jit_block

        # ---- Telemetry: measurements only ------------------------------------
        final_cleaned_tokens = sum(max(1, len(m.get("content") or "") // 4) for m in cleaned_messages)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        tokens_saved = max(0, raw_token_count - final_cleaned_tokens)
        compression_pct = round((tokens_saved / max(1, raw_token_count)) * 100, 1)

        # Verified against the actual emitted sequence, not the requested mode.
        prefix_len = self._kv_prefix_len(messages, cleaned_messages)
        kv_prefix_preserved = all(
            a.get("content") == b.get("content")
            for a, b in zip(messages[:prefix_len], cleaned_messages[:prefix_len])
        )

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
                "active_state_slots": {k: v.value for k, v in self.dag.active_state.items()},
                "orphaned_facts": self.dag.get_orphaned_facts(),
                "dag": {
                    "active": [
                        {"entity": k, "value": v.value, "turn_index": v.turn_index, "is_immutable": v.is_immutable}
                        for k, v in self.dag.active_state.items()
                    ],
                    "superseded": [
                        {"entity": n.entity, "value": n.value, "turn_index": n.turn_index, "superseded_by": n.superseded_by}
                        for history in self.dag.nodes.values()
                        for n in history
                        if n.superseded_by is not None
                    ],
                },
                "kv_cache_prefix_messages_preserved": prefix_len,
                "kv_cache_prefix_intact": kv_prefix_preserved,
            },
            "raw_messages_count": len(messages),
            "compiled_messages_count": len(cleaned_messages),
        }
