"""Kubernetes environment implementations and scheduling baselines for GuardEdge-K8s.

Implements Gap 1 switchable environments:
- K8sMultiNodeEmulator (when use_k8s_trace_env=True):
    4-node heterogeneous Kubernetes cluster (1 control-plane, 3 workers)
    with taints, tolerations, namespaces, bin-packing efficiency, Prometheus
    telemetry snapshots, and a Kubernetes Python SDK-compatible API interface.
- ToyTwoNodeSimulator (when use_k8s_trace_env=False):
    Base paper (AgentEdge) 2-node edge topology lacking K8s namespace/taint awareness.
- KubeSchedulerBaseline & StaticHPABaseline:
    Standard Kubernetes LeastRequestedPriority scheduler and HPA baseline algorithms
    for empirical comparison in E1 & E4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Union
from src.state import ProposedPlan


def parse_k8s_resource(val: Any, default: float = 0.0) -> float:
    """Parse Kubernetes resource string or numeric value to float."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip()
    if not val_str:
        return default
    if val_str.endswith("m"):
        try:
            return float(val_str[:-1]) / 1000.0
        except ValueError:
            return default
    if val_str.endswith("Gi") or val_str.endswith("G"):
        num_part = val_str.rstrip("GiG")
        try:
            return float(num_part) * 1024.0
        except ValueError:
            return default
    if val_str.endswith("Mi") or val_str.endswith("M"):
        num_part = val_str.rstrip("MiM")
        try:
            return float(num_part)
        except ValueError:
            return default
    if val_str.endswith("Ki") or val_str.endswith("K"):
        num_part = val_str.rstrip("KiK")
        try:
            return float(num_part) / 1024.0
        except ValueError:
            return default
    try:
        return float(val_str)
    except ValueError:
        return default


@dataclass
class NodeState:
    """State of an individual Kubernetes node in the cluster."""

    name: str
    cpu_capacity: float  # CPU cores (e.g. 4.0)
    mem_capacity: float  # Memory in MiB (e.g. 8192.0)
    cpu_allocated: float = 0.0
    mem_allocated: float = 0.0
    taints: list[dict[str, str]] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    pods: dict[str, dict[str, Any]] = field(default_factory=dict)
    is_ready: bool = True

    @property
    def cpu_free(self) -> float:
        return max(0.0, round(self.cpu_capacity - self.cpu_allocated, 4))

    @property
    def mem_free(self) -> float:
        return max(0.0, round(self.mem_capacity - self.mem_allocated, 2))

    @property
    def cpu_utilization(self) -> float:
        return round(self.cpu_allocated / self.cpu_capacity, 4) if self.cpu_capacity > 0 else 0.0

    @property
    def mem_utilization(self) -> float:
        return round(self.mem_allocated / self.mem_capacity, 4) if self.mem_capacity > 0 else 0.0

    def can_fit(self, cpu_req: float, mem_req: float) -> bool:
        """Check if node has sufficient unallocated capacity."""
        return (cpu_req <= self.cpu_free + 1e-6) and (mem_req <= self.mem_free + 1e-6)

    def tolerates_taints(self, tolerations: list[dict[str, str]]) -> bool:
        """Verify whether pod tolerations satisfy all 'NoSchedule' taints."""
        for taint in self.taints:
            if taint.get("effect") == "NoSchedule":
                key = taint.get("key")
                matched = any(
                    tol.get("key") == key or tol.get("operator") == "Exists"
                    for tol in tolerations
                )
                if not matched:
                    return False
        return True


