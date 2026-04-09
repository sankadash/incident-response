"""Scenario registry for incident response tasks."""

from typing import Dict, Optional

from .base import Scenario
from .easy import EASY_SCENARIO
from .medium import MEDIUM_SCENARIO
from .hard import HARD_SCENARIO
from .generator import generate_scenario

# Static scenarios for backward compatibility (seed=None)
SCENARIO_REGISTRY: Dict[str, Scenario] = {
    "easy": EASY_SCENARIO,
    "medium": MEDIUM_SCENARIO,
    "hard": HARD_SCENARIO,
}


def get_scenario(task_id: str, seed: Optional[int] = None) -> Scenario:
    """Look up or generate a scenario.

    If seed is None, uses the static registry (backward compatible).
    If seed is provided, generates a new scenario procedurally.
    """
    if seed is not None:
        difficulty = task_id
        if difficulty not in ("easy", "medium", "hard"):
            raise KeyError(
                f"Unknown difficulty '{difficulty}'. Available: easy, medium, hard"
            )
        return generate_scenario(difficulty=difficulty, seed=seed)

    # Static registry path
    if task_id not in SCENARIO_REGISTRY:
        raise KeyError(
            f"Unknown task_id '{task_id}'. Available: {list(SCENARIO_REGISTRY.keys())}"
        )
    return SCENARIO_REGISTRY[task_id]
