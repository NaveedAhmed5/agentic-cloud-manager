# Rego Policy Definition for GuardEdge-K8s
# Enforces CIS Kubernetes Benchmark security constraints and operational quotas.

package k8s.safety

default allow = false

# -------------------------------------------------------------
# 1. Deny Privileged Security Contexts and Host Namespaces
# -------------------------------------------------------------
deny[msg] {
    input.privileged == true
    msg := "Security violation: Privileged container execution is strictly disallowed (CIS Benchmark 5.2.1)."
}

deny[msg] {
    input.host_network == true
    msg := "Security violation: Sharing host network namespace (hostNetwork: true) is prohibited."
}

deny[msg] {
    input.host_pid == true
    msg := "Security violation: Sharing host process namespace (hostPID: true) is prohibited."
}

# -------------------------------------------------------------
# 2. Deny Missing or Excessive Resource Requests
# -------------------------------------------------------------
deny[msg] {
    input.cpu_req <= 0
    msg := "Resource violation: Pod must declare positive CPU resource request."
}

deny[msg] {
    input.mem_req <= 0
    msg := "Resource violation: Pod must declare positive Memory resource request."
}

deny[msg] {
    # Maximum single container request cannot exceed 85% of largest node (8.0 cores * 0.85 = 6.8 cores)
    input.cpu_req > 6.8
    msg := sprintf("Resource quota violation: Requested CPU (%v cores) exceeds safe node limit (>85%% capacity).", [input.cpu_req])
}

deny[msg] {
    # Maximum single container request cannot exceed 85% of largest node (16384 MiB * 0.85 = 13926.4 MiB)
    input.mem_req > 13926.4
    msg := sprintf("Resource quota violation: Requested Memory (%v MiB) exceeds safe node limit (>85%% capacity).", [input.mem_req])
}

# -------------------------------------------------------------
# 3. Deny Unauthorized System Namespace Mutations
# -------------------------------------------------------------
deny[msg] {
    input.namespace == "kube-system"
    input.action != "inspect"
    msg := "Namespace isolation violation: Direct deployment or modification in 'kube-system' namespace is prohibited."
}

# -------------------------------------------------------------
# 4. Require Human-in-the-Loop (HITL) Authorization
# -------------------------------------------------------------
require_hitl[msg] {
    input.action == "drain_node"
    msg := "HITL required: Draining a Kubernetes node causes pod evictions and service disruption."
}

require_hitl[msg] {
    input.action == "delete_namespace"
    msg := "HITL required: Deleting a namespace permanently removes all contained workloads."
}

require_hitl[msg] {
    input.action == "scale"
    input.replicas > 5
    msg := sprintf("HITL required: Large-scale replica change (%v replicas) requires human operator verification.", [input.replicas])
}

# Allow when no deny rules are triggered
allow {
    count(deny) == 0
}

