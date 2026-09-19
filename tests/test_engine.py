import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from core.state_dag import StateDAG, FactNode

from core.sanitizer import ToolSanitizer
from core.vector_tier import VectorMemoryTier
from core.anchors import PolicyInvariantAnchor
from core.gc_engine import ContextGCEngine
from scenarios.operations_dispatch_crisis import get_operations_crisis_session, get_expected_eval_criteria
from scenarios.coding_agent_refactor import get_coding_agent_session, get_coding_eval_criteria
from server.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

# ---------------------------------------------------------------------------
# 1. State DAG Unit Tests
# ---------------------------------------------------------------------------

def test_state_dag_operations_superseding():
    dag = StateDAG()
    # Turn 0: initial address
    dag.register_turn(0, "user", "Please deliver to Tower 4, Flat 902.")
    assert "destination_address" in dag.active_state
    assert dag.active_state["destination_address"].turn_index == 0

    # Turn 1: updated address
    dag.register_turn(1, "user", "Wait, change address to Clubhouse Security Desk.")
    assert dag.active_state["destination_address"].turn_index == 1
    assert "Clubhouse Security Desk" in dag.active_state["destination_address"].value
    
    # Turn 0 should now be prunable
    prunable = dag.get_prunable_turns()
    assert 0 in prunable
    assert 1 not in prunable

def test_state_dag_immutable_guardrails():
    dag = StateDAG()
    dag.register_turn(0, "user", "The customer has a severe peanut allergy: severe allergy peanuts.")
    assert "dietary_allergy" in dag.active_state
    allergy_node = dag.active_state["dietary_allergy"]
    assert allergy_node.is_immutable is True

    # Even if someone attempts to change or tamper in turn 1
    dag.register_turn(1, "user", "Actually allergy: none.")
    # Immutable entity must NOT be superseded
    assert dag.active_state["dietary_allergy"].turn_index == 0
    assert 0 not in dag.get_prunable_turns()

def test_state_dag_coding_agent_superseding():
    dag = StateDAG()
    # Turn 0: initial spec RSA-256, port 8080
    dag.register_turn(0, "user", "Refactor auth to use RSA-256 signatures on port 8080.")
    assert dag.active_state["signature_algorithm"].value == "RSA-256"

    # Turn 1: architecture switch to Ed25519 and port 9443
    dag.register_turn(1, "user", "Switch to Ed25519 signatures and change port from 8080 to 9443.")
    assert dag.active_state["signature_algorithm"].value == "Ed25519"
    assert dag.active_state["target_port"].value == "9443"
    assert 0 in dag.get_prunable_turns()

def test_state_dag_dynamic_schema_and_generic_kv():
    dag = StateDAG()
    # Test dynamic registration
    dag.register_entity_schema("payment_rail", [r"(?:pay with|rail:?)\s+(UPI|Stripe|Crypto)"])
    dag.register_turn(0, "user", "Please pay with UPI.")
    assert "payment_rail" in dag.active_state
    assert dag.active_state["payment_rail"].value == "UPI"

    # Override dynamic entity
    dag.register_turn(1, "user", "Actually pay with Stripe.")
    assert dag.active_state["payment_rail"].value == "Stripe"
    assert 0 in dag.get_prunable_turns()

    # Test generic KV extraction
    dag.register_turn(2, "user", "Please set timeout to 45s.")
    assert "config_timeout" in dag.active_state
    assert dag.active_state["config_timeout"].value == "45s"

    # Override generic KV
    dag.register_turn(3, "user", "Update timeout to 120s.")
    assert dag.active_state["config_timeout"].value == "120s"
    assert 2 in dag.get_prunable_turns()

# ---------------------------------------------------------------------------
# 2. Tool Sanitizer Unit Tests
# ---------------------------------------------------------------------------

