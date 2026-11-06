# Developer Log: GuardEdge-K8s

## Entry #1: 2026-11-06 — Phase 0: Environment & Repository Scaffolding + Modular Ablation State Design

### 1. Objective
Establish the foundational environment, directory layout, dependency specifications, configuration flags, and typed state management for **GuardEdge-K8s** (*Policy-Enforced and Adversarial-Resilient Agentic Orchestration for Cloud-Native Kubernetes Clusters*).

### 2. Repository Layout
The repository is structured to maintain clean modularity across core agents, cluster traces, policy evaluations, and experimental benchmarks:

```
GuardEdge-K8s/
├── .env.example              # Environment variables template (API keys, execution mode, seeds)
├── .gitignore                # Git ignore rules preserving results/ and logs/ artifacts
├── requirements.txt          # Production and benchmarking dependencies
├── docs/
│   └── devlog.md             # Chronological engineering log and design decisions
├── src/
│   ├── __init__.py           # Package initialization
│   ├── config.py             # SystemConfig Pydantic model with research gap ablation switches
│   └── state.py              # Typed AgentGraphState and ProposedPlan data models
├── data/
│   └── __init__.py           # Cluster telemetry, trace datasets, and injection vectors
├── experiments/              # Benchmark execution scripts for research gaps E1-E5
│   └── .gitkeep
├── results/                  # Benchmark metrics, CSVs, and figures (tracked for grading)
│   └── .gitkeep
├── logs/                     # Detailed trajectory step logs and JSON audits (tracked for grading)
│   └── .gitkeep
└── tests/                    # Pytest verification suites
    └── __init__.py
```

### 3. Dependency Management & Environment
- Added `requirements.txt` with tested version pins:
  - `pydantic>=2.0.0`: High-performance data validation and state schema enforcement.
  - `numpy>=1.24.0`, `pandas>=2.0.0`: Trace analysis, cluster state matrices, and metrics calculation.
  - `pyyaml>=6.0`: Kubernetes manifest parsing and serialization.
  - `openai>=1.0.0`: LLM client interface for planning and critic reasoning nodes.
  - `python-dotenv>=1.0.0`: Environment variable loading.
  - `pytest>=7.0.0`: Test harness.
  - `kubernetes>=28.1.0`: Native client for Kubernetes cluster interaction.
  - `rich>=13.0.0`: Structured CLI formatting and terminal telemetry visualization.
- Configured `.env.example` with fallback configurations for both mock and live modes (`USE_MOCK_LLM=true`, `K8S_EXECUTION_MODE=emulator`).
- Configured `.gitignore` to unignore and track `results/*.csv`, `results/*.json`, and `logs/*.json` to ensure automated grading reproducibility while ignoring `.env`, `__pycache__/`, `.venv/`, and `.pytest_cache/`.

### 4. Modular Ablation Architecture (`src/config.py`)
`SystemConfig` provides toggleable switches addressing the core research gaps:
- **Gap 1 (`use_k8s_trace_env`)**: Controls switching between a realistic 4-node cluster driven by trace metrics and a 2-node toy simulator.
- **Gap 2 (`use_opa_guard`)**: Enables deterministic Rego Policy-as-Code enforcement, Human-in-the-Loop (HITL) authorization gates, and loop cap constraints (`max_reflection_loops=3`). When disabled, `max_reflection_loops` dynamically expands to 10 to demonstrate unbounded reflection deadlocks.
- **Gap 3 (`use_adv_sanitizer`)**: Controls the pre-execution input sanitizer designed to intercept prompt injection attempts and poisoned telemetry before LLM ingestion.
- **Baseline (`use_actsimcrit`)**: Supports the baseline paper's offline dry-run simulator and critic feedback loop.

### 5. Centralized Typed State (`src/state.py`)
The `AgentGraphState` model unifies agent communication, safety guards, and audit trails:
- **Scenario context**: `scenario_id`, `raw_intent`, `telemetry_log`.
- **Adversarial sanitization**: `sanitized_intent`, `is_adversarial_blocked`.
- **Plan representation**: `ProposedPlan` capturing `action`, `target_node`, `pod_spec`, `cpu_req`, `mem_req`, `privileged`, `host_network`, and `namespace`.
- **Dry-run & Critic loop**: `sim_result`, `critic_feedback`.
- **Deterministic Policy Guard & HITL**: `opa_passed`, `opa_violations`, `hitl_triggered`, `hitl_approved`.
- **Execution & Deadlock monitoring**: `reflection_count`, `deadlock_occurred`, `policy_breach_occurred`, `execution_success`.
- **Audit & Performance Telemetry**: `latency_ms`, `opa_latency_ms`, `api_calls`, `token_count`, and `trajectory_log` (with `add_trajectory_step()` utility).

### 6. Verification
- Scaffolding verified via automated import and unit tests.
- Virtual environment created and requirements resolved.
- Phase 0 baseline committed to version control.
