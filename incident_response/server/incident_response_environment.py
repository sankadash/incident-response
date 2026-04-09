# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Incident Response Environment Implementation.

An SRE incident triage environment where an AI agent investigates
production alerts in a microservice system, diagnoses root causes,
and takes remediation actions. Scored deterministically.
"""

from copy import deepcopy
from typing import Any, Dict, List, Optional
from uuid import uuid4

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import (
        IncidentResponseAction,
        IncidentResponseObservation,
        QueryResult,
        ServiceStatus,
    )
    from .scenarios import get_scenario
    from .scenarios.base import Scenario
    from .service_graph import build_default_service_states, DEPENDENCY_GRAPH
    from .verifier import compute_score
except ImportError:
    from models import (
        IncidentResponseAction,
        IncidentResponseObservation,
        QueryResult,
        ServiceStatus,
    )
    from server.scenarios import get_scenario
    from server.scenarios.base import Scenario
    from server.service_graph import build_default_service_states, DEPENDENCY_GRAPH
    from server.verifier import compute_score

try:
    from .scenarios.templates import METRIC_THRESHOLDS, METRIC_NAME_MAP
except ImportError:
    from server.scenarios.templates import METRIC_THRESHOLDS, METRIC_NAME_MAP


INVESTIGATION_ACTIONS = {
    "check_logs",
    "check_metrics",
    "check_dependencies",
    "check_deployments",
}
REMEDIATION_ACTIONS = {"restart_service", "rollback_deployment", "scale_up"}
ALL_ACTIONS = list(INVESTIGATION_ACTIONS) + [
    "diagnose",
    "restart_service",
    "rollback_deployment",
    "scale_up",
    "escalate",
]
VALID_LOG_LEVELS = {"ALL", "FATAL", "ERROR", "WARN", "INFO", "DEBUG"}
VALID_METRIC_NAMES = {"latency", "error_rate", "cpu", "memory", "rpm", "all"}
VALID_RESOURCES = {"cpu", "memory", "connections", "replicas"}
VALID_MODES = {"graceful", "force"}
VALID_SEVERITIES = {"low", "medium", "high", "critical"}


class IncidentResponseEnvironment(Environment):
    """
    SRE incident triage environment.

    The agent receives a production alert, investigates by querying logs,
    metrics, and dependencies, then diagnoses the root cause and takes
    a remediation action. Scored deterministically on diagnosis accuracy,
    remediation correctness, efficiency, and safety.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        super().__init__()
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._scenario: Optional[Scenario] = None
        self._services: Dict[str, Dict[str, Any]] = {}
        self._original_services: Dict[str, Dict[str, Any]] = {}
        self._baseline_services: Dict[str, Dict[str, Any]] = {}
        self._action_history: List[Dict[str, Any]] = []
        self._last_diagnosis: Optional[str] = None
        self._last_remediation_action: Optional[str] = None
        self._last_remediation_target: Optional[str] = None
        self._last_remediation_params: Optional[Dict[str, Any]] = None
        self._done: bool = False
        self._last_query_result: Optional[QueryResult] = None
        self._temporarily_fixed: set = set()

    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IncidentResponseObservation:
        """Reset the environment with a specific task scenario."""
        task_id = kwargs.get("task_id", "easy")
        self._scenario = get_scenario(task_id, seed=seed)
        gt = self._scenario.ground_truth

        # Reset state
        self._state = State(
            episode_id=episode_id or str(uuid4()), step_count=0
        )
        self._action_history = []
        self._last_diagnosis = None
        self._last_remediation_action = None
        self._last_remediation_target = None
        self._last_remediation_params = None
        self._done = False
        self._last_query_result = None
        self._temporarily_fixed = set()

        # Store healthy baseline for include_history comparisons
        self._baseline_services = build_default_service_states()

        # Build and configure services
        services = build_default_service_states()
        self._services = self._scenario.setup_fn(services)
        self._original_services = deepcopy(self._services)

        return IncidentResponseObservation(
            alert=self._scenario.alert_text,
            service_statuses=self._build_service_statuses(),
            last_query_result=None,
            step_number=0,
            max_steps=gt["max_steps"],
            available_actions=ALL_ACTIONS,
            done=False,
            reward=0.0,
        )

    def step(
        self,
        action: IncidentResponseAction,
        timeout_s: Optional[float] = None,
        **kwargs: Any,
    ) -> IncidentResponseObservation:  # type: ignore[override]
        """Execute one step in the environment."""
        if self._scenario is None:
            return self._error_obs("Environment not initialized. Call reset() first.")

        if self._done:
            return self._terminal_obs()

        gt = self._scenario.ground_truth

        # Increment step
        self._state.step_count += 1

        # Record action with all parameters
        action_record = {
            "action_type": action.action_type,
            "target_service": action.target_service,
            "diagnosis": action.diagnosis,
            "log_level": action.log_level,
            "keyword": action.keyword,
            "target_version": action.target_version,
            "resource": action.resource,
            "mode": action.mode,
        }
        self._action_history.append(action_record)

        # Re-apply faults for any temporarily fixed services
        self._restore_temporary_fixes()

        # --- Per-step penalty: repeated action (escalating) ---
        # Compare full action signature — same type + target + parameters.
        # check_logs(payment-svc, ERROR) and check_logs(payment-svc, DEBUG) are DIFFERENT actions.
        def _action_signature(a: dict) -> tuple:
            return (
                a.get("action_type"),
                a.get("target_service"),
                a.get("log_level"),
                a.get("keyword"),
                a.get("diagnosis"),
                a.get("target_version"),
                a.get("resource"),
                a.get("mode"),
            )

        # =================================================================
        # Per-step reward system — all values in [0.0, 1.0].
        #
        # Reward tiers:
        #   0.70  Productive investigation on root cause with good params
        #   0.50  Productive investigation on related service
        #   0.40  Neutral investigation (unrelated but valid)
        #   0.30  Repeated action (escalating: 0.30, 0.25, 0.20, 0.15, 0.10)
        #   0.10  Malformed action / missing params
        #   0.05  Wrong target remediation / premature remediation
        # =================================================================

        # Compute repeat count for this exact action signature
        curr_sig = _action_signature(action_record)
        repeat_count = sum(
            1 for a in self._action_history[:-1]
            if _action_signature(a) == curr_sig
        )

        # Base reward: 0.40 for valid actions, reduced by repeats
        if repeat_count > 0:
            base_reward = max(0.10, 0.30 - (repeat_count - 1) * 0.05)
        else:
            base_reward = 0.40

        # Validate action type
        if action.action_type not in ALL_ACTIONS:
            return self._step_obs(
                query_result=QueryResult(
                    query_type="error",
                    target_service=action.target_service or "unknown",
                    data=f"Invalid action_type: '{action.action_type}'. Valid: {ALL_ACTIONS}",
                ),
                reward=0.05,
            )

        # Validate target_service for actions that require it
        if action.action_type != "escalate" and not action.target_service:
            return self._step_obs(
                query_result=QueryResult(
                    query_type="error",
                    target_service="unknown",
                    data=f"target_service is required for action_type '{action.action_type}'",
                ),
                reward=0.05,
            )

        if (
            action.target_service
            and action.target_service not in self._services
        ):
            return self._step_obs(
                query_result=QueryResult(
                    query_type="error",
                    target_service=action.target_service,
                    data=f"Unknown service: '{action.target_service}'. Valid: {list(self._services.keys())}",
                ),
                reward=0.05,
            )

        # Premature remediation reduces base reward
        if action.action_type in REMEDIATION_ACTIONS and self._last_diagnosis is None:
            base_reward = min(base_reward, 0.15)

        # Route action
        if action.action_type in INVESTIGATION_ACTIONS:
            return self._handle_investigation(action, base_reward)
        elif action.action_type == "diagnose":
            return self._handle_diagnose(action, base_reward)
        elif action.action_type in REMEDIATION_ACTIONS:
            return self._handle_remediation(action, base_reward)
        elif action.action_type == "escalate":
            return self._handle_escalate(action)
        else:
            return self._step_obs(reward=base_reward)

    @property
    def state(self) -> State:
        return self._state

    # --- Action Handlers ---

    def _handle_investigation(
        self, action: IncidentResponseAction, base_reward: float = 0.40
    ) -> IncidentResponseObservation:
        """Handle parameterized investigation actions."""
        svc = self._services[action.target_service]

        if action.action_type == "check_logs":
            data = self._handle_check_logs(svc, action)
        elif action.action_type == "check_metrics":
            data = self._handle_check_metrics(svc, action)
        elif action.action_type == "check_dependencies":
            data = self._handle_check_dependencies(svc, action)
        elif action.action_type == "check_deployments":
            data = self._handle_check_deployments(svc, action)
        else:
            data = "Unknown investigation type"

        # Parameter validation errors
        if isinstance(data, str) and data.startswith("ERROR:"):
            return self._step_obs(
                query_result=QueryResult(
                    query_type="error",
                    target_service=action.target_service,
                    data=data,
                ),
                reward=0.10,
            )

        # Base + investigation bonus (capped at 0.70)
        bonus = self._compute_investigation_reward(action)
        reward = min(base_reward + bonus, 0.70)

        qr = QueryResult(
            query_type=action.action_type,
            target_service=action.target_service,
            data=data,
        )
        return self._step_obs(query_result=qr, reward=reward)

    def _handle_check_logs(self, svc: Dict, action: IncidentResponseAction) -> Any:
        """check_logs with log_level filter, keyword search, and tail limit."""
        logs = svc["recent_logs"]

        # Filter by log_level
        log_level = (action.log_level or "ALL").upper()
        if log_level not in VALID_LOG_LEVELS:
            return f"ERROR: Invalid log_level '{log_level}'. Valid: {sorted(VALID_LOG_LEVELS)}"
        if log_level != "ALL":
            logs = [l for l in logs if l.get("level") == log_level]

        # Filter by keyword
        if action.keyword:
            kw = action.keyword.lower()
            logs = [l for l in logs if kw in l.get("message", "").lower()]

        # Apply tail limit
        tail = min(action.tail or 10, 50)
        return logs[-tail:]

    def _handle_check_metrics(self, svc: Dict, action: IncidentResponseAction) -> Any:
        """check_metrics with optional specific metric and history comparison."""
        metrics = svc["metrics"]
        metric_name = (action.metric_name or "all").lower()

        if metric_name not in VALID_METRIC_NAMES:
            return f"ERROR: Invalid metric_name '{metric_name}'. Valid: {sorted(VALID_METRIC_NAMES)}"

        if metric_name == "all":
            result = dict(metrics)
        else:
            key = METRIC_NAME_MAP[metric_name]
            value = metrics.get(key, 0)
            thresholds = METRIC_THRESHOLDS.get(key, {})
            status = "normal"
            if "critical" in thresholds and value >= thresholds["critical"]:
                status = "CRITICAL"
            elif "warning" in thresholds and value >= thresholds["warning"]:
                status = "WARNING"
            result = {
                "metric": key,
                "value": value,
                "unit": thresholds.get("unit", ""),
                "status": status,
                "thresholds": {k: v for k, v in thresholds.items() if k != "unit"},
            }

        # Include history comparison if requested
        if action.include_history:
            baseline = self._baseline_services.get(svc["name"], {}).get("metrics", {})
            if metric_name == "all":
                result = {
                    "current": dict(metrics),
                    "baseline_1h_ago": dict(baseline),
                    "changes": {
                        k: {"current": metrics.get(k, 0), "baseline": baseline.get(k, 0),
                            "delta": round(metrics.get(k, 0) - baseline.get(k, 0), 2)}
                        for k in metrics
                    },
                }
            else:
                key = METRIC_NAME_MAP[metric_name]
                baseline_val = baseline.get(key, 0)
                result["baseline_1h_ago"] = baseline_val
                result["delta"] = round(value - baseline_val, 2)

        return result

    def _handle_check_dependencies(self, svc: Dict, action: IncidentResponseAction) -> Any:
        """check_dependencies with depth control and optional metrics."""
        depth = action.depth or 1
        if depth not in (1, 2):
            return f"ERROR: Invalid depth '{depth}'. Valid: 1 (direct) or 2 (transitive)"

        deps = svc["dependencies"]
        dep_info = []
        for dep_name in deps:
            dep_svc = self._services[dep_name]
            entry: Dict[str, Any] = {"name": dep_name, "status": dep_svc["status"]}

            if action.include_metrics:
                entry["metrics"] = {
                    "latency_p99_ms": dep_svc["metrics"]["latency_p99_ms"],
                    "error_rate_pct": dep_svc["metrics"]["error_rate_pct"],
                    "cpu_pct": dep_svc["metrics"]["cpu_pct"],
                }

            if depth >= 2:
                transitive = []
                for trans_name in dep_svc.get("dependencies", []):
                    trans_svc = self._services[trans_name]
                    trans_entry: Dict[str, Any] = {"name": trans_name, "status": trans_svc["status"]}
                    if action.include_metrics:
                        trans_entry["metrics"] = {
                            "latency_p99_ms": trans_svc["metrics"]["latency_p99_ms"],
                            "error_rate_pct": trans_svc["metrics"]["error_rate_pct"],
                            "cpu_pct": trans_svc["metrics"]["cpu_pct"],
                        }
                    transitive.append(trans_entry)
                entry["dependencies"] = transitive

            dep_info.append(entry)
        return dep_info

    def _handle_check_deployments(self, svc: Dict, action: IncidentResponseAction) -> Any:
        """check_deployments with optional changelog."""
        deployments = svc["recent_deployments"]
        if action.include_changelog:
            return deployments
        # Strip changelog from output
        return [{k: v for k, v in d.items() if k != "changelog"} for d in deployments]

    def _handle_diagnose(
        self, action: IncidentResponseAction, base_reward: float = 0.40
    ) -> IncidentResponseObservation:
        """Record the agent's diagnosis."""
        if not action.diagnosis:
            return self._step_obs(
                query_result=QueryResult(
                    query_type="error",
                    target_service=action.target_service or "unknown",
                    data="diagnosis field is required for diagnose action. Format: 'service_name:cause_type'",
                ),
                reward=0.05,
            )

        self._last_diagnosis = action.diagnosis

        # Diagnosis quality reward (direct values, no negatives)
        gt = self._scenario.ground_truth
        expected = f"{gt['root_cause_service']}:{gt['root_cause_type']}"
        if action.diagnosis == expected:
            reward = 0.70  # exact match
        elif action.diagnosis and ":" in action.diagnosis and action.diagnosis.split(":")[0] == gt["root_cause_service"]:
            reward = 0.50  # right service, wrong cause
        else:
            reward = 0.15  # wrong diagnosis — low but not zero (agent tried)

        qr = QueryResult(
            query_type="diagnose",
            target_service=action.target_service or "",
            data=f"Diagnosis recorded: {action.diagnosis}",
        )
        return self._step_obs(query_result=qr, reward=reward)

    def _handle_remediation(
        self, action: IncidentResponseAction, base_reward: float = 0.40
    ) -> IncidentResponseObservation:
        """Handle parameterized remediation actions. All rewards in [0, 1]."""
        gt = self._scenario.ground_truth

        # --- Validate required parameters (missing = low reward, not negative) ---
        if action.action_type == "rollback_deployment" and not action.target_version:
            return self._step_obs(
                query_result=QueryResult(
                    query_type="error", target_service=action.target_service,
                    data="target_version is REQUIRED for rollback_deployment. Use check_deployments to find the previous stable version.",
                ), reward=0.05)

        if action.action_type == "scale_up":
            if not action.resource:
                return self._step_obs(
                    query_result=QueryResult(
                        query_type="error", target_service=action.target_service,
                        data=f"resource is REQUIRED for scale_up. Valid: {sorted(VALID_RESOURCES)}.",
                    ), reward=0.05)
            if action.resource not in VALID_RESOURCES:
                return self._step_obs(
                    query_result=QueryResult(
                        query_type="error", target_service=action.target_service,
                        data=f"Invalid resource '{action.resource}'. Valid: {sorted(VALID_RESOURCES)}",
                    ), reward=0.10)

        if action.action_type == "restart_service":
            if not action.mode:
                return self._step_obs(
                    query_result=QueryResult(
                        query_type="error", target_service=action.target_service,
                        data=f"mode is REQUIRED for restart_service. Valid: {sorted(VALID_MODES)}.",
                    ), reward=0.05)
            if action.mode not in VALID_MODES:
                return self._step_obs(
                    query_result=QueryResult(
                        query_type="error", target_service=action.target_service,
                        data=f"Invalid mode '{action.mode}'. Valid: {sorted(VALID_MODES)}",
                    ), reward=0.10)

        # --- Determine correctness ---
        action_type_correct = action.action_type == gt["correct_remediation"]
        target_correct = action.target_service == gt["correct_target"]

        params_correct = True
        if action.action_type == "rollback_deployment":
            expected = gt.get("correct_target_version")
            if expected and action.target_version != expected:
                params_correct = False
        elif action.action_type == "scale_up":
            expected = gt.get("correct_resource")
            if expected and action.resource != expected:
                params_correct = False
        elif action.action_type == "restart_service":
            expected = gt.get("correct_restart_mode")
            if expected and action.mode != expected:
                params_correct = False

        is_fully_correct = action_type_correct and target_correct and params_correct

        rem_params = {
            "target_version": action.target_version,
            "resource": action.resource,
            "mode": action.mode,
        }

        # ── Fully correct: episode ends with verifier score ──
        if is_fully_correct:
            self._done = True
            self._last_remediation_action = action.action_type
            self._last_remediation_target = action.target_service
            self._last_remediation_params = rem_params
            reward = self._compute_final_reward()

            final_reward = reward.total
            if self._last_diagnosis is None:
                final_reward = min(final_reward * 0.25, 0.15)

            self._services = self._baseline_services

            qr = QueryResult(
                query_type=action.action_type,
                target_service=action.target_service,
                data=f"Remediation successful: {action.action_type} on {action.target_service}",
            )
            return self._terminal_obs(query_result=qr, reward=final_reward)

        # ── Right action + target, wrong params ──
        elif action_type_correct and target_correct and not params_correct:
            if action.action_type == "restart_service":
                # Wrong mode still restarts — episode ends with penalized score
                self._done = True
                self._last_remediation_action = action.action_type
                self._last_remediation_target = action.target_service
                self._last_remediation_params = rem_params
                reward = self._compute_final_reward()

                final_reward = reward.total
                if self._last_diagnosis is None:
                    final_reward = min(final_reward * 0.25, 0.15)

                self._services = self._baseline_services

                qr = QueryResult(
                    query_type=action.action_type,
                    target_service=action.target_service,
                    data=f"Service restarted with mode='{action.mode}'. WARNING: May have unintended consequences.",
                )
                return self._terminal_obs(query_result=qr, reward=final_reward)
            else:
                # Wrong version/resource — doesn't fix, symptoms return
                self._temporarily_fixed.add(action.target_service)
                self._last_remediation_action = action.action_type
                self._last_remediation_target = action.target_service
                self._last_remediation_params = rem_params

                self._services[action.target_service]["status"] = "healthy"
                self._services[action.target_service]["metrics"]["error_rate_pct"] = 0.5
                self._services[action.target_service]["metrics"]["latency_p99_ms"] = 50.0

                qr = QueryResult(
                    query_type=action.action_type,
                    target_service=action.target_service,
                    data=f"{action.action_type} applied to {action.target_service}. Service appears to recover...",
                )
                if self._state.step_count >= gt["max_steps"]:
                    self._done = True
                    return self._terminal_obs(query_result=qr, reward=self._compute_final_reward().total)

                return self._step_obs(query_result=qr, reward=0.10)  # wrong params

        # ── Right target, wrong action type ──
        elif target_correct and not action_type_correct:
            self._temporarily_fixed.add(action.target_service)
            self._last_remediation_action = action.action_type
            self._last_remediation_target = action.target_service
            self._last_remediation_params = rem_params

            self._services[action.target_service]["status"] = "healthy"
            self._services[action.target_service]["metrics"]["error_rate_pct"] = 0.5
            self._services[action.target_service]["metrics"]["latency_p99_ms"] = 50.0

            qr = QueryResult(
                query_type=action.action_type,
                target_service=action.target_service,
                data=f"WARNING: {action.action_type} applied to {action.target_service}. This may cause collateral damage.",
            )
            if self._state.step_count >= gt["max_steps"]:
                self._done = True
                return self._terminal_obs(query_result=qr, reward=self._compute_final_reward().total)

            return self._step_obs(query_result=qr, reward=0.08)  # wrong action type

        # ── Wrong target entirely ──
        else:
            self._temporarily_fixed.add(action.target_service)
            self._last_remediation_action = action.action_type
            self._last_remediation_target = action.target_service
            self._last_remediation_params = rem_params

            self._services[action.target_service]["status"] = "healthy"
            self._services[action.target_service]["metrics"]["error_rate_pct"] = 0.5
            self._services[action.target_service]["metrics"]["latency_p99_ms"] = 50.0

            qr = QueryResult(
                query_type=action.action_type,
                target_service=action.target_service,
                data=f"DANGER: {action.action_type} applied to {action.target_service}. This service was healthy.",
            )
            if self._state.step_count >= gt["max_steps"]:
                self._done = True
                return self._terminal_obs(query_result=qr, reward=self._compute_final_reward().total)

            return self._step_obs(query_result=qr, reward=0.02)  # wrong target

    def _handle_escalate(self, action: IncidentResponseAction) -> IncidentResponseObservation:
        """Handle escalate action — ends episode, no remediation score."""
        self._done = True
        self._last_remediation_action = "escalate"
        self._last_remediation_target = None
        self._last_remediation_params = None
        reward = self._compute_final_reward()

        qr = QueryResult(
            query_type="escalate",
            target_service="",
            data=f"Incident escalated (severity: {action.severity or 'unspecified'}).",
        )
        return self._terminal_obs(query_result=qr, reward=reward.total)

    # --- Reward Shaping ---

    def _compute_investigation_reward(self, action: IncidentResponseAction) -> float:
        """
        Positive reinforcement for productive investigation.

        Rewards the agent for:
        - Investigating the root cause service (highest reward)
        - Investigating services on the dependency path to root cause
        - Investigating degraded/down services (they're worth looking at)
        - Using appropriate parameters (depth=2, include_history, etc.)
        - First time checking a new service (exploration bonus)

        Returns 0.0 for uninformative actions, up to +0.15 for highly productive ones.
        """
        gt = self._scenario.ground_truth
        root_service = gt["root_cause_service"]
        target = action.target_service
        reward = 0.0

        # --- Proximity to root cause ---
        if target == root_service:
            # Investigating the actual root cause service
            reward += 0.10
        else:
            # Check if target is on the dependency path to root cause
            # (a direct dependent of root cause, or root cause depends on target)
            root_deps = DEPENDENCY_GRAPH.get(root_service, [])
            target_deps = DEPENDENCY_GRAPH.get(target, [])
            if root_service in target_deps:
                # target depends on root_service (upstream of root)
                reward += 0.05
            elif target in root_deps:
                # root_service depends on target (downstream of root)
                reward += 0.05

        # --- Investigating unhealthy services is productive ---
        svc_status = self._services.get(target, {}).get("status", "healthy")
        if svc_status == "down":
            reward += 0.03
        elif svc_status == "degraded":
            reward += 0.02

        # --- Exploration bonus: first time checking this service ---
        prev_targets = {
            a["target_service"] for a in self._action_history[:-1]
            if a.get("target_service")
        }
        if target not in prev_targets:
            reward += 0.02

        # --- Parameter quality bonuses ---
        if action.action_type == "check_dependencies" and action.depth == 2:
            reward += 0.02  # depth=2 traces transitive deps
        if action.action_type == "check_metrics" and action.include_history:
            reward += 0.02  # history comparison reveals what changed
        if action.action_type == "check_deployments" and action.include_changelog:
            reward += 0.02  # changelog connects code changes to errors
        if action.action_type == "check_logs" and target == root_service:
            # Checking logs of root cause with the right log level
            root_log_levels = set()
            for log in self._services.get(root_service, {}).get("recent_logs", []):
                root_log_levels.add(log.get("level"))
            if action.log_level and action.log_level in root_log_levels:
                reward += 0.02

        return min(reward, 0.20)  # bonus capped — combined with 0.5 base, max per-step is ~0.70

    # --- Helper Methods ---

    def _restore_temporary_fixes(self):
        """Re-apply original fault state for services that were wrongly remediated."""
        for svc_name in list(self._temporarily_fixed):
            if svc_name in self._original_services:
                self._services[svc_name] = deepcopy(
                    self._original_services[svc_name]
                )
        self._temporarily_fixed.clear()

    def _build_service_statuses(self) -> List[ServiceStatus]:
        """Build ServiceStatus list from current service states."""
        statuses = []
        for name in sorted(self._services.keys()):
            svc = self._services[name]
            statuses.append(
                ServiceStatus(
                    name=name,
                    status=svc["status"],
                    latency_p99_ms=svc["metrics"]["latency_p99_ms"],
                    error_rate_pct=svc["metrics"]["error_rate_pct"],
                )
            )
        return statuses

    def _compute_final_reward(self):
        """Compute final reward via verifier."""
        gt = self._scenario.ground_truth
        return compute_score(
            ground_truth=gt,
            agent_diagnosis=self._last_diagnosis,
            agent_remediation_action=self._last_remediation_action,
            agent_remediation_target=self._last_remediation_target,
            agent_remediation_params=self._last_remediation_params,
            steps_taken=self._state.step_count,
            max_steps=gt["max_steps"],
            action_history=self._action_history,
        )

    def _step_obs(
        self,
        query_result: Optional[QueryResult] = None,
        reward: float = 0.0,
    ) -> IncidentResponseObservation:
        """Build a non-terminal observation. All rewards clamped to [0, 1]."""
        gt = self._scenario.ground_truth

        # Check max steps
        if self._state.step_count >= gt["max_steps"]:
            self._done = True
            final_reward = self._compute_final_reward()
            return self._terminal_obs(query_result=query_result, reward=final_reward.total)

        if query_result is not None:
            self._last_query_result = query_result

        return IncidentResponseObservation(
            alert=None,
            service_statuses=self._build_service_statuses(),
            last_query_result=query_result,
            step_number=self._state.step_count,
            max_steps=gt["max_steps"],
            available_actions=ALL_ACTIONS,
            done=False,
            reward=max(0.0, min(1.0, reward)),
        )

    def _terminal_obs(
        self,
        query_result: Optional[QueryResult] = None,
        reward: float = 0.0,
    ) -> IncidentResponseObservation:
        """Build a terminal observation. All rewards clamped to [0, 1]."""
        gt = self._scenario.ground_truth
        return IncidentResponseObservation(
            alert=None,
            service_statuses=self._build_service_statuses(),
            last_query_result=query_result or self._last_query_result,
            step_number=self._state.step_count,
            max_steps=gt["max_steps"],
            available_actions=[],
            done=True,
            reward=max(0.0, min(1.0, reward)),
        )

    def _error_obs(self, message: str) -> IncidentResponseObservation:
        """Build an error observation."""
        return IncidentResponseObservation(
            alert=None,
            service_statuses=[],
            last_query_result=QueryResult(
                query_type="error",
                target_service="system",
                data=message,
            ),
            step_number=0,
            max_steps=0,
            available_actions=[],
            done=True,
            reward=0.0,
        )