class K8sSDKCoreV1Adapter:
    """Wrapper exposing method signatures compatible with the official kubernetes CoreV1Api."""

    def __init__(self, emulator: K8sMultiNodeEmulator) -> None:
        self._emu = emulator

    def list_node(self) -> dict[str, Any]:
        """Mimics core_v1.list_node()."""
        nodes = self._emu.list_nodes()
        return {"items": nodes, "kind": "NodeList", "apiVersion": "v1"}

    def list_namespaced_pod(self, namespace: str) -> dict[str, Any]:
        """Mimics core_v1.list_namespaced_pod(namespace)."""
        pods = self._emu.list_namespaced_pod(namespace=namespace)
        return {"items": pods, "kind": "PodList", "apiVersion": "v1"}

    def create_namespaced_pod(self, namespace: str, body: dict[str, Any]) -> dict[str, Any]:
        """Mimics core_v1.create_namespaced_pod(namespace, body)."""
        return self._emu.create_namespaced_pod(namespace=namespace, body=body)

    def delete_namespaced_pod(self, name: str, namespace: str) -> dict[str, Any]:
        """Mimics core_v1.delete_namespaced_pod(name, namespace)."""
        success = self._emu.delete_namespaced_pod(name=name, namespace=namespace)
        return {"status": "Success" if success else "NotFound", "pod": name}


