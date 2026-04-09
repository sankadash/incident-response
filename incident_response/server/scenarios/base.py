"""Base scenario definition."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict


@dataclass
class Scenario:
    """A single incident scenario with ground truth and setup logic."""

    task_id: str
    name: str
    alert_text: str
    ground_truth: Dict[str, Any]
    # Takes default service states dict, returns modified services with faults injected
    setup_fn: Callable[[Dict[str, Dict[str, Any]]], Dict[str, Dict[str, Any]]]