def test_tool_sanitizer_json_compaction():
    sanitizer = ToolSanitizer()
    catalog_json = '{"items": [{"name": "Amul Butter 500g", "price": 285}, {"name": "Mother Dairy Milk 1L", "price": 68}, {"name": "Eggs 12pk", "price": 110}, {"name": "Bread", "price": 45}], "metadata": {"trace": "abc-123"}}'
    compacted, orig_toks, new_toks = sanitizer.distill_tool_payload(catalog_json, "catalog_search")
    assert new_toks < orig_toks
    assert "Amul Butter" in compacted
    assert "metadata" not in compacted

def test_tool_sanitizer_error_traceback_detection():
    sanitizer = ToolSanitizer()
    error_log = "Traceback (most recent call last):\n  File 'jwt.py', line 89 in sign\n    TypeError: crypto.createPrivateKey is not a function"
    assert sanitizer.is_error_payload(error_log) is True
    compacted, orig_toks, new_toks = sanitizer.distill_tool_payload(error_log, "pnpm_test_runner")
    assert "ToolError" in compacted or "TypeError" in compacted

def test_tool_sanitizer_tombstone():
    sanitizer = ToolSanitizer()
    tombstone = sanitizer.create_tombstone(turn_index=2, tool_name="jest_runner", resolved_turn=4)
    assert "TOMBSTONE: Tool 'jest_runner' failed at Turn 2" in tombstone
    assert "Turn 4" in tombstone

# ---------------------------------------------------------------------------
# 3. Vector Memory Tier Unit Tests
# ---------------------------------------------------------------------------

def test_vector_memory_tier():
    vec_tier = VectorMemoryTier(session_id="TEST-VEC-01")
    record = vec_tier.archive_turn(
        turn_index=2,
        role="system",
        content="TOOL_OUTPUT: Failed to dispatch rider due to heavy rain at Indiranagar cluster",
        reason="Obsolete weather failure"
    )
    assert len(vec_tier.archive_table) == 1
    assert len(record["embedding"]) == 768
    
    # Check SQL generation
    sql = vec_tier.get_sql_insert(record)
    assert "INSERT INTO AGENT_EPISODIC_ARCHIVE" in sql
    assert "TEST-VEC-01" in sql

    # Search archive
    results = vec_tier.search_archive("rider dispatch rain Indiranagar", top_k=1)
    assert len(results) == 1
    assert results[0]["turn_index"] == 2

# ---------------------------------------------------------------------------
# 4. Policy Invariant Anchor Unit Tests
# ---------------------------------------------------------------------------

def test_policy_invariants_rendering_and_violations():
    anchor = PolicyInvariantAnchor()
    rendered = anchor.render_anchor_block()
    assert "IMMUTABLE_POLICY_INVARIANTS" in rendered
    assert "FINANCIAL_LIMIT" in rendered
    assert "SECURITY_GUARDRAIL" in rendered

    # Safe response
    check_safe = anchor.check_violation("Issuing courtesy refund of ₹100 for delay.")
    assert check_safe["has_violation"] is False

    # Financial limit violation (> 150)
    check_violation = anchor.check_violation("Issuing full refund of ₹450 to appease customer.")
    assert check_violation["has_violation"] is True
    assert check_violation["violations"][0]["rule"] == "FINANCIAL_LIMIT"

    # Security leak violation
    check_leak = anchor.check_violation("Here is your token: private_key: secret-12345")
    assert check_leak["has_violation"] is True
    assert check_leak["violations"][0]["rule"] == "SECURITY_GUARDRAIL"

# ---------------------------------------------------------------------------
# 5. End-to-End GC Engine Integration Tests
# ---------------------------------------------------------------------------