class K8sMultiNodeEmulator:
    """Gap 1: Realistic 4-node Kubernetes cluster emulator.

    Topology:
    - control-plane-1: 4C / 8192MiB (Tainted: NoSchedule)
    - worker-1: 8C / 16384MiB (High-compute worker)
    - worker-2: 4C / 8192MiB (General compute worker)
    - worker-3: 4C / 8192MiB (General compute worker)
    """

    def __init__(self) -> None:
        self.nodes: dict[str, NodeState] = {}
        self.core_v1 = K8sSDKCoreV1Adapter(self)
        self.reset()

    def reset(self, initial_state: Optional[dict[str, Any]] = None) -> None:
        """Reset nodes to default cluster topology and apply initial allocations."""
        self.nodes = {
            "control-plane-1": NodeState(
                name="control-plane-1",
                cpu_capacity=4.0,
                mem_capacity=8192.0,
                taints=[{"key": "node-role.kubernetes.io/control-plane", "effect": "NoSchedule"}],
                labels={"kubernetes.io/hostname": "control-plane-1", "node-role.kubernetes.io/control-plane": ""},
            ),
            "worker-1": NodeState(
                name="worker-1",
                cpu_capacity=8.0,
                mem_capacity=16384.0,
                labels={"kubernetes.io/hostname": "worker-1", "node.kubernetes.io/instance-type": "high-compute"},
            ),
            "worker-2": NodeState(
                name="worker-2",
                cpu_capacity=4.0,
                mem_capacity=8192.0,
                labels={"kubernetes.io/hostname": "worker-2", "node.kubernetes.io/instance-type": "general-compute"},
            ),
            "worker-3": NodeState(
                name="worker-3",
                cpu_capacity=4.0,
                mem_capacity=8192.0,
                labels={"kubernetes.io/hostname": "worker-3", "node.kubernetes.io/instance-type": "general-compute"},
            ),
        }

        # Apply initial allocations (e.g. from Alibaba trace scenario)
        if initial_state:
            for node_name, alloc in initial_state.items():
                if node_name in self.nodes:
                    node = self.nodes[node_name]
                    node.cpu_allocated = min(node.cpu_capacity, alloc.get("cpu_alloc", 0.0))
                    node.mem_allocated = min(node.mem_capacity, alloc.get("mem_alloc", 0.0))

    def list_nodes(self) -> list[dict[str, Any]]:
        """Return structured node representations."""
        result = []
        for node in self.nodes.values():
            result.append({
                "metadata": {"name": node.name, "labels": node.labels},
                "spec": {"taints": node.taints},
                "status": {
                    "capacity": {"cpu": str(node.cpu_capacity), "memory": f"{node.mem_capacity}Mi"},
                    "allocatable": {"cpu": str(node.cpu_free), "memory": f"{node.mem_free}Mi"},
                    "conditions": [{"type": "Ready", "status": "True" if node.is_ready else "False"}],
                },
            })
        return result

    def list_namespaced_pod(self, namespace: str = "default") -> list[dict[str, Any]]:
        """List all active pods residing in given namespace across all nodes."""
        matched = []
        for node in self.nodes.values():
            for pod in node.pods.values():
                pod_ns = pod.get("namespace") or pod.get("metadata", {}).get("namespace", "default")
                if namespace == "" or pod_ns == namespace:
                    matched.append(pod)
        return matched

    def create_namespaced_pod(self, namespace: str, body: dict[str, Any]) -> dict[str, Any]:
        """Deploy a pod into the cluster, validating taints and capacity."""
        metadata = body.get("metadata", {})
        spec = body.get("spec", {})
        pod_name = metadata.get("name", "unnamed-pod")
        tolerations = spec.get("tolerations", [])

        # Extract resource requests
        containers = spec.get("containers", [{}])
        first_container = containers[0] if containers else {}
        resources = first_container.get("resources", {}).get("requests", {})
        raw_cpu = resources.get("cpu", body.get("cpu_req", 0.1))
        raw_mem = resources.get("memory", body.get("mem_req", 128.0))
        cpu_req = parse_k8s_resource(raw_cpu, default=0.1)
        mem_req = parse_k8s_resource(raw_mem, default=128.0)
        target_node = spec.get("nodeName") or body.get("target_node")

        # If target node specified explicitly, attempt binding to it
        if target_node:
            if target_node not in self.nodes:
                return {"status": "Failed", "reason": f"Node '{target_node}' does not exist"}
            node = self.nodes[target_node]
            if not node.tolerates_taints(tolerations):
                return {"status": "Failed", "reason": f"Pod does not tolerate taints on {target_node}"}
            if not node.can_fit(cpu_req, mem_req):
                return {"status": "Failed", "reason": f"Insufficient capacity on {target_node}"}

            chosen_node = node
        else:
            # Automatic scheduling via First-Fit Least-Requested heuristic
            scheduler = KubeSchedulerBaseline()
            scheduled_name = scheduler.schedule_first_fit_least_requested(
                pod_spec={"cpu_req": cpu_req, "mem_req": mem_req, "tolerations": tolerations},
                nodes=list(self.nodes.values()),
            )
            if not scheduled_name:
                return {"status": "Pending", "reason": "No feasible node available"}
            chosen_node = self.nodes[scheduled_name]

        # Allocate resources
        chosen_node.cpu_allocated = round(chosen_node.cpu_allocated + cpu_req, 4)
        chosen_node.mem_allocated = round(chosen_node.mem_allocated + mem_req, 2)
        pod_record = {
            "metadata": {"name": pod_name, "namespace": namespace},
            "namespace": namespace,
            "spec": spec,
            "status": {"phase": "Running", "hostIP": chosen_node.name, "nodeName": chosen_node.name},
            "cpu_req": cpu_req,
            "mem_req": mem_req,
            "node": chosen_node.name,
        }
        chosen_node.pods[pod_name] = pod_record

        return {"status": "Running", "node": chosen_node.name, "pod": pod_record}

    def delete_namespaced_pod(self, name: str, namespace: str = "default") -> bool:
        """Evict and delete pod, reclaiming allocated capacity."""
        for node in self.nodes.values():
            if name in node.pods:
                pod = node.pods[name]
                if pod.get("metadata", {}).get("namespace", "default") == namespace:
                    cpu_req = pod.get("cpu_req", 0.0)
                    mem_req = pod.get("mem_req", 0.0)
                    node.cpu_allocated = max(0.0, round(node.cpu_allocated - cpu_req, 4))
                    node.mem_allocated = max(0.0, round(node.mem_allocated - mem_req, 2))
                    del node.pods[name]
                    return True
        return False

    def get_cluster_snapshot(self) -> dict[str, Any]:
        """Return cluster-wide capacity, allocation, and node details."""
        total_cpu = sum(n.cpu_capacity for n in self.nodes.values())
        alloc_cpu = sum(n.cpu_allocated for n in self.nodes.values())
        total_mem = sum(n.mem_capacity for n in self.nodes.values())
        alloc_mem = sum(n.mem_allocated for n in self.nodes.values())

        return {
            "total_nodes": len(self.nodes),
            "total_cpu_cores": total_cpu,
            "allocated_cpu_cores": round(alloc_cpu, 2),
            "cpu_utilization_pct": round((alloc_cpu / total_cpu) * 100, 2) if total_cpu else 0.0,
            "total_mem_mib": total_mem,
            "allocated_mem_mib": round(alloc_mem, 1),
            "mem_utilization_pct": round((alloc_mem / total_mem) * 100, 2) if total_mem else 0.0,
            "nodes": {
                name: {
                    "cpu_util": node.cpu_utilization,
                    "mem_util": node.mem_utilization,
                    "cpu_free": node.cpu_free,
                    "mem_free": node.mem_free,
                    "pod_count": len(node.pods),
                }
                for name, node in self.nodes.items()
            },
        }

    def get_prometheus_metrics(self) -> dict[str, Any]:
        """Generate simulated Prometheus telemetry snapshot for Observability Agent."""
        metrics: dict[str, Any] = {
            "node_cpu_utilization": {},
            "node_memory_utilization": {},
            "node_memory_available_bytes": {},
        }
        for name, node in self.nodes.items():
            metrics["node_cpu_utilization"][name] = node.cpu_utilization
            metrics["node_memory_utilization"][name] = node.mem_utilization
            metrics["node_memory_available_bytes"][name] = node.mem_free * 1024 * 1024
        return metrics

    def calculate_resource_utilization(self) -> dict[str, float]:
        """Compute average worker utilization, variance, and bin-packing efficiency."""
        worker_nodes = [n for n in self.nodes.values() if "control-plane" not in n.name]
        if not worker_nodes:
            return {"mean_worker_cpu_util": 0.0, "mean_worker_mem_util": 0.0, "bin_packing_efficiency": 0.0}

        cpu_utils = [n.cpu_utilization for n in worker_nodes]
        mem_utils = [n.mem_utilization for n in worker_nodes]

        mean_cpu = sum(cpu_utils) / len(cpu_utils)
        mean_mem = sum(mem_utils) / len(mem_utils)
        composite_util = (mean_cpu + mean_mem) / 2.0

        # Calculate variance to penalize fragmented allocation
        var_cpu = sum((u - mean_cpu) ** 2 for u in cpu_utils) / len(cpu_utils)
        var_mem = sum((u - mean_mem) ** 2 for u in mem_utils) / len(mem_utils)
        std_dev = math.sqrt((var_cpu + var_mem) / 2.0)

        # Bin-packing efficiency: reward high utilization while penalizing unbalanced node fragmentation
        balance_factor = max(0.0, 1.0 - min(0.6, std_dev * 1.2))
        bin_packing_efficiency = round(composite_util * balance_factor * 100, 2)

        return {
            "mean_worker_cpu_util": round(mean_cpu * 100, 2),
            "mean_worker_mem_util": round(mean_mem * 100, 2),
            "composite_worker_util": round(composite_util * 100, 2),
            "cpu_variance": round(var_cpu, 4),
            "mem_variance": round(var_mem, 4),
            "bin_packing_efficiency": bin_packing_efficiency,
        }


