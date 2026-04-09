"""
Medium scenario: "The Cascading Slowdown"

Database has hit connection pool exhaustion. Surface symptoms strongly point at
checkout-svc (which has the WORST metrics and most alarming logs). inventory-svc
also looks bad. The database itself appears only mildly degraded in the overview
— you have to actually check its logs/metrics to see the pool exhaustion.
"""

from typing import Any, Dict

try:
    from ..service_graph import _ts
except ImportError:
    from server.service_graph import _ts

from .base import Scenario


def setup_medium(services: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Inject database exhaustion and cascading effects."""

    # Root cause: database — but make it look only MILDLY degraded in the overview
    # The real evidence (pool exhaustion) is only visible in logs/metrics
    db = services["database"]
    db["status"] = "healthy"  # Appears healthy in overview!
    db["metrics"]["latency_p99_ms"] = 800.0  # Elevated but not alarming
    db["metrics"]["error_rate_pct"] = 3.0  # Low — doesn't stand out
    db["metrics"]["cpu_pct"] = 95.0  # High but only visible if you check_metrics
    db["metrics"]["memory_pct"] = 88.0
    db["metrics"]["requests_per_min"] = 300.0
    db["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "WARN",
            "message": "connection pool utilization at 100% — all connections in use",
        },
        {
            "timestamp": _ts(1),
            "level": "ERROR",
            "message": "too many connections — pool exhausted (max=100, active=100)",
        },
        {
            "timestamp": _ts(2),
            "level": "ERROR",
            "message": "connection request timed out after 5000ms, no available connections",
        },
        {
            "timestamp": _ts(3),
            "level": "WARN",
            "message": "slow query detected: SELECT * FROM inventory WHERE ... (4200ms)",
        },
        {
            "timestamp": _ts(5),
            "level": "INFO",
            "message": "connection pool stats: active=100, idle=0, waiting=47",
        },
        {
            "timestamp": _ts(8),
            "level": "INFO",
            "message": "database: request processed successfully",
        },
        {
            "timestamp": _ts(9),
            "level": "INFO",
            "message": "database: health check passed",
        },
        {
            "timestamp": _ts(10),
            "level": "INFO",
            "message": "database: request processed successfully",
        },
    ]

    # checkout-svc: THE RED HERRING — worst visible metrics, most alarming logs
    # Agent that stops here will misdiagnose
    checkout = services["checkout-svc"]
    checkout["status"] = "degraded"
    checkout["metrics"]["latency_p99_ms"] = 12000.0  # Worst latency
    checkout["metrics"]["error_rate_pct"] = 55.0  # Worst error rate
    checkout["metrics"]["cpu_pct"] = 85.0  # High CPU
    checkout["metrics"]["memory_pct"] = 78.0
    checkout["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "ERROR",
            "message": "CRITICAL: checkout processing completely stalled — all requests timing out",
        },
        {
            "timestamp": _ts(1),
            "level": "ERROR",
            "message": "thread pool exhausted: 200/200 threads blocked on downstream calls",
        },
        {
            "timestamp": _ts(2),
            "level": "ERROR",
            "message": "timeout waiting for inventory-svc response (12000ms exceeded)",
        },
        {
            "timestamp": _ts(3),
            "level": "WARN",
            "message": "circuit breaker OPEN for inventory-svc — too many consecutive failures",
        },
        {
            "timestamp": _ts(4),
            "level": "ERROR",
            "message": "customer order failed: unable to verify inventory availability",
        },
        {
            "timestamp": _ts(5),
            "level": "WARN",
            "message": "memory pressure: object heap nearing limit due to queued requests",
        },
        {
            "timestamp": _ts(6),
            "level": "WARN",
            "message": "retrying inventory-svc request (attempt 3/3) — still failing",
        },
        {
            "timestamp": _ts(8),
            "level": "INFO",
            "message": "checkout-svc: request processed successfully",
        },
    ]
    # Recent deployment on checkout-svc to further mislead
    checkout["recent_deployments"] = [
        {"version": "v3.2.0", "timestamp": _ts(60), "status": "active"},
        {"version": "v3.1.8", "timestamp": _ts(2880), "status": "previous"},
    ]

    # inventory-svc: also looks very bad — secondary red herring
    inv = services["inventory-svc"]
    inv["status"] = "degraded"
    inv["metrics"]["latency_p99_ms"] = 8000.0
    inv["metrics"]["error_rate_pct"] = 40.0
    inv["metrics"]["cpu_pct"] = 70.0
    inv["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "ERROR",
            "message": "SEVERE: inventory queries failing at 40% rate — service degraded",
        },
        {
            "timestamp": _ts(1),
            "level": "ERROR",
            "message": "query execution failed: downstream dependency timeout",
        },
        {
            "timestamp": _ts(2),
            "level": "WARN",
            "message": "falling back to stale cache for inventory lookups — data may be outdated",
        },
        {
            "timestamp": _ts(3),
            "level": "WARN",
            "message": "request queue building up: 47 pending requests",
        },
        {
            "timestamp": _ts(5),
            "level": "ERROR",
            "message": "connection timeout to downstream dependency — query failed after 5000ms",
        },
        {
            "timestamp": _ts(8),
            "level": "INFO",
            "message": "inventory-svc: request processed successfully",
        },
    ]

    # api-gateway: elevated but not terrible
    gw = services["api-gateway"]
    gw["metrics"]["latency_p99_ms"] = 4000.0
    gw["metrics"]["error_rate_pct"] = 18.0
    gw["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "ERROR",
            "message": "upstream checkout-svc returning 503 — marking as unavailable",
        },
        {
            "timestamp": _ts(1),
            "level": "WARN",
            "message": "elevated latency on /checkout and /inventory endpoints",
        },
        {
            "timestamp": _ts(2),
            "level": "WARN",
            "message": "upstream timeout: checkout-svc (12000ms)",
        },
        {
            "timestamp": _ts(5),
            "level": "INFO",
            "message": "api-gateway: request processed successfully",
        },
    ] + gw["recent_logs"][:6]

    # frontend: user-facing impact
    fe = services["frontend"]
    fe["metrics"]["latency_p99_ms"] = 3000.0
    fe["metrics"]["error_rate_pct"] = 12.0
    fe["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "ERROR",
            "message": "checkout page failing to load — users seeing error screen",
        },
        {
            "timestamp": _ts(1),
            "level": "WARN",
            "message": "slow page load detected: product pages (3200ms)",
        },
        {
            "timestamp": _ts(2),
            "level": "WARN",
            "message": "sporadic timeout errors on checkout flow",
        },
    ] + fe["recent_logs"][:7]

    return services


MEDIUM_SCENARIO = Scenario(
    task_id="medium",
    name="The Cascading Slowdown",
    alert_text=(
        "ALERT: Checkout system critically degraded. 55% of checkout requests failing. "
        "Customers unable to complete purchases. Inventory lookups also impacted."
    ),
    ground_truth={
        "root_cause_service": "database",
        "root_cause_type": "resource_exhaustion",
        "correct_remediation": "scale_up",
        "correct_target": "database",
        "correct_target_version": None,
        "correct_resource": "connections",
        "correct_restart_mode": None,
        "optimal_steps": 5,
        "max_steps": 20,
    },
    setup_fn=setup_medium,
)