def test_gc_engine_operations_crisis_session():
    engine = ContextGCEngine(session_id="SESSION-TEST-OPS")
    session = get_operations_crisis_session()
    result = engine.process_session(session)

    telemetry = result["telemetry"]
    assert telemetry["compression_ratio_pct"] > 5.0
    assert telemetry["tokens_saved"] > 0
    assert telemetry["gc_execution_time_ms"] < 25.0
    assert telemetry["context_gc_hallucination_risk_score"] == 0
    assert len(telemetry["active_state_slots"]) > 0

    # Ensure active state summary was injected
    cleaned_messages = result["cleaned_messages"]
    system_prompt = cleaned_messages[0]["content"]
    assert "ACTIVE_AGENT_STATE_DAG" in system_prompt
    assert "IMMUTABLE_POLICY_INVARIANTS" in system_prompt

def test_gc_engine_coding_agent_session():
    engine = ContextGCEngine(session_id="SESSION-TEST-CODING")
    session = get_coding_agent_session()
    result = engine.process_session(session, query_for_jit="package.json dependencies")

    telemetry = result["telemetry"]
    assert telemetry["compression_ratio_pct"] > 30.0
    assert "signature_algorithm" in telemetry["active_state_slots"]
    assert telemetry["active_state_slots"]["signature_algorithm"].lower() == "ed25519"
    assert telemetry["active_state_slots"]["target_port"] == "9443"


# ---------------------------------------------------------------------------
# 6. FastAPI Endpoints Integration Tests
# ---------------------------------------------------------------------------

def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["event"] == "Hack Devengers 2.0"

def test_api_scenarios():
    res = client.get("/api/scenarios")
    assert res.status_code == 200
    scenarios = res.json()
    assert len(scenarios) == 2
    ids = [s["id"] for s in scenarios]
    assert "operations" in ids
    assert "coding" in ids

def test_api_session():
    res = client.get("/api/session?scenario=coding")
    assert res.status_code == 200
    data = res.json()
    assert data["scenario"] == "coding"
    assert data["total_turns"] > 0

