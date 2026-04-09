# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""
Data models for the Incident Response Environment.

An SRE incident triage environment where an AI agent investigates
production alerts, diagnoses root causes, and takes remediation actions.
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from openenv.core.env_server.types import Action, Observation


class ServiceStatus(BaseModel):
    """Summary status of a single microservice."""

    name: str = Field(..., description="Service name")
    status: str = Field(..., description="'healthy', 'degraded', or 'down'")
    latency_p99_ms: float = Field(..., description="p99 latency in milliseconds")
    error_rate_pct: float = Field(..., description="Error rate as a percentage")


class QueryResult(BaseModel):
    """Result of an investigation action."""

    query_type: str = Field(..., description="The action_type that produced this result")
    target_service: str = Field(..., description="The service that was queried")
    data: Union[Dict[str, Any], List[Any], str] = Field(
        ..., description="Log lines, metric dict, dependency list, etc."
    )


class Reward(BaseModel):
    """Deterministic 4-component reward breakdown."""

    total: float = Field(..., description="Overall score 0.0-1.0")
    diagnosis_score: float = Field(..., description="0.0, 0.5, or 1.0")
    remediation_score: float = Field(..., description="0.0, 0.3, or 1.0")
    efficiency_score: float = Field(..., description="0.0-1.0")
    safety_score: float = Field(..., description="0.0-1.0")


class IncidentResponseAction(Action):
    """Action for the Incident Response environment.

    Investigation: check_logs, check_metrics, check_dependencies, check_deployments
    Diagnosis:     diagnose
    Remediation:   restart_service, rollback_deployment, scale_up, escalate
    """

    action_type: str = Field(..., description="One of the 9 valid action types")
    target_service: Optional[str] = Field(
        default=None, description="Target service (required for all except escalate)"
    )
    diagnosis: Optional[str] = Field(
        default=None,
        description="Diagnosis string in format 'service_name:cause_type' (required for diagnose action)",
    )

    # --- Investigation parameters ---
    log_level: Optional[str] = Field(
        default=None,
        description="Log level filter for check_logs: ALL, FATAL, ERROR, WARN, INFO, DEBUG",
    )
    keyword: Optional[str] = Field(
        default=None,
        description="Keyword substring filter for check_logs",
    )
    tail: Optional[int] = Field(
        default=None,
        description="Number of log entries to return for check_logs (default 10, max 50)",
    )
    metric_name: Optional[str] = Field(
        default=None,
        description="Specific metric for check_metrics: latency, error_rate, cpu, memory, rpm, or all",
    )
    include_history: Optional[bool] = Field(
        default=None,
        description="Include baseline comparison for check_metrics",
    )
    depth: Optional[int] = Field(
        default=None,
        description="Dependency traversal depth for check_dependencies: 1 (direct) or 2 (transitive)",
    )
    include_metrics: Optional[bool] = Field(
        default=None,
        description="Include health metrics of dependencies for check_dependencies",
    )
    include_changelog: Optional[bool] = Field(
        default=None,
        description="Include changelog for check_deployments",
    )

    # --- Remediation parameters ---
    target_version: Optional[str] = Field(
        default=None,
        description="Version to roll back to for rollback_deployment (REQUIRED)",
    )
    resource: Optional[str] = Field(
        default=None,
        description="Resource to scale for scale_up: cpu, memory, connections, replicas (REQUIRED)",
    )
    mode: Optional[str] = Field(
        default=None,
        description="Restart mode for restart_service: graceful or force (REQUIRED)",
    )

    # --- Escalate parameters ---
    severity: Optional[str] = Field(
        default=None,
        description="Escalation severity: low, medium, high, critical",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Brief reason for escalation",
    )


class IncidentResponseObservation(Observation):
    """Observation from the Incident Response environment."""

    alert: Optional[str] = Field(
        default=None, description="Alert text, present only on first observation after reset()"
    )
    service_statuses: List[ServiceStatus] = Field(
        default_factory=list, description="Current status of all services"
    )
    last_query_result: Optional[QueryResult] = Field(
        default=None, description="Result of the last investigation action"
    )
    step_number: int = Field(default=0, description="Current step number")
    max_steps: int = Field(default=15, description="Maximum steps for this episode")
    available_actions: List[str] = Field(
        default_factory=list, description="List of valid action types"
    )