class ToyTwoNodeSimulator:
    """Baseline: Simplistic 2-node edge topology modeled after AgentEdge (Base Paper).

    Features:
    - 2 nodes: 'edge-node-1' (2C/4096MiB) and 'cloud-node-1' (8C/16384MiB).
    - Lacks Kubernetes namespace awareness, node taints, and pod affinity rules.
    """

    def __init__(self) -> None:
        self.nodes = {
            "edge-node-1": NodeState(name="edge-node-1", cpu_capacity=2.0, mem_capacity=4096.0),
            "cloud-node-1": NodeState(name="cloud-node-1", cpu_capacity=8.0, mem_capacity=16384.0),
        }

    def reset(self, initial_state: Optional[dict[str, Any]] = None) -> None:
        self.nodes = {
            "edge-node-1": NodeState(name="edge-node-1", cpu_capacity=2.0, mem_capacity=4096.0),
            "cloud-node-1": NodeState(name="cloud-node-1", cpu_capacity=8.0, mem_capacity=16384.0),
        }
        if initial_state:
            for k, alloc in initial_state.items():
                if k in self.nodes:
                    self.nodes[k].cpu_allocated = alloc.get("cpu_alloc", 0.0)
                    self.nodes[k].mem_allocated = alloc.get("mem_alloc", 0.0)

    def schedule_pod(self, name: str, cpu_req: float, mem_req: float, prefer_edge: bool = True) -> Optional[str]:
        """Simple flat placement without taints or namespace partitioning."""
        order = ["edge-node-1", "cloud-node-1"] if prefer_edge else ["cloud-node-1", "edge-node-1"]
        for node_name in order:
            node = self.nodes[node_name]
            if node.can_fit(cpu_req, mem_req):
                node.cpu_allocated = round(node.cpu_allocated + cpu_req, 4)
                node.mem_allocated = round(node.mem_allocated + mem_req, 2)
                node.pods[name] = {"name": name, "cpu_req": cpu_req, "mem_req": mem_req}
                return node_name
        return None

    def get_cluster_snapshot(self) -> dict[str, Any]:
        return {
            "total_nodes": 2,
            "nodes": {
                name: {"cpu_util": node.cpu_utilization, "mem_util": node.mem_utilization}
                for name, node in self.nodes.items()
            },
        }


