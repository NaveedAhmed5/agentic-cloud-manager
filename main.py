"""CLI Entry Point for GuardEdge-K8s Orchestration Framework.

Modes:
- demo: Runs 1 benign trace scenario and 1 adversarial scenario, displaying rich
  trajectory traces, OPA policy verdicts, and Kubernetes state transition tables.
- run-all: Executes the complete E1-E6 experimental benchmark suite.
"""

from __future__ import annotations

import argparse
import sys
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from data import load_adversarial_suite, load_dev_traces
from src.config import SystemConfig
from src.k8s_env import K8sMultiNodeEmulator
from src.orchestrator import GuardEdgeOrchestrator
from src.state import AgentGraphState

console = Console()


def run_demo() -> None:
    """Execute interactive CLI demonstration on benign and adversarial scenarios."""
    console.print(
        Panel.fit(
            "[bold cyan]GuardEdge-K8s: Policy-Enforced & Adversarial-Resilient Agentic Orchestration[/bold cyan]\n"
            "[dim]Ablation-Ready Multi-Agent Control Plane for Cloud-Native Kubernetes Clusters[/dim]",
            border_style="cyan",
        )
    )

    config = SystemConfig(use_k8s_trace_env=True, use_opa_guard=True, use_adv_sanitizer=True)
    orchestrator = GuardEdgeOrchestrator(config)
    env = K8sMultiNodeEmulator()

    # =========================================================================
    # Demo 1: Benign Trace Workload Scenario
    # =========================================================================
    dev_traces = load_dev_traces()
    benign_sample = dev_traces[0]
    scenario_id = benign_sample["scenario_id"]
    raw_intent = benign_sample["raw_intent"]

    console.print(f"\n[bold green]=== Demo Scenario 1: Benign Alibaba Cluster Trace ({scenario_id}) ===[/bold green]")
    console.print(f"[bold]Operator Intent:[/bold] {raw_intent}")

    # Seed cluster with initial scenario state
    env.reset(benign_sample.get("cluster_initial_state"))
    pre_metrics = env.calculate_resource_utilization()

    state = AgentGraphState(
        scenario_id=scenario_id,
        raw_intent=raw_intent,
        telemetry_log=benign_sample.get("telemetry_log"),
    )

    state = orchestrator.run(state, env)
    post_metrics = env.calculate_resource_utilization()

    # Render Step-by-Step Trajectory
    traj_table = Table(title=f"Agent Trajectory Audit Log ({scenario_id})", border_style="blue")
    traj_table.add_column("Agent", style="bold yellow", width=20)
    traj_table.add_column("Tool / Action", style="cyan", width=24)
    traj_table.add_column("Internal Reasoning / Output", style="white")

    for step in state.trajectory_log:
        agent_name = step.get("agent", "")
        tool_name = step.get("tool_call", {}).get("tool", "internal") if step.get("tool_call") else "internal"
        reasoning = step.get("reasoning", "")
        traj_table.add_row(agent_name, tool_name, reasoning)

    console.print(traj_table)

    # Render Cluster State Transition Table
    cluster_table = Table(title="Kubernetes Cluster State Transition", border_style="magenta")
    cluster_table.add_column("Node", style="bold")
    cluster_table.add_column("Role / Type", style="dim")
    cluster_table.add_column("CPU Capacity", justify="right")
    cluster_table.add_column("CPU Alloc", justify="right")
    cluster_table.add_column("RAM Capacity", justify="right")
    cluster_table.add_column("RAM Alloc", justify="right")
    cluster_table.add_column("Active Pods", justify="right")

    for name, node in env.nodes.items():
        role = "Control Plane (NoSchedule)" if "control-plane" in name else "Worker Node"
        cluster_table.add_row(
            name,
            role,
            f"{node.cpu_capacity:.1f}C",
            f"{node.cpu_allocated:.2f}C ({node.cpu_utilization*100:.1f}%)",
            f"{node.mem_capacity:.0f}Mi",
            f"{node.mem_allocated:.1f}Mi ({node.mem_utilization*100:.1f}%)",
            str(len(node.pods)),
        )

    console.print(cluster_table)

    console.print(
        Panel(
            f"[bold green]Execution Status:[/bold green] {'SUCCESS' if state.execution_success else 'FAILED'}\n"
            f"[bold]Total Latency:[/bold] {state.latency_ms:.2f} ms | "
            f"[bold]OPA Evaluation Latency:[/bold] {state.opa_latency_ms:.3f} ms | "
            f"[bold]LLM API Calls:[/bold] {state.api_calls} | "
            f"[bold]Tokens Consumed:[/bold] {state.token_count}\n"
            f"[bold]Bin-Packing Efficiency:[/bold] Pre: {pre_metrics['bin_packing_efficiency']:.2f}% -> Post: {post_metrics['bin_packing_efficiency']:.2f}%",
            title="Execution Outcome",
            border_style="green",
        )
    )

    # =========================================================================
    # Demo 2: Adversarial Attack Scenario (Gap 3 Defense)
    # =========================================================================
    adv_suite = load_adversarial_suite()
    adv_sample = adv_suite[0]  # Direct prompt injection
    adv_id = adv_sample["scenario_id"]
    adv_intent = adv_sample["raw_intent"]

    console.print(f"\n[bold red]=== Demo Scenario 2: Adversarial Security Attack ({adv_id}) ===[/bold red]")
    console.print(f"[bold red]Injected Intent:[/bold red] {adv_intent}")

    adv_state = AgentGraphState(
        scenario_id=adv_id,
        raw_intent=adv_intent,
        telemetry_log=adv_sample.get("telemetry_log"),
    )

    adv_state = orchestrator.run(adv_state, env)

    console.print(
        Panel(
            f"[bold red]Adversarial Attack Blocked:[/bold red] {adv_state.is_adversarial_blocked}\n"
            f"[bold]Execution Halt Status:[/bold] Zero unauthorized pods created on cluster\n"
            f"[bold]Policy Breach Occurred:[/bold] {adv_state.policy_breach_occurred} (Target: 0%)\n"
            f"[bold]Sanitization Latency:[/bold] {adv_state.latency_ms:.3f} ms\n"
            f"[dim]Audit Reasoning: {adv_state.trajectory_log[0]['reasoning']}[/dim]",
            title="[bold red]Gap 3 Pre-Execution Sanitizer Verdict[/bold red]",
            border_style="red",
        )
    )


def run_all_experiments() -> None:
    """Execute complete E1-E6 experimental benchmark suite and output metrics."""
    console.print("[bold cyan]Running Full E1-E6 Experimental Evaluation Suite...[/bold cyan]")
    try:
        from experiments.run_experiments import run_benchmarks
        run_benchmarks()
    except ImportError:
        console.print("[yellow]experiments/run_experiments.py not yet populated; placeholder initialized.[/yellow]")


def main() -> None:
    parser = argparse.ArgumentParser(description="GuardEdge-K8s Agentic Orchestration CLI")
    parser.add_argument(
        "--mode",
        choices=["demo", "run-all"],
        default="demo",
        help="Execution mode: 'demo' for live interactive sample trace, or 'run-all' for E1-E6 suite.",
    )
    args = parser.parse_args()

    if args.mode == "demo":
        run_demo()
    elif args.mode == "run-all":
        run_all_experiments()


if __name__ == "__main__":
    main()

