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


