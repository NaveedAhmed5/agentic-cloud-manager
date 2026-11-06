"""System configuration and ablation switches for GuardEdge-K8s.

Supports research gap ablations:
- Gap 1: 4-node K8s trace cluster vs 2-node toy simulator (use_k8s_trace_env)
- Gap 2: Deterministic Rego Policy-as-Code + HITL gate + loop cap (use_opa_guard)
- Gap 3: Pre-execution prompt injection & telemetry poisoning filter (use_adv_sanitizer)
- Baseline: Offline dry-run simulator + critic loop (use_actsimcrit)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

# Automatically locate and load .env file from project root
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)
else:
    load_dotenv()


class SystemConfig(BaseModel):
    """Configuration and ablation flags for the GuardEdge-K8s framework."""

    # ---------------------------------------------------------
    # Research Gap Ablation Switches
    # ---------------------------------------------------------
    use_k8s_trace_env: bool = Field(
        default=True,
        description="Gap 1: 4-node K8s cluster with trace metrics vs 2-node toy simulator.",
    )
    use_opa_guard: bool = Field(
        default=True,
        description="Gap 2: Deterministic Rego Policy-as-Code + HITL gate + loop cap.",
    )
    use_adv_sanitizer: bool = Field(
        default=True,
        description="Gap 3: Pre-execution prompt injection & telemetry poisoning filter.",
    )
    use_actsimcrit: bool = Field(
        default=True,
        description="Base paper: Offline dry-run simulator + critic loop.",
    )

    # ---------------------------------------------------------
    # Reflection & Loop Controls
    # ---------------------------------------------------------
    max_reflection_loops: int = Field(
        default=3,
        description=(
            "Max reflection loop count. Defaults to 3 when use_opa_guard=True, "
            "or 10 when use_opa_guard=False to observe unbounded loop deadlocks."
        ),
    )

    # ---------------------------------------------------------
    # Runtime & Model Execution Settings
    # ---------------------------------------------------------
    seed: int = Field(
        default=42,
        description="Deterministic random seed for benchmarks and cluster traces.",
    )
    random_seed: int = Field(
        default=42,
        description="Alias for seed to support environment configuration.",
    )
    use_mock_llm: bool = Field(
        default=True,
        description="Use deterministic mock LLM provider instead of live API calls.",
    )
    llm_api_key: str = Field(
        default_factory=lambda: os.getenv("LLM_API_KEY", "your_api_key_here"),
        description="API key for LLM orchestrator.",
    )
    llm_base_url: str = Field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        description="Base URL for OpenAI-compatible endpoint.",
    )
    llm_model: str = Field(
        default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini"),
        description="Target model identifier.",
    )
    k8s_execution_mode: Literal["emulator", "live_k8s"] = Field(
        default_factory=lambda: os.getenv("K8S_EXECUTION_MODE", "emulator"),  # type: ignore[return-value]
        description="Cluster execution target: 'emulator' (simulated/trace) or 'live_k8s'.",
    )

    @model_validator(mode="before")
    @classmethod
    def resolve_reflection_and_seeds(cls, data: Any) -> Any:
        """Resolve seed aliasing and adjust reflection limit based on OPA guard."""
        if isinstance(data, dict):
            # Sync seed and random_seed
            if "random_seed" in data and "seed" not in data:
                data["seed"] = data["random_seed"]
            elif "seed" in data and "random_seed" not in data:
                data["random_seed"] = data["seed"]

            # If OPA guard is disabled and max_reflection_loops wasn't explicitly overridden,
            # allow loop count to expand to 10 for observing deadlocks
            if data.get("use_opa_guard") is False and "max_reflection_loops" not in data:
                data["max_reflection_loops"] = 10

        return data

    @classmethod
    def from_env(cls, **overrides: Any) -> SystemConfig:
        """Instantiate SystemConfig reading from environment variables with optional overrides."""
        env_dict: dict[str, Any] = {
            "use_mock_llm": os.getenv("USE_MOCK_LLM", "true").lower() in ("true", "1", "yes"),
            "k8s_execution_mode": os.getenv("K8S_EXECUTION_MODE", "emulator"),
            "llm_api_key": os.getenv("LLM_API_KEY", "your_api_key_here"),
            "llm_base_url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            "llm_model": os.getenv("LLM_MODEL", "gpt-4o-mini"),
            "random_seed": int(os.getenv("RANDOM_SEED", "42")),
            "seed": int(os.getenv("RANDOM_SEED", "42")),
        }
        # Apply any explicit argument overrides
        env_dict.update(overrides)
        return cls(**env_dict)


# Default global instance for convenience
default_config = SystemConfig()