class KubeSchedulerBaseline:
    """Standard Kubernetes LeastRequestedPriority heuristic scheduler for Baseline E1 & E4.

    Scores feasible nodes using the default Kubernetes formula:
    Score = (cpu_score + mem_score) / 2
    Where:
    cpu_score = (capacity.cpu - alloc.cpu) * 10 / capacity.cpu
    mem_score = (capacity.mem - alloc.mem) * 10 / capacity.mem
    """

    @staticmethod
    def schedule_first_fit_least_requested(
        pod_spec: Union[ProposedPlan, dict[str, Any]],
        nodes: list[NodeState],
    ) -> Optional[str]:
        if isinstance(pod_spec, ProposedPlan):
            cpu_req = pod_spec.cpu_req
            mem_req = pod_spec.mem_req
            tolerations = pod_spec.pod_spec.get("tolerations", [])
        else:
            cpu_req = pod_spec.get("cpu_req", 0.1)
            mem_req = pod_spec.get("mem_req", 128.0)
            tolerations = pod_spec.get("tolerations", [])

        feasible_nodes: list[tuple[float, str]] = []

        for node in nodes:
            # 1. Filter: Taint check
            if not node.tolerates_taints(tolerations):
                continue
            # 2. Filter: Capacity check
            if not node.can_fit(cpu_req, mem_req):
                continue

            # 3. Score: LeastRequestedPriority
            cpu_free_ratio = (node.cpu_free - cpu_req) / node.cpu_capacity if node.cpu_capacity > 0 else 0
            mem_free_ratio = (node.mem_free - mem_req) / node.mem_capacity if node.mem_capacity > 0 else 0
            score = (cpu_free_ratio * 10.0 + mem_free_ratio * 10.0) / 2.0

            feasible_nodes.append((score, node.name))

        if not feasible_nodes:
            return None

        # Sort descending by score; break ties deterministically by node name
        feasible_nodes.sort(key=lambda item: (-item[0], item[1]))
        return feasible_nodes[0][1]


class StaticHPABaseline:
    """Standard Kubernetes Horizontal Pod Autoscaler (HPA) heuristic baseline.

    Formula:
    desired_replicas = ceil(current_replicas * (current_util / target_util))
    """

    @staticmethod
    def evaluate_scaling(
        current_replicas: int,
        current_cpu_util_pct: float,
        target_cpu_util_pct: float = 80.0,
        min_replicas: int = 1,
        max_replicas: int = 10,
    ) -> int:
        if current_replicas <= 0:
            return min_replicas
        if target_cpu_util_pct <= 0:
            return current_replicas

        ratio = current_cpu_util_pct / target_cpu_util_pct
        desired = math.ceil(current_replicas * ratio)
        return max(min_replicas, min(max_replicas, desired))


def create_k8s_environment(use_k8s_trace_env: bool = True) -> Union[K8sMultiNodeEmulator, ToyTwoNodeSimulator]:
    """Factory creating either the 4-node K8s trace emulator or the toy 2-node simulator."""
    if use_k8s_trace_env:
        return K8sMultiNodeEmulator()
    return ToyTwoNodeSimulator()
