"""Unit tests for Phase 1: Alibaba trace datasets, 4-node K8s emulator, and scheduler baselines."""

import pytest
from data import load_adversarial_suite, load_dev_traces, load_test_traces
from src.k8s_env import (
    K8sMultiNodeEmulator,
    KubeSchedulerBaseline,
    NodeState,
    StaticHPABaseline,
    ToyTwoNodeSimulator,
    create_k8s_environment,
)
from src.state import ProposedPlan


def test_dataset_loading_and_counts():
    """Verify all 3 dataset files exist, load cleanly, and contain exact specified scenario counts."""
    dev_traces = load_dev_traces()
    assert len(dev_traces) == 30, f"Expected 30 dev traces, found {len(dev_traces)}"
    for item in dev_traces:
        assert "scenario_id" in item
        assert item["split"] == "dev"
        assert "pod_request" in item
        assert "cluster_initial_state" in item
        assert "ground_truth" in item

    test_traces = load_test_traces()
    assert len(test_traces) == 100, f"Expected 100 test traces, found {len(test_traces)}"
    for item in test_traces:
        assert "scenario_id" in item
        assert item["split"] == "test"
        assert "category" in item
        assert "ground_truth" in item

    adv_suite = load_adversarial_suite()
    assert len(adv_suite) == 40, f"Expected 40 adversarial scenarios, found {len(adv_suite)}"
    injections = [s for s in adv_suite if s["attack_type"] == "direct_prompt_injection"]
    poisoned = [s for s in adv_suite if s["attack_type"] == "telemetry_poisoning"]
    benign = [s for s in adv_suite if s["attack_type"] == "none"]
    assert len(injections) == 10, f"Expected 10 prompt injections, found {len(injections)}"
    assert len(poisoned) == 10, f"Expected 10 telemetry poisoning cases, found {len(poisoned)}"
    assert len(benign) == 20, f"Expected 20 benign control cases, found {len(benign)}"


def test_k8s_multinode_emulator_initialization_and_taints():
    """Verify 4-node topology, control-plane taints, and untolerated pod rejection."""
    emu = K8sMultiNodeEmulator()
    nodes = emu.list_nodes()
    assert len(nodes) == 4

    node_names = [n["metadata"]["name"] for n in nodes]
    assert set(node_names) == {"control-plane-1", "worker-1", "worker-2", "worker-3"}

    # Attempt to deploy untolerated user pod directly onto control-plane-1
    pod_manifest = {
        "metadata": {"name": "user-pod-1"},
        "spec": {
            "nodeName": "control-plane-1",
            "containers": [{"resources": {"requests": {"cpu": "1.0", "memory": "1024"}}}],
        },
    }
    result = emu.create_namespaced_pod(namespace="default", body=pod_manifest)
    assert result["status"] == "Failed"
    assert "taints" in result["reason"]

    # Verify that tolerating pod can be placed on control plane
    tolerating_manifest = {
        "metadata": {"name": "system-agent"},
        "spec": {
            "nodeName": "control-plane-1",
            "tolerations": [{"key": "node-role.kubernetes.io/control-plane", "effect": "NoSchedule"}],
            "containers": [{"resources": {"requests": {"cpu": "0.5", "memory": "512"}}}],
        },
    }
    res_tol = emu.create_namespaced_pod(namespace="kube-system", body=tolerating_manifest)
    assert res_tol["status"] == "Running"
    assert res_tol["node"] == "control-plane-1"


def test_k8s_multinode_emulator_pod_lifecycle_and_allocation():
    """Verify pod placement, resource consumption, SDK adapter, and eviction/reclaim."""
    emu = K8sMultiNodeEmulator()

    pod_manifest = {
        "metadata": {"name": "web-backend"},
        "spec": {
            "nodeName": "worker-1",
            "containers": [{"resources": {"requests": {"cpu": "2.0", "memory": "4096"}}}],
        },
    }
    create_res = emu.core_v1.create_namespaced_pod(namespace="production", body=pod_manifest)
    assert create_res["status"] == "Running"
    assert create_res["node"] == "worker-1"

    worker_1 = emu.nodes["worker-1"]
    assert worker_1.cpu_allocated == 2.0
    assert worker_1.mem_allocated == 4096.0

    # List pods via SDK adapter
    pod_list = emu.core_v1.list_namespaced_pod("production")
    assert len(pod_list["items"]) == 1
    assert pod_list["items"][0]["metadata"]["name"] == "web-backend"

    # Delete pod and verify resource reclamation
    del_res = emu.core_v1.delete_namespaced_pod(name="web-backend", namespace="production")
    assert del_res["status"] == "Success"
    assert worker_1.cpu_allocated == 0.0
    assert worker_1.mem_allocated == 0.0


