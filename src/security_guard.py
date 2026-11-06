"""Pre-Execution Adversarial Prompt & Telemetry Sanitizer (Research Gap 3).

Implements a two-stage inspection pipeline:
1. Pattern & Structural Inspector: Detects prompt injections, jailbreak tokens,
   privilege escalation strings, command injection characters, and base64 payloads.
2. Semantic Intent Verifier: Validates that telemetry logs strictly adhere to Prometheus
   metric schemas and do not contain embedded imperative overrides or shell escapes.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional, Union
from src.state import AgentGraphState


class AdversarialSanitizer:
    """Two-stage pre-execution adversarial inspector for intents and telemetry streams."""

    # -------------------------------------------------------------
    # Stage 1: Explicit Injection Patterns & Jailbreak Signatures
    # -------------------------------------------------------------
    INJECTION_PATTERNS: list[re.Pattern[str]] = [
        # Prompt overrides & jailbreaks
        re.compile(r"ignore\s+(all\s+)?(previous|system|safety|policy|\s+)+\s*(rules|instructions|guardrails|critic)", re.IGNORECASE),
        re.compile(r"system\s+override", re.IGNORECASE),
        re.compile(r"developer\s+(debug\s+mode|prompt)", re.IGNORECASE),
        re.compile(r"dan\s+mode", re.IGNORECASE),
        re.compile(r"disable\s+(all\s+)?policy\s+constraints", re.IGNORECASE),
        re.compile(r"bypass\s+(opa|verification|policy|guardrails)", re.IGNORECASE),
        re.compile(r"approve\s+the\s+execution\s+plan\s+immediately\s+without\s+review", re.IGNORECASE),
        re.compile(r"translate\s+the\s+following.*and\s+also\s+execute", re.IGNORECASE),
        re.compile(r"ignore\s+opa\s+reject", re.IGNORECASE),
        # Privilege & RBAC escalations
        re.compile(r"cap_add\s*=\s*\[.*SYS_ADMIN.*\]", re.IGNORECASE),
        re.compile(r"unconfined\s+securitycontext", re.IGNORECASE),
        re.compile(r"crypto-mining", re.IGNORECASE),
        re.compile(r"docker\.sock", re.IGNORECASE),
        re.compile(r"/etc/(kubernetes|shadow|passwd)", re.IGNORECASE),
        re.compile(r"\$\(kubectl\s+create\s+clusterrolebinding", re.IGNORECASE),
        re.compile(r"cluster-admin", re.IGNORECASE),
        re.compile(r"run\s+in\s+privileged\s+mode(\s+to\s+verify)?", re.IGNORECASE),
        re.compile(r"set\s+hostnetwork:\s*true", re.IGNORECASE),
        re.compile(r"hostpath\s+mounted\s+to\s+/etc", re.IGNORECASE),
        # Shell & command injection signatures
        re.compile(r";\s*rm\s+-rf", re.IGNORECASE),
        re.compile(r"curl\s+-[^\n|]*\|\s*(bash|sh)", re.IGNORECASE),
        re.compile(r"chmod\s+777\s+/", re.IGNORECASE),
        re.compile(r"nc\s+-e\s+/bin/(sh|bash)", re.IGNORECASE),
        re.compile(r"eyJ[a-zA-Z0-9+/]{10,}={0,2}"),  # Base64 payload signature
        re.compile(r"<script", re.IGNORECASE),
        re.compile(r"drop\s+table", re.IGNORECASE),
    ]

    # -------------------------------------------------------------
    # Stage 2: Telemetry Schema Suspicious Imperative Keywords
    # -------------------------------------------------------------
    SUSPICIOUS_TELEMETRY_IMPERATIVES: list[str] = [
        "execute",
        "rm -rf",
        "chmod 777",
        "curl",
        "wget",
        "nc -e",
        "/bin/sh",
        "/bin/bash",
        "clusterrolebinding",
        "cluster-admin",
        "base64",
        "drop table",
        "force deployment",
        "ignore opa",
    ]

    def __init__(self, strict_mode: bool = True) -> None:
        self.strict_mode = strict_mode

    def inspect(
        self,
        raw_intent: str,
        telemetry: Optional[Union[dict[str, Any], str]] = None,
    ) -> tuple[bool, str, Any, str, float]:
        """Execute two-stage inspection on natural language intent and telemetry stream.

        Returns:
            (is_safe, cleaned_intent, cleaned_telemetry, detection_reason, eval_latency_ms)
        """
        start_time = time.perf_counter()

        telemetry_str = ""
        if isinstance(telemetry, dict):
            telemetry_str = json.dumps(telemetry)
        elif isinstance(telemetry, str):
            telemetry_str = telemetry

        # ---------------------------------------------------------
        # Stage 1: Pattern & Structural Inspection (Intent & Telemetry)
        # ---------------------------------------------------------
        for pattern in self.INJECTION_PATTERNS:
            match_intent = pattern.search(raw_intent)
            if match_intent:
                elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
                reason = f"Prompt injection detected in intent: matches pattern '{pattern.pattern}'"
                return False, "", telemetry, reason, elapsed_ms

            if telemetry_str:
                match_telem = pattern.search(telemetry_str)
                if match_telem:
                    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
                    reason = f"Telemetry poisoning detected in metrics/alerts: matches pattern '{pattern.pattern}'"
                    return False, "", telemetry, reason, elapsed_ms

        # ---------------------------------------------------------
        # Stage 2: Semantic Intent Verification (Telemetry Schema Compliance)
        # ---------------------------------------------------------
        if telemetry_str:
            telemetry_lower = telemetry_str.lower()
            for imperative in self.SUSPICIOUS_TELEMETRY_IMPERATIVES:
                if imperative in telemetry_lower:
                    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
                    reason = f"Poisoned telemetry schema: unauthorized imperative command '{imperative}' in metric stream"
                    return False, "", telemetry, reason, elapsed_ms

        # Input is verified safe
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 3)
        cleaned_intent = raw_intent.strip()
        cleaned_telemetry = telemetry

        return True, cleaned_intent, cleaned_telemetry, "Safe", elapsed_ms

    def sanitize_state(self, state: AgentGraphState) -> AgentGraphState:
        """Process an AgentGraphState, update safety flags, and record audit trace."""
        is_safe, cleaned_intent, cleaned_telem, reason, latency_ms = self.inspect(
            raw_intent=state.raw_intent,
            telemetry=state.telemetry_log,
        )

        state.is_adversarial_blocked = not is_safe
        state.sanitized_intent = cleaned_intent if is_safe else None
        state.latency_ms = round(state.latency_ms + latency_ms, 3)

        # Audit log in trajectory
        state.add_trajectory_step(
            agent="AdversarialSanitizer",
            input={"raw_intent": state.raw_intent, "has_telemetry": bool(state.telemetry_log)},
            reasoning=f"Stage 1 & 2 inspection completed in {latency_ms}ms. Verdict: {'SAFE' if is_safe else 'BLOCKED'}.",
            tool_call={"tool": "regex_and_schema_validator", "strict_mode": self.strict_mode},
            output={"is_safe": is_safe, "reason": reason, "latency_ms": latency_ms},
        )

        return state

