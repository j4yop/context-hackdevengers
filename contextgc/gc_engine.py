"""
ContextGC: deterministic context compiler for AI agent transcripts.

Compiles a message history into a smaller, non-self-contradicting context by
(a) tracking asserted entity state, (b) retiring superseded assertions,
(c) compacting tool payloads, and (d) pinning declared invariants.

Every number this module reports is measured at runtime. Nothing here is
estimated, projected, or modelled -- see ``telemetry`` at the bottom of
:meth:`ContextGCEngine.process_session`.
"""

import re
import time
from typing import Any, Dict, List, Optional

from .anchors import PolicyInvariantAnchor
from .sanitizer import ToolSanitizer
from .state_dag import SOURCE_DECLARED, SOURCE_INFERRED, StateDAG
from .state_protocol import (
    DECLARING_ROLES,
    StateDeclaration,
    declaration_counts,
    has_block,
    parse_declaration,
    render_instruction,
    strip_blocks,
)
from .vector_tier import VectorMemoryTier


def _strip_tool_calls(tool_calls: Any) -> Any:
    """
    Remove protocol markup from tool-call arguments.

    ``tool_calls`` is copied through structurally rather than as text, so the
    content strip never touched it and markup smuggled into a function's
    arguments reached the model verbatim.
    """
    if not isinstance(tool_calls, list):
        return tool_calls
    cleaned = []
    for call in tool_calls:
        if not isinstance(call, dict):
            cleaned.append(call)
            continue
        call = dict(call)
        function = call.get("function")
        if isinstance(function, dict) and isinstance(function.get("arguments"), str):
            function = dict(function)
            function["arguments"] = strip_blocks(function["arguments"])
            call["function"] = function
        cleaned.append(call)
    return cleaned


#: The state register this compiler injects. Recognised on input so a
#: re-compile replaces it instead of stacking a second, contradictory copy.