def test_k8s_multinode_emulator_out_of_capacity():
    """Verify rejection when pod requests exceed any node's free capacity."""
    emu = K8sMultiNodeEmulator()
    # worker-1 has 8.0 CPU max; request 10.0 CPU
    huge_pod = {
        "metadata": {"name": "massive-job"},
        "spec": {
            "containers": [{"resources": {"requests": {"cpu": "10.0", "memory": "2048"}}}],
        },
    }
    res = emu.create_namespaced_pod(namespace="default", body=huge_pod)
    assert res["status"] == "Pending"
    assert "No feasible node" in res["reason"]


def test_k8s_bin_packing_and_metrics():
    """Verify calculation of worker utilization, variance, and bin-packing efficiency."""
    emu = K8sMultiNodeEmulator()
    initial_state = {
        "worker-1": {"cpu_alloc": 4.0, "mem_alloc": 8192.0},  # 50% util
        "worker-2": {"cpu_alloc": 2.0, "mem_alloc": 4096.0},  # 50% util
        "worker-3": {"cpu_alloc": 2.0, "mem_alloc": 4096.0},  # 50% util
    }
    emu.reset(initial_state)

    metrics = emu.calculate_resource_utilization()
    assert metrics["mean_worker_cpu_util"] == 50.0
    assert metrics["mean_worker_mem_util"] == 50.0
    assert metrics["composite_worker_util"] == 50.0
    # Balanced load should have near-zero variance and high bin-packing score
    assert metrics["cpu_variance"] < 0.001
    assert metrics["bin_packing_efficiency"] == 50.0

    # Prometheus telemetry snapshot
    prom = emu.get_prometheus_metrics()
    assert "node_cpu_utilization" in prom
    assert prom["node_cpu_utilization"]["worker-1"] == 0.5


def test_kube_scheduler_baseline_least_requested():
    """Verify standard LeastRequestedPriority selects the node with the highest spare capacity ratio."""
    emu = K8sMultiNodeEmulator()
    # worker-1 has 6/8 CPU used (25% free)
    # worker-2 has 3/4 CPU used (25% free)
    # worker-3 has 1/4 CPU used (75% free)
    initial_state = {
        "worker-1": {"cpu_alloc": 6.0, "mem_alloc": 12000.0},
        "worker-2": {"cpu_alloc": 3.0, "mem_alloc": 6000.0},
        "worker-3": {"cpu_alloc": 1.0, "mem_alloc": 2000.0},
    }
    emu.reset(initial_state)

    scheduler = KubeSchedulerBaseline()
    plan = ProposedPlan(
        action="deploy",
        cpu_req=1.0,
        mem_req=1024.0,
        namespace="default",
    )

    chosen = scheduler.schedule_first_fit_least_requested(plan, list(emu.nodes.values()))
    assert chosen == "worker-3", f"Expected worker-3 (most idle), got {chosen}"


def test_static_hpa_baseline():
    """Verify HPA replica formula with scaling up, scaling down, and bounds clamping."""
    hpa = StaticHPABaseline()

    # Scale up: 2 replicas at 90% CPU vs 80% target -> ceil(2 * 90/80) = ceil(2.25) = 3
    assert hpa.evaluate_scaling(current_replicas=2, current_cpu_util_pct=90.0, target_cpu_util_pct=80.0) == 3

    # Scale down: 4 replicas at 20% CPU vs 80% target -> ceil(4 * 20/80) = ceil(1.0) = 1
    assert hpa.evaluate_scaling(current_replicas=4, current_cpu_util_pct=20.0, target_cpu_util_pct=80.0) == 1

    # Clamp to max_replicas: 5 replicas at 300% CPU -> ceil(5 * 300/80) = 19 -> max 10
    assert hpa.evaluate_scaling(current_replicas=5, current_cpu_util_pct=300.0, max_replicas=10) == 10


def test_toy_two_node_simulator_ablation():
    """Verify Base Paper 2-node simulator functionality for Gap 1 ablation comparison."""
    toy = ToyTwoNodeSimulator()
    snapshot = toy.get_cluster_snapshot()
    assert snapshot["total_nodes"] == 2
    assert "edge-node-1" in snapshot["nodes"]
    assert "cloud-node-1" in snapshot["nodes"]

    # Place small pod on edge
    placed_node = toy.schedule_pod(name="edge-app", cpu_req=0.5, mem_req=512.0, prefer_edge=True)
    assert placed_node == "edge-node-1"

    # Edge node has 2.0 CPU max; place large pod requiring 4.0 CPU, falls back to cloud
    big_node = toy.schedule_pod(name="heavy-job", cpu_req=4.0, mem_req=4096.0, prefer_edge=True)
    assert big_node == "cloud-node-1"

    # Factory creates correct environment
    env_4node = create_k8s_environment(use_k8s_trace_env=True)
    assert isinstance(env_4node, K8sMultiNodeEmulator)

    env_2node = create_k8s_environment(use_k8s_trace_env=False)
    assert isinstance(env_2node, ToyTwoNodeSimulator)
