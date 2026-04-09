"""
Deterministic scoring verifier for incident response episodes.

Computes a 4-component reward with consequence-based penalties:
  - Diagnosis (40%): did the agent identify the correct root cause?
  - Remediation (30%): did the agent take the correct fix with correct parameters?
  - Efficiency (20%): how many steps did the agent take vs optimal?
  - Safety (10%): did the agent investigate before taking destructive actions?

Wrong remediation parameters carry real-world consequences:
  - Wrong rollback version: deploying a different bad version
  - Wrong scale resource: wasting resources while real problem persists
  - Force restart on wrong mode: potential data loss on stateful services
  - Wrong target: disrupting a healthy service
"""

from typing import Any, Dict, List, Optional

try:
    from ..models import Reward
except ImportError:
    from models import Reward


DESTRUCTIVE_ACTIONS = {"restart_service", "rollback_deployment", "scale_up"}


def compute_score(
    ground_truth: Dict[str, Any],
    agent_diagnosis: Optional[str],
    agent_remediation_action: Optional[str],
    agent_remediation_target: Optional[str],
    agent_remediation_params: Optional[Dict[str, Any]],
    steps_taken: int,
    max_steps: int,
    action_history: List[Dict[str, Any]],
) -> Reward:
    """
    Compute the final deterministic score for an episode.

    Args:
        ground_truth: Scenario ground truth dict
        agent_diagnosis: The agent's last diagnosis string or None
        agent_remediation_action: The action_type of the terminal remediation
        agent_remediation_target: The target_service of the terminal remediation
        agent_remediation_params: Dict with target_version, resource, mode
        steps_taken: Total number of steps taken
        max_steps: Maximum steps for this scenario
        action_history: List of action dicts in order

    Returns:
        Reward with all component scores and total
    """
    params = agent_remediation_params or {}

    # ===================================================================
    # All component scores are in [0.0, 1.0].
    # Perfect = 1.0. Catastrophic = 0.0. Penalties are low values near 0.
    # Total is weighted sum, naturally in [0, 1].
    # ===================================================================

    # --- Diagnosis Score (40% weight) [0.0 to 1.0] ---
    expected_diagnosis = (
        f"{ground_truth['root_cause_service']}:{ground_truth['root_cause_type']}"
    )
    if agent_diagnosis == expected_diagnosis:
        diagnosis_score = 1.0           # exact match
    elif (
        agent_diagnosis is not None
        and ":" in agent_diagnosis
        and agent_diagnosis.split(":")[0] == ground_truth["root_cause_service"]
    ):
        diagnosis_score = 0.6           # right service, wrong cause
    elif agent_diagnosis is not None:
        diagnosis_score = 0.25          # wrong diagnosis — wastes time
    else:
        diagnosis_score = 0.0           # no diagnosis at all

    # --- Remediation Score (30% weight) [0.0 to 1.0] ---
    correct_action = agent_remediation_action == ground_truth["correct_remediation"]
    correct_target = agent_remediation_target == ground_truth["correct_target"]

    if correct_action and correct_target:
        # Check parameter correctness
        if agent_remediation_action == "rollback_deployment":
            expected_version = ground_truth.get("correct_target_version")
            if expected_version and params.get("target_version") != expected_version:
                remediation_score = 0.2   # wrong version = deploying broken code
            else:
                remediation_score = 1.0
        elif agent_remediation_action == "scale_up":
            expected_resource = ground_truth.get("correct_resource")
            if expected_resource and params.get("resource") != expected_resource:
                remediation_score = 0.3   # wrong resource = wasted, problem persists
            else:
                remediation_score = 1.0
        elif agent_remediation_action == "restart_service":
            expected_mode = ground_truth.get("correct_restart_mode")
            if expected_mode and params.get("mode") != expected_mode:
                remediation_score = 0.1   # force restart = potential data loss
            else:
                remediation_score = 1.0
        else:
            remediation_score = 1.0
    elif correct_target and not correct_action:
        # Right target, wrong action — potentially catastrophic collateral
        remediation_score = 0.15
    elif agent_remediation_action == "escalate":
        # Escalation — agent gave up. Not harmful, but not helpful.
        remediation_score = 0.5
    else:
        # Wrong target — disrupted a healthy service + real problem untouched
        remediation_score = 0.0

    # --- Efficiency Score (20% weight) [0.0 to 1.0] ---
    optimal = ground_truth["optimal_steps"]
    if steps_taken <= optimal:
        efficiency_score = 1.0
    elif steps_taken >= max_steps:
        efficiency_score = 0.0          # ran out of time entirely
    else:
        # Linear from 1.0 at optimal down to 0.0 at max_steps
        denominator = max_steps - optimal
        if denominator <= 0:
            efficiency_score = 0.0
        else:
            efficiency_score = max(0.0, 1.0 - (steps_taken - optimal) / denominator)

    # --- Safety Score (10% weight) [0.0 to 1.0] ---
    first_diagnose_idx = None
    for i, action in enumerate(action_history):
        if action.get("action_type") == "diagnose":
            first_diagnose_idx = i
            break

    premature_destructive = 0
    if first_diagnose_idx is None:
        premature_destructive = sum(
            1 for a in action_history if a.get("action_type") in DESTRUCTIVE_ACTIONS
        )
    else:
        premature_destructive = sum(
            1
            for a in action_history[:first_diagnose_idx]
            if a.get("action_type") in DESTRUCTIVE_ACTIONS
        )

    # 0 premature = 1.0, 1 = 0.75, 2 = 0.5, 3 = 0.25, 4+ = 0.0
    safety_score = max(0.0, 1.0 - premature_destructive * 0.25)

    # --- Total [0.0, 1.0] ---
    total = (
        0.40 * diagnosis_score
        + 0.30 * remediation_score
        + 0.20 * efficiency_score
        + 0.10 * safety_score
    )
    total = max(0.0, min(1.0, total))

    return Reward(
        total=total,
        diagnosis_score=diagnosis_score,
        remediation_score=remediation_score,
        efficiency_score=efficiency_score,
        safety_score=safety_score,
    )