def _normalise_schema(schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Accept either a bare slot mapping or a whole schema file.

    ``benchmarks/schemas/*.json`` wrap their patterns in ``{"entities": ...}``
    and carry a ``_comment`` explaining how the patterns were arrived at. The
    benchmark CLI and the HTTP server both unwrapped that; the Python SDK did
    not, so ``compile_messages(schema=json.load(open(path)))`` -- the obvious
    thing to write, and what the other two entry points do internally -- raised
    ``re.PatternError: missing ), unterminated subpattern`` on the comment prose.

    Keys beginning with ``_`` are documentation, not entities.
    """
    if not schema:
        return {}
    raw = schema.get("entities") if isinstance(schema.get("entities"), dict) else schema
    out: Dict[str, Any] = {}
    for name, patterns in raw.items():
        if name.startswith("_"):
            continue
        if isinstance(patterns, str):
            patterns = [patterns]
        if not isinstance(patterns, (list, tuple)):
            # A slot with no patterns is a slot that cannot match. Keeping it
            # would only make the state register advertise an entity that can
            # never be filled.
            continue
        out[name] = [p for p in patterns if isinstance(p, str) and p]
    return out


class ContextGCEngine:
    """
    Compiles a conversation transcript into a bounded, high-signal context.

    Pure stdlib, no network, no model calls, deterministic for a given input.
    """

    #: The state register this compiler injects. Recognised on input so a
    #: re-compile replaces it rather than stacking a second, contradictory copy.
    #: Both spellings are listed because 0.1.0 emitted the ``_DAG`` form, and
    #: transcripts persisted by that version exist in the wild.
    REGISTER_MARKERS = ("[ACTIVE_AGENT_STATE]", "[ACTIVE_AGENT_STATE_DAG]")

    #: Ceiling on tracked facts. The read path is naturally bounded by its
    #: patterns; the write path is not, and an agent that re-declares its whole
    #: state every turn would otherwise inject thousands of tokens of system
    #: prompt and delete the conversation (every re-assert supersedes the last,
    #: so every declaring turn becomes prunable).
    MAX_TRACKED_FACTS = 64
    MAX_VALUE_CHARS = 512

    def __init__(
        self,
        session_id: str = "contextgc",
        invariants: Optional[List[str]] = None,
        schema: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            schema: entity patterns to enable, as
                ``{"slot_name": [pattern, ...], "__immutable__": (...)}``. The
                default is empty, because the shipped default used to be a
                logistics schema that matched prose in any other domain. See
                :attr:`StateDAG.ENTITY_PATTERNS`.

                A whole schema *file* may also be passed, i.e. the
                ``{"entities": {...}}`` shape used by ``benchmarks/schemas/``.
                Documentation keys such as ``_comment`` are ignored rather than
                compiled as patterns -- a schema's own prose is not a regex, and
                feeding it to ``re`` raises an opaque ``re.PatternError`` about
                unbalanced parentheses instead of saying what is wrong.
        """
        self.session_id = session_id
        self.schema = _normalise_schema(schema)
        self.dag = self._new_dag()
        self.sanitizer = ToolSanitizer()
        self.vector_tier = VectorMemoryTier(session_id)
        self.anchor = PolicyInvariantAnchor(invariants)
        self.turn_counter = 0

    def _declared_share(self) -> Optional[float]:
        """
        Share of active facts that were declared rather than inferred.

        Deliberately named ``declared_share`` and not an "authority" score. It
        measures provenance mix only. A declared fact always outranks an inferred
        one, so this value goes *up* when the model's opinion wins a conflict --
        it cannot be read as confidence in the result. ``conflicts`` is the
        signal that matters.

        ``None`` when nothing is tracked: an undefined ratio should not render as
        a failing 0%.
        """
        total = len(self.dag.active_state)
        if not total:
            return None
        declared = sum(1 for n in self.dag.active_state.values() if n.source == SOURCE_DECLARED)
        return round(declared / total, 3)

    @classmethod
    def _strip_prior_registers(cls, text: str) -> str:
        """
        Remove a state register we injected on an earlier pass.

        Without this, compiling already-compiled output produces two registers,
        the stale one first, and the prompt asserts two different current values
        for the same key. The 0.2.0 marker rename made this worse: a transcript
        persisted by 0.1.0 carries the old marker, so both spellings are matched.

        Line-based rather than index-based, so text *after* the register survives.
        A register runs from its marker until the first line that is not part of
        it: a blank line followed by anything, or a line that is not a ``- key =
        value`` entry.
        """
        if not text or not any(marker in text for marker in cls.REGISTER_MARKERS):
            return text

        lines = text.split("\n")
        out: List[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if not any(marker in line for marker in cls.REGISTER_MARKERS):
                out.append(line)
                index += 1
                continue

            # Skip the marker, then its indented entries, then one blank line.
            index += 1
            while index < len(lines) and re.match(
                r"^[ \t]*(?:- |[•*]\s|\(retired: )", lines[index]
            ):
                index += 1
            if index < len(lines) and not lines[index].strip():
                index += 1
        return "\n".join(out).strip()

    def _new_dag(self) -> StateDAG:
        """A fresh graph carrying this engine's entity schema.

        Built per invocation so nothing accumulates across calls, which means the
        schema has to be re-applied each time rather than set once in __init__.
        """
        dag = StateDAG()
        if self.schema:
            immutable = self.schema.get("__immutable__") or ()
            for name, patterns in self.schema.items():
                if name == "__immutable__":
                    continue
                dag.register_entity_schema(name, list(patterns))
            dag.immutable_entities.update(immutable)
        return dag

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
        self.dag = self._new_dag()
        self.vector_tier = VectorMemoryTier(self.session_id)

        raw_token_count = 0
        sanitized_tools_count = 0
        evicted_turns: List[int] = []
        declarations = []
        stripped_blocks = 0
        untrusted_blocks = 0
        conflicts: List[Dict[str, Any]] = []
        rejections: List[Dict[str, Any]] = []

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
            # Only the assistant may write to it: tool output is a fetched page
            # or an MCP result, user text may be a pasted injection or a quote of
            # our own documentation, and a system message is a summarised
            # transcript that inherits whatever those contained. Any of them
            # being able to assert authoritative state turns "declared" into a
            # mark of forgery rather than of authority.
            #
            # Markup in an untrusted role is still *stripped* -- the model must
            # never see protocol markup regardless of who wrote it -- but it is
            # counted and reported, never applied.
            present = has_block(content)
            if present:
                stripped_blocks += 1

            if role in DECLARING_ROLES:
                declaration = parse_declaration(content)
            elif present:
                untrusted_blocks += 1
                declaration = StateDeclaration()
                rejections.append({
                    "entity": "-",
                    "turn": idx,
                    "kind": "untrusted_declaration_ignored",
                    "reason": f"protocol markup in a {role!r} message was not applied",
                })
            else:
                declaration = StateDeclaration()

            declarations.append(declaration)

            reg_info = self.dag.register_declaration(
                idx, declaration.asserts, declaration.pins, declaration.unsure
            )
            rejections.extend(dict(r, turn=idx) for r in reg_info.get("rejected", []))
            for key in declaration.revokes:
                if not self.dag.revoke(key, idx, reason="revoked by agent declaration"):
                    rejections.append({
                        "entity": key,
                        "turn": idx,
                        "kind": "revoke_refused",
                        "reason": f"could not revoke {key}",
                    })

            # Inference sees the text with the protocol markup removed, so a
            # declared key is never also pattern-matched out of its own JSON.
            # Do not infer state from machine-generated output.
            #
            # A traceback that mentions a path is not a statement about which file
            # the agent is working on, and a grep listing is not an edit. Measured
            # on 40 real SWE-agent trajectories, every mislabelled extraction came
            # from exactly this: the pattern matched a filename inside a stack
            # trace or a search result and promoted it to "the file under edit".
            #
            # The declared path is unaffected -- only the agent may write there,
            # and it is reasoning about its own work rather than reading a blob.
            is_machine_output = self.sanitizer.looks_like_tool_output(content, role)
            inferrable = (
                strip_blocks(content)
                if has_block(content)
                else ("" if is_machine_output else content)
            )
            # A declared key must never be re-matched out of its own JSON, so
            # inference is told which keys are already accounted for.
            already = set(declaration.asserts) | set(declaration.pins) | set(declaration.unsure)
            inferred_info = self.dag.register_turn(
                idx, role, inferrable, skip_entities=already
            )
            rejections.extend(dict(r, turn=idx) for r in inferred_info.get("rejected", []))

            # Conflict: the agent declared a key and the transcript's own text
            # says something different. The declaration wins by design, so a
            # stale declaration silently outranks the user's correction -- this
            # is the only place that becomes visible.
            #
            # Detected from the *rejection*, not from new_assertions: a blocked
            # write never lands there, which is why this was previously invisible.
            for blocked in inferred_info.get("rejected", []):
                entity = blocked.get("entity")
                live = self.dag.active_state.get(entity) if entity else None
                if live is None or live.source != SOURCE_DECLARED:
                    continue
                attempted = blocked.get("attempted_value")
                if attempted is None or str(attempted) == str(live.value):
                    continue
                conflicts.append({
                    "entity": entity,
                    "declared": live.value,
                    "declared_turn": live.turn_index,
                    "inferred": str(attempted),
                    "inferred_turn": idx,
                    "note": "the declaration won; verify it is still correct",
                })

            tool_name = msg.get("name")
            if not tool_name:
                import re
                t_match = re.search(r"TOOL_OUTPUT\s*\[([a-zA-Z0-9_\-]+)\]", content)
                if t_match:
                    tool_name = t_match.group(1)

            # Drop a register we injected on a previous compile before doing
            # anything else with the content.
            if role == "system":
                content = self._strip_prior_registers(content)

            # Detected by content, not by a naming convention. Keying on
            # `role in (tool, function)` or a `TOOL_OUTPUT` tag found nothing in
            # the SWE-agent corpus, where tool output is filed as `user` and
            # untagged -- so the compactor silently did nothing on real data.
            is_tool_message = self.sanitizer.looks_like_tool_output(content, role)

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
        live_support_turns = {n.turn_index for n in self.dag.active_state.values()}

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
                # An error payload is a legitimate reason to drop the turn's
                # *content*, but only if the turn holds no live fact. Otherwise
                # the fact stays in the register with its evidence deleted --
                # the same half-pruned branch the prunable path guards against.
                if idx in live_support_turns:
                    item["superseded_turns"] = []
                else:
                    tombstone = self.sanitizer.create_tombstone(
                        idx, item.get("tool_name") or "Runtime/Test", len(annotated_turns) - 1
                    )
                    self.vector_tier.archive_turn(
                        idx, role, item["raw_content"], "Error traceback resolved"
                    )
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
                cleaned_msg["tool_calls"] = _strip_tool_calls(item["tool_calls"])
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

        # Bound the register before rendering it.
        dropped_keys = 0
        if len(self.dag.active_state) > self.MAX_TRACKED_FACTS:
            keep = sorted(
                self.dag.active_state.items(),
                key=lambda kv: (kv[1].source != SOURCE_DECLARED, kv[1].turn_index),
            )[: self.MAX_TRACKED_FACTS]
            dropped_keys = len(self.dag.active_state) - len(keep)
            for entity, _ in keep:
                self.dag.active_state[entity].value = str(
                    self.dag.active_state[entity].value
                )[: self.MAX_VALUE_CHARS]
            trimmed = dict(keep)
            for entity in list(self.dag.active_state):
                if entity not in trimmed:
                    del self.dag.active_state[entity]
            state_summary = self.dag.get_active_state_summary()
        for node in self.dag.active_state.values():
            if len(str(node.value)) > self.MAX_VALUE_CHARS:
                node.value = str(node.value)[: self.MAX_VALUE_CHARS]

        # A state register only helps if it is cheaper than the transcript it
        # replaces. Report the growth honestly instead of clamping to zero.
        verified = self._kv_prefix_len(messages, cleaned_messages)

        # Verified against the actual emitted sequence, not the requested mode.
        # `prefix_len` is how far the byte-identical prefix extends. The boolean
        # answers the question a caller actually has -- "is my cache still valid
        # for the whole conversation" -- not "is message[0] unchanged", which is
        # true even when everything after it was rewritten.
        prefix_len = verified
        kv_prefix_intact = prefix_len >= len(messages)
        growth = final_cleaned_tokens - raw_token_count

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
                # Positive means the compiled context is LARGER than the input.
                # The register can cost more than it saves on a short transcript,
                # and reporting that is the point: `compression_ratio_pct` is
                # clamped at 0 and would hide it.
                "token_growth": growth,
                "context_grew": growth > 0,
                "token_estimator": "chars/4 heuristic (not a BPE tokenizer)",

                # --- time, measured ---
                "compile_time_ms": round(elapsed_ms, 3),

                # --- structure, measured ---
                "retired_turn_indices": sorted(evicted_turns),
                "retired_turn_count": len(evicted_turns),
                "tool_payloads_compacted": sanitized_tools_count,
                "state_keys_dropped_over_limit": dropped_keys,

                # --- write-path provenance, measured ---
                "state": {
                    **self.dag.provenance_summary(),
                    "inferred_facts": sum(
                        1 for n in self.dag.active_state.values() if n.source == SOURCE_INFERRED
                    ),
                },
                "declarations": {
                    **declaration_counts(declarations),
                    "blocks_stripped": stripped_blocks,
                    # Markup found in a role that is not allowed to declare.
                    # Stripped from the prompt, never applied.
                    "blocks_in_untrusted_roles": untrusted_blocks,
                    # Provenance mix, not a quality score. A declared fact always
                    # wins a conflict, so a high value is *not* evidence the state
                    # is right -- see `conflicts` for that.
                    "declared_share": self._declared_share(),
                    "protocol_taught": teach_protocol,
                },
                # The agent asserted a key one way and a pattern matched it
                # another. This is the signal that correlates with a wrong state,
                # and it was previously computed and thrown away.
                "conflicts": conflicts,
                # Writes the compiler refused: pinned keys, lifted guardrails,
                # ignored untrusted markup. Also previously discarded.
                "rejected_writes": rejections,
                "active_state_slots": {k: v.value for k, v in self.dag.active_state.items()},
                # A real post-hoc check on the set we actually retired, not an
                # identity over the prunable set (which could only ever be empty).
                "retirement_violations": self.dag.get_retirement_violations(set(evicted_turns)),
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
