# 🧹 ContextGC: Autonomous Semantic Context Defragmenter for AI Agents

> 🏆 **Top 50 Winner (Rank #46 out of ~1,500 Submissions)** at [*Hack Devengers 2.0*](https://unstop.com/hackathons/hack-devengers-20-devengers-1749441)  
> **Track:** Open Innovation (AI, Developer Tools & Automation)  
> **Author:** Jay Gopal Tripathy ([@j4yop](https://github.com/j4yop))  
> **Live Deployment:** [https://context-hackdevengers.vercel.app](https://context-hackdevengers.vercel.app)  
> **Interactive Pitch Deck:** [https://context-hackdevengers.vercel.app/presentation](https://context-hackdevengers.vercel.app/presentation)  
> **Submission Manifest:** [`SUBMISSION.md`](SUBMISSION.md)

[![Hack Devengers 2.0](https://img.shields.io/badge/Hack%20Devengers%202.0-Top%2050%20(Rank%20%2346)-ffd700.svg?style=flat&logo=target)](https://unstop.com/hackathons/hack-devengers-20-devengers-1749441)
[![CI Build](https://github.com/j4yop/context-hackdevengers/actions/workflows/ci.yml/badge.svg)](https://github.com/j4yop/context-hackdevengers/actions)
[![Live Demo](https://img.shields.io/badge/Demo-context--hackdevengers.vercel.app-emerald.svg)](https://context-hackdevengers.vercel.app)
[![Pitch Deck](https://img.shields.io/badge/Deck-6--Slide%20Presentation-cyan.svg)](https://context-hackdevengers.vercel.app/presentation)
[![Tests](https://img.shields.io/badge/Tests-27%20Passed-brightgreen.svg)]()
[![Track](https://img.shields.io/badge/Track-Open%20Innovation%20(AI%20%26%20DevTools)-blue.svg)]()
[![Python](https://img.shields.io/badge/Python-3.11+-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

---

> [!NOTE]
> ### 🏆 Hack Devengers 2.0 Leaderboard Recognition
> **ContextGC** was awarded **Rank #46 in the Top 50 Leaderboard** out of ~1,500 submissions at [Hack Devengers 2.0](https://unstop.com/hackathons/hack-devengers-20-devengers-1749441).  
> Recognized for its inline sub-3ms Neuro-Symbolic State DAG, semantic dead-branch garbage collection, and ~70% prompt token reduction for long-horizon AI agents.


---

## ⚡ The 30-Second Pitch for Hack Devengers Judges

Today's Large Language Models boast 1M+ token context windows. Yet in real-world multi-turn workflows—whether running autonomous coding agents that refactor multi-file repositories or high-velocity logistics bots handling dynamic reroutes—**agents quietly get dumber as their context fills up with operational junk**. This fatal industry phenomenon is called **Context Rot**.

When an autonomous coding agent encounters five terminal errors, an operations bot handles three address updates, and APIs return 5,000-token JSON blobs, models suffer attention collapse: they hallucinate, violate core business constraints, and burn unnecessary API costs.

**`ContextGC` fixes this at the systems level:**  
It acts as an inline, low-latency semantic garbage collector and defragmenter between enterprise agent interfaces and LLMs. It maintains a **Neuro-Symbolic State DAG** to prune dead conversational branches in sub-3ms, sanitizes verbose tool outputs into compact schemas, and archives cold history into **high-speed Vector Tables**.

* Slashes token consumption by **68.9% to 70.1%** (headline: **~70%**).
* Accelerates inference latency by **39.8% to 46.8%** (faster TTFT via prompt minimization).
* Guarantees **100% compliance** with system policy invariants.
* Supports **real-time SSE streaming (`stream: true`)** and **Radix Cache-Friendly prefix preservation**.

---

## 🎯 Answering the Hack Devengers 4 Litmus Tests

| Question | ContextGC Answer |
| :--- | :--- |
| **1. Why does this need to exist?** | Because 1M+ token windows don't prevent attention collapse; operational sludge makes models dumber, causes policy violations, and inflates enterprise token bills. |
| **2. Can someone use it tomorrow?** | **Yes.** Use either the 1-line Python SDK (`from core.client import defrag_context, patch_openai`) or point any agent framework (Cursor, LangChain, AutoGen) to the OpenAI-compatible reverse proxy (`/v1/chat/completions`) with full streaming support. |
| **3. What makes it different?** | While LangChain and CrewAI use recursive LLM summarizers that add 1.5s+ of latency and distort verbatim entity values, ContextGC uses an in-memory Neuro-Symbolic State DAG that runs deterministically in **< 3ms** with zero API calls. |
| **4. Can I demo it in 30 seconds?** | **Yes.** Launch the interactive split-screen dashboard to watch a live benchmark battle showing real-time token reduction flamegraphs and instant policy violation prevention. |

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    User([User / Developer / Agent Orchestrator]) -->|Multi-Turn Message Stream| Proxy[ContextGC Inline Proxy Engine]

    subgraph MemoryEngine [ContextGC Core Engine (<3ms Latency)]
        Proxy --> DAG[1. Neuro-Symbolic State DAG]
        DAG -->|Detects State Overrides| Pruner[Dead-Branch Pruning]
        
        Proxy --> Sanitizer[2. Tool Sanitizer & Distiller]
        Sanitizer -->|Collapses Verbose JSON & Stack Traces| Distill[Payload Distiller & Tombstoner]
        
        Proxy --> Anchor[3. Invariant Policy Anchor]
        Anchor -->|Pins Safety & Business Invariants| Recency[Recency Attention Anchor]
    end

    Pruner -->|Evicted Dead Turns| VectorTier[4. Episodic Vector Tier]
    
    subgraph StorageCloud [Episodic Memory Archive]
        VectorTier --> VectorTable[(AGENT_EPISODIC_ARCHIVE\nVECTOR 768)]
        VectorTable --> FastSearch[Sub-ms Vector Similarity Recall]
    end

    Pruner --> CleanPrompt[Bounded High-Signal Context\n< 900 Tokens | Sub-600ms Latency]
    Distill --> CleanPrompt
    Recency --> CleanPrompt

    CleanPrompt --> LLM[LLM Inference Engine\nOpenAI / Gemini / Anthropic]
    LLM --> Response([Deterministic Safe Response])

    FastSearch -.->|On Retrospective Query| CleanPrompt
```

---

## 🔬 The 6 Core Systems Features

### 1. Neuro-Symbolic State DAG (Dead-Branch Pruner)
* **Code:** [`core/state_dag.py`](file:///Users/jaygopal/context-hackdevengers/core/state_dag.py)
* Maintains an in-memory Directed Acyclic Graph of verified state assertions with negation and polarity awareness.
* Differentiates between **Mutable Slots** (file paths, configs, addresses, ports) and **Immutable Constraints** (dietary allergies, security invariants).
* When a mutable slot updates, prior turns are automatically flagged as `SUPERSEDED` and pruned from the prompt.
* **Transactional Rollback:** Supports `dag.rollback_to(turn_id)` to unwind failed reasoning loops cleanly.

### 2. Tool-Payload Distillation & Error Tombstoner
* **Code:** [`core/sanitizer.py`](file:///Users/jaygopal/context-hackdevengers/core/sanitizer.py)
* **Payload Compaction:** Multi-kilobyte JSON responses (4,000+ tokens) are parsed into essential semantic fields (under 50 tokens).
* **Error Tombstoning:** Stack traces and connection timeouts are kept only for the recovery turn, then replaced with an immutable tombstone: `[TOMBSTONE: Gateway timeout resolved at Turn 19 via fallback]`.

### 3. Episodic Vector Memory Tier
* **Code:** [`core/vector_tier.py`](file:///Users/jaygopal/context-hackdevengers/core/vector_tier.py)
* Evicted turns are never lost—they are asynchronously vectorized and indexed into vector tables (`AGENT_EPISODIC_ARCHIVE`).
* **JIT Retrieval:** When a retrospective query arrives, ContextGC executes cosine similarity search and retrieves only that specific 10-token record just-in-time.

### 4. Deterministic Policy Invariant Anchoring
* **Code:** [`core/anchors.py`](file:///Users/jaygopal/context-hackdevengers/core/anchors.py)
* Pins non-negotiable operational thresholds and security invariants at the recency position of the transformer.
* Eliminates "Lost-in-the-Middle" attention drift and guarantees 0% policy erosion.

### 5. Full SSE Streaming Reverse Proxy (`stream: true`)
* **Code:** [`server/main.py`](file:///Users/jaygopal/context-hackdevengers/server/main.py)
* Real-time Server-Sent Events proxy forwarding for Cursor, LangChain, and Claude Code with zero-latency streaming and defrag telemetry headers.

### 6. Cache-Aware Compactor Mode
* **Code:** [`core/gc_engine.py`](file:///Users/jaygopal/context-hackdevengers/core/gc_engine.py)
* Resolves the KV-Cache dilemma: choose between `mode="compact"` (max token reduction) and `mode="cache_friendly"` (preserves exact byte prefix for 100% KV-cache reuse on vLLM/OpenAI/Anthropic).

---

## 📊 Benchmark Results

Tested across two realistic multi-turn scenarios:
1. **Scenario 1: High-Velocity Logistics Incident** (11 turns with 504 timeouts, address updates, and refund claims)
2. **Scenario 2: Autonomous Coding Agent Refactoring** (Multi-file JWT refactor with Jest test tracebacks and 350-line package diffs)

| Metric | Vanilla LLM Agent (Rotted Context) | `ContextGC` Defragmented Agent | Improvement |
| :--- | :---: | :---: | :---: |
| **Active Prompt Tokens** | 1,000 – 1,592 tokens | **311 – 476 tokens** | **68.9% – 70.1% Reduction** |
| **Turn Inference Latency** | 750 – 898 ms | **454 – 487 ms** | **39.8% – 46.8% Faster** |
| **GC Interception Latency**| 0 ms | **2.5 – 15 ms** | **Deterministic In-Memory** |
| **Policy Invariant Violations** | 100% Failure Rate (Illegal refund / Private key dump) | **0% Violations (100% Compliant)** | **100% Policy Integrity** |
| **State Resolution Accuracy** | 0% (Hallucinated obsolete addresses/ports) | **100% (Settled DAG State)** | **Zero Hallucination** |
| **KV-Cache Prefix Preservation** | Broken on standard mutation | **100% Supported** | **Cache-Friendly Mode** |

---

## 🚀 Quickstart & Integration

### Option A: 1-Line Python Client SDK (Zero Proxy Overhead)
```python
from core.client import defrag_context, patch_openai
import openai

# 1. Direct Functional Defrag
clean_messages, telemetry = defrag_context(messages)

# 2. Transparent OpenAI SDK Auto-Patcher
client = openai.OpenAI()
patch_openai(client)
res = client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    stream=True  # Fully supported!
)
print("Tokens saved:", res.context_gc["tokens_saved"])
```

### Option B: Drop-in Reverse Proxy (`/v1/chat/completions`)
Point any agent framework (LangChain, AutoGen, CrewAI, LiteLLM, or Cursor) to ContextGC:

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://context-hackdevengers.vercel.app/v1",  # or http://localhost:8000/v1
    api_key="your-openai-api-key"
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    stream=True
)
```

### Option C: Run Local Test Suite (28 Tests)
```bash
pytest tests/test_engine.py -v
```

---

## 📂 Project Structure

```
context-hackdevengers/
├── .github/workflows/
│   └── ci.yml                        # GitHub Actions automated test workflow
├── core/
│   ├── anchors.py                    # Policy Invariant Anchoring & Violation Auditing
│   ├── client.py                     # Zero-overhead Python Client SDK & monkey-patcher
│   ├── gc_engine.py                  # Central ContextGC Defragmenter Controller
│   ├── sanitizer.py                  # Tool JSON Compaction & Traceback Tombstoning
│   ├── state_dag.py                  # Neuro-Symbolic State DAG & Causal Invalidation
│   └── vector_tier.py                # Episodic Vector Memory Tier & Cosine Recall
├── demo/
│   ├── DEMO_SCRIPT.md                # 90-Second Product Demo Video Script
│   └── interactive_demo.py           # Rich ANSI Terminal Benchmark Runner
├── presentation/
│   └── index.html                    # 6-Slide Agency-Grade Interactive Pitch Deck
├── scenarios/
│   ├── coding_agent_refactor.py      # Autonomous Coding Agent Benchmark
│   └── operations_dispatch_crisis.py # High-Velocity Operations Benchmark
├── server/
│   └── main.py                       # FastAPI Server, SSE Streaming Proxy, & Rollback API
├── tests/
│   └── test_engine.py                # 27 Unit & Integration Pytests (100% passing)
├── web/
│   └── index.html                    # Split-Screen Showdown Dashboard & Diff Sandbox
├── pyproject.toml                    # Package configuration & pytest settings
├── requirements.txt                  # Minimal Python dependencies
├── SUBMISSION.md                     # Turnkey Hack Devengers 2.0 Form Payload
└── README.md
```


---

## 🏆 Hack Devengers 2.0 Compliance Confirmation

* **Development Window:** Built during the official 24-hour Hack Devengers 2.0 hackathon period (Sept 19–20, 2026).
* **Originality:** Original systems architecture created by Jay Gopal Tripathy.
* **Permissive Access:** Public GitHub repository, public live deployment link, and unlisted demo walkthrough video.
