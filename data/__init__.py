"""Data package for GuardEdge-K8s benchmarks and cluster traces."""

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent


def load_dev_traces() -> list[dict[str, Any]]:
    """Load the 30 dev validation trace scenarios."""
    file_path = DATA_DIR / "alibaba_traces_dev.json"
    return json.loads(file_path.read_text(encoding="utf-8"))


def load_test_traces() -> list[dict[str, Any]]:
    """Load the 100 locked evaluation trace scenarios."""
    file_path = DATA_DIR / "alibaba_traces_test.json"
    return json.loads(file_path.read_text(encoding="utf-8"))


def load_adversarial_suite() -> list[dict[str, Any]]:
    """Load the 40 adversarial and control scenarios."""
    file_path = DATA_DIR / "adversarial_suite_test.json"
    return json.loads(file_path.read_text(encoding="utf-8"))
