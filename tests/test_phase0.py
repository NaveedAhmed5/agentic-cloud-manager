"""Unit tests for Phase 0 scaffolding: configuration flags, state schema, and ablation switches."""

import os
import pytest
from src.config import SystemConfig
from src.state import AgentGraphState, ProposedPlan, TrajectoryStep


def test_system_config_defaults():
    """Verify default ablation flags and configuration values."""
    cfg = SystemConfig()
    assert cfg.use_k8s_trace_env is True
    assert cfg.use_opa_guard is True
    assert cfg.use_adv_sanitizer is True
    assert cfg.use_actsimcrit is True
    assert cfg.max_reflection_loops == 3
    assert cfg.seed == 42
    assert cfg.random_seed == 42
    assert cfg.use_mock_llm == (os.getenv("USE_MOCK_LLM", "false").lower() in ("true", "1", "yes"))
    assert cfg.k8s_execution_mode == "emulator"


def test_system_config_opa_ablation_reflection_loop_expansion():
    """When OPA guard is disabled, max_reflection_loops should expand to 10 to allow observing deadlocks."""
    cfg_no_opa = SystemConfig(use_opa_guard=False)
    assert cfg_no_opa.use_opa_guard is False
    assert cfg_no_opa.max_reflection_loops == 10

    # Explicit override should be preserved even if OPA guard is disabled
    cfg_custom = SystemConfig(use_opa_guard=False, max_reflection_loops=7)
    assert cfg_custom.max_reflection_loops == 7


def test_agent_graph_state_instantiation_and_defaults():
    """Verify that AgentGraphState initializes correctly with typed defaults."""
    state = AgentGraphState(
        scenario_id="E1_benign_01",
        raw_intent="Deploy a worker pod with 500m CPU in production.",
    )
    assert state.scenario_id == "E1_benign_01"
    assert state.raw_intent == "Deploy a worker pod with 500m CPU in production."
    assert state.sanitized_intent is None
    assert state.is_adversarial_blocked is False
    assert state.cluster_snapshot == {}
    assert state.proposed_plan is None
    assert state.sim_result is None
    assert state.critic_feedback is None
    assert state.opa_passed is None
    assert state.opa_violations == []
    assert state.hitl_triggered is False
    assert state.hitl_approved is None
    assert state.reflection_count == 0
    assert state.deadlock_occurred is False
    assert state.policy_breach_occurred is False
    assert state.execution_success is False
    assert state.latency_ms == 0.0
    assert state.opa_latency_ms == 0.0
    assert state.api_calls == 0
    assert state.token_count == 0
    assert state.trajectory_log == []


def test_agent_graph_state_proposed_plan_and_trajectory():
    """Verify structured plan assignment and trajectory step auditing."""
    plan = ProposedPlan(
        action="deploy",
        target_node="node-1",
        pod_spec={"containers": [{"name": "app", "image": "nginx"}]},
        cpu_req=0.5,
        mem_req=512.0,
        privileged=False,
        host_network=False,
        namespace="default",
    )
    state = AgentGraphState(
        scenario_id="E1_test",
        proposed_plan=plan,
    )

    assert state.proposed_plan.action == "deploy"
    assert state.proposed_plan.cpu_req == 0.5
    assert state.proposed_plan.privileged is False

    # Append trajectory step
    state.add_trajectory_step(
        agent="Planner",
        input="Request to deploy nginx",
        reasoning="Selected node-1 based on lowest CPU utilization.",
        tool_call={"tool": "k8s_dryrun", "node": "node-1"},
        output={"status": "simulated_success"},
    )

    assert len(state.trajectory_log) == 1
    step = state.trajectory_log[0]
    assert step["agent"] == "Planner"
    assert step["reasoning"] == "Selected node-1 based on lowest CPU utilization."
    assert "timestamp" in step