def test_api_simulate():
    payload = {"scenario": "coding"}
    res = client.post("/api/simulate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "telemetry" in data
    assert "comparison" in data
    assert data["comparison"]["context_gc"]["token_count"] < data["comparison"]["vanilla_llm"]["token_count"]

def test_api_benchmark_showdown():
    res = client.post("/api/benchmark-showdown?scenario=operations")
    assert res.status_code == 200
    data = res.json()
    assert "vanilla_agent" in data
    assert "context_gc_agent" in data
    assert data["vanilla_agent"]["policy_violation"] is True
    assert data["context_gc_agent"]["policy_violation"] is False
    assert data["deltas"]["tokens_saved"] > 0

def test_api_presentation():
    res = client.get("/presentation")
    assert res.status_code == 200
    assert "ContextGC" in res.text
    assert "Pitch" in res.text

def test_v1_models_endpoint():
    res = client.get("/v1/models")
    assert res.status_code == 200
    data = res.json()
    assert data["object"] == "list"
    ids = [m["id"] for m in data["data"]]
    assert "gpt-4o" in ids
    assert "context-gc-v2" in ids

def test_v1_chat_completions_endpoint():
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "Set cluster to us-east-1 and delivery to Gate 2."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "Wait, change cluster to ap-south-1."}
        ]
    }
    res = client.post("/v1/chat/completions", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["object"] == "chat.completion"
    assert "choices" in data
    assert len(data["choices"]) > 0
    assert "usage" in data
    assert "context_gc" in data["usage"]
    assert "context_gc" in data
    assert data["usage"]["context_gc"]["raw_prompt_tokens"] > 0

def test_vector_archive_auto_seeding():
    # Directly verify vector archive endpoint returns seeded table even on fresh calls
    res = client.get("/api/vector-archive?scenario=operations")
    assert res.status_code == 200
    data = res.json()
    assert data["table"] == "AGENT_EPISODIC_ARCHIVE"
    assert data["total_archived_turns"] > 0
    assert len(data["rows"]) > 0

    # Test search with auto-seeding
    search_res = client.post("/api/vector-archive/search", json={"query": "rain Indiranagar", "scenario": "operations"})
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["results_found"] > 0

# ---------------------------------------------------------------------------
# 6. Advanced Council Enhancements & Protocol Tests
# ---------------------------------------------------------------------------

def test_state_dag_negation_awareness():
    dag = StateDAG()
    dag.register_turn(0, "user", "Switch target port to 8080.")
    assert dag.active_state["target_port"].value == "8080"

    # Turn 1: user says "Do NOT switch to port 9443"
    dag.register_turn(1, "user", "Under no circumstances should you switch port to 9443, do not switch port to 9443.")
    # Port 8080 must remain active, 9443 must be ignored due to negation
    assert dag.active_state["target_port"].value == "8080"
    assert dag.active_state["target_port"].turn_index == 0

def test_state_dag_json_slot_extraction():
    dag = StateDAG()
    dag.register_turn(0, "user", 'Initialize microservice with config: {"database_cluster": "aurora-pg-01", "max_conns": 50}')
    assert "slot_database_cluster" in dag.active_state
    assert dag.active_state["slot_database_cluster"].value == "aurora-pg-01"

def test_state_dag_transactional_rollback():
    dag = StateDAG()
    dag.register_turn(0, "user", "Please deliver to Tower 4, Flat 902.")
    dag.register_turn(1, "user", "Wait, change address to Clubhouse Security Desk.")
    assert "Clubhouse" in dag.active_state["destination_address"].value

    # Roll back to turn 0
    rollback = dag.rollback_to(target_turn=0)
    assert rollback["rollback_target_turn"] == 0
    assert "Tower 4" in dag.active_state["destination_address"].value
    assert dag.active_state["destination_address"].turn_index == 0

def test_gc_engine_cache_friendly_mode():
    engine = ContextGCEngine(session_id="TEST-CACHE-01")
    messages = [
        {"role": "system", "content": "You are an enterprise logistics orchestrator."},
        {"role": "user", "content": "Deliver to Tower 4."},
        {"role": "user", "content": "Change address to Gate 2."}
    ]
    res = engine.process_session(messages, mode="cache_friendly")
    telemetry = res["telemetry"]
    assert telemetry["mode"] == "cache_friendly"
    assert telemetry["kv_cache_prefix_preserved"] is True
    # Ensure messages[0] system prompt was NOT mutated (prefix preserved)
    assert res["cleaned_messages"][0]["content"] == "You are an enterprise logistics orchestrator."
    # Ensure canonical state register was appended at tail
    assert any("[CANONICAL_TAIL_STATE_REGISTER]" in m["content"] for m in res["cleaned_messages"])

def test_client_sdk_defrag_context():
    from core.client import defrag_context
    messages = [
        {"role": "user", "content": "Set cluster to us-east-1 and deliver to Tower B."},
        {"role": "assistant", "content": "Acknowledged."},
        {"role": "user", "content": "Change address to Gate 1."}
    ]
    cleaned, telemetry = defrag_context(messages)
    assert len(cleaned) > 0
    assert telemetry["tokens_saved"] >= 0
    assert "active_state_slots" in telemetry

def test_v1_chat_completions_streaming():
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "Hello, plan delivery to Gate 2."}
        ],
        "stream": True
    }
    res = client.post("/v1/chat/completions", json=payload)
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("content-type", "")
    content = res.text
    assert "data: " in content
    assert "chat.completion.chunk" in content
    assert "[DONE]" in content
    assert "x-context-gc-tokens-saved" in res.headers

def test_api_dag_rollback_endpoint():
    res = client.post("/api/dag/rollback", json={"scenario": "operations", "target_turn": 0})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["target_turn"] == 0
    assert "rollback" in data

def test_council_report_endpoint():
    res = client.get("/council")
    assert res.status_code == 200
    assert "Council Report" in res.text
    assert "Chairman" in res.text


