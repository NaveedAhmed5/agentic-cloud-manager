"""Typed state representations for GuardEdge-K8s agentic orchestration workflow.

Defines the central `AgentGraphState` tracking scenario context, adversarial sanitization,
proposed orchestration plans, ActSimCrit dry-run & critic feedback, OPA Rego policy checks,
HITL gates, loop counters, and performance/audit telemetry.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Union
from pydantic import BaseModel, Field


class ProposedPlan(BaseModel):
    """Structured representation of an agent's proposed Kubernetes orchestration plan."""

    action: str = Field(
        default="deploy",
        description="Kubernetes orchestration action (e.g. 'deploy', 'scale', 'evict', 'delete', 'patch').",
    )
    target_node: Optional[str] = Field(
        default=None,
        description="Designated Kubernetes worker node (e.g. 'node-1', 'node-2').",
    )
    pod_spec: dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed Pod manifest specification or resource definition.",
    )
    cpu_req: float = Field(
        default=0.0,
        description="Requested CPU capacity (in cores, e.g. 0.5 = 500m).",
    )
    mem_req: float = Field(
        default=0.0,
        description="Requested Memory capacity (in MiB or GiB, e.g. 512.0).",
    )
    privileged: bool = Field(
        default=False,
        description="SecurityContext flag: whether pod container requests privileged root/host access.",
    )
    host_network: bool = Field(
        default=False,
        description="HostNetwork flag: whether pod requests sharing the host network namespace.",
    )
    namespace: str = Field(
        default="default",
        description="Target Kubernetes namespace.",
    )


class TrajectoryStep(BaseModel):
    """Audit record of an individual step or node transition in the agent trajectory."""

    agent: str = Field(
        description="Identifier of the executing agent or node (e.g., 'Sanitizer', 'Planner', 'Critic', 'OPAGuard')."
    )
    input: Any = Field(
        default=None,
        description="Input context or prompt provided to the agent/node.",
    )
    reasoning: Optional[str] = Field(
        default=None,
        description="Internal CoT / reasoning emitted by the agent.",
    )
    tool_call: Optional[dict[str, Any]] = Field(
        default=None,
        description="Tool or function call requested or executed during this step.",
    )
    output: Any = Field(
        default=None,
        description="Output result, state delta, or verdict produced by this step.",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="UTC ISO-8601 timestamp when step was logged.",
    )


class AgentGraphState(BaseModel):
    """Central state passed across nodes in the GuardEdge-K8s orchestration graph."""

    # ---------------------------------------------------------
    # Scenario and Input Context
    # ---------------------------------------------------------
    scenario_id: str = Field(
        default="",
        description="Unique benchmark scenario identifier (e.g. 'E1_benign_deploy_01').",
    )
    raw_intent: str = Field(
        default="",
        description="Original, unvetted operator prompt or orchestration intent.",
    )
    telemetry_log: Optional[dict[str, Any]] = Field(
        default=None,
        description="Cluster telemetry, metrics log, or events associated with the scenario.",
    )

    # ---------------------------------------------------------
    # Adversarial Sanitization (Research Gap 3)
    # ---------------------------------------------------------
    sanitized_intent: Optional[str] = Field(
        default=None,
        description="Cleaned prompt after pre-execution prompt-injection and poisoning filtering.",
    )
    is_adversarial_blocked: bool = Field(
        default=False,
        description="True if an adversarial prompt injection or telemetry poisoning attack was detected and blocked.",
    )

    # ---------------------------------------------------------
    # Cluster State and Proposed Orchestration Plan
    # ---------------------------------------------------------
    cluster_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Current state snapshot of cluster nodes, allocations, and capacities.",
    )
    proposed_plan: Optional[Union[ProposedPlan, dict[str, Any]]] = Field(
        default=None,
        description="Candidate orchestration plan produced by the Planner Agent.",
    )

    # ---------------------------------------------------------
    # ActSimCrit Simulator & Critic Loop (Baseline Gap)
    # ---------------------------------------------------------
    sim_result: Optional[dict[str, Any]] = Field(
        default=None,
        description="Offline dry-run simulation outcome (predicted node utilization, feasibility).",
    )
    critic_feedback: Optional[str] = Field(
        default=None,
        description="Critique or revision instructions generated by the Critic Agent.",
    )

    # ---------------------------------------------------------
    # OPA Policy Guard & HITL Gate (Research Gap 2)
    # ---------------------------------------------------------
    opa_passed: Optional[bool] = Field(
        default=None,
        description="True if the proposed plan satisfied all deterministic Rego OPA security policies.",
    )
    opa_violations: list[str] = Field(
        default_factory=list,
        description="List of specific policy violation messages emitted by the Rego policy engine.",
    )
    hitl_triggered: bool = Field(
        default=False,
        description="True if Human-in-the-Loop review was required (e.g. for high-risk operations).",
    )
    hitl_approved: Optional[bool] = Field(
        default=None,
        description="Outcome of Human-in-the-Loop approval (True if approved, False if rejected).",
    )

    # ---------------------------------------------------------
    # Execution & Reflection Loop Metrics
    # ---------------------------------------------------------
    reflection_count: int = Field(
        default=0,
        description="Number of critique/re-planning iterations performed in this episode.",
    )
    deadlock_occurred: bool = Field(
        default=False,
        description="True if the agent entered an unresolvable reflection loop or exceeded loop cap.",
    )
    policy_breach_occurred: bool = Field(
        default=False,
        description="True if a security/cluster policy was violated during execution.",
    )
    execution_success: bool = Field(
        default=False,
        description="True if the orchestration plan was successfully executed in the target cluster.",
    )

    # ---------------------------------------------------------
    # Benchmark Telemetry & Audit
    # ---------------------------------------------------------
    latency_ms: float = Field(
        default=0.0,
        description="End-to-end orchestration latency in milliseconds.",
    )
    opa_latency_ms: float = Field(
        default=0.0,
        description="Time spent evaluating deterministic OPA Rego policies in milliseconds.",
    )
    api_calls: int = Field(
        default=0,
        description="Number of LLM API requests invoked during this episode.",
    )
    token_count: int = Field(
        default=0,
        description="Total tokens consumed (prompt + completion) during this episode.",
    )
    trajectory_log: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Sequential list of audit steps recording agent, input, reasoning, tool_call, output, timestamp.",
    )

    def add_trajectory_step(
        self,
        agent: str,
        input: Any = None,
        reasoning: Optional[str] = None,
        tool_call: Optional[dict[str, Any]] = None,
        output: Any = None,
        timestamp: Optional[str] = None,
    ) -> None:
        """Helper to append an audit record to the trajectory log."""
        step = TrajectoryStep(
            agent=agent,
            input=input,
            reasoning=reasoning,
            tool_call=tool_call,
            output=output,
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        )
        self.trajectory_log.append(step.model_dump())

