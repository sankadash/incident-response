"""
Service graph topology and cascade failure logic.

Defines the 7-microservice system and how failures propagate upstream
through the dependency graph via BFS.
"""

from collections import deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

SERVICE_NAMES: List[str] = [
    "frontend",
    "api-gateway",
    "auth-svc",
    "checkout-svc",
    "inventory-svc",
    "payment-svc",
    "database",
]

# service -> list of services it depends on (downstream)
DEPENDENCY_GRAPH: Dict[str, List[str]] = {
    "frontend": ["api-gateway"],
    "api-gateway": ["auth-svc", "checkout-svc", "inventory-svc"],
    "auth-svc": [],
    "checkout-svc": ["payment-svc"],
    "inventory-svc": ["database"],
    "payment-svc": [],
    "database": [],
}


def build_reverse_graph() -> Dict[str, List[str]]:
    """Invert the dependency graph: service -> list of upstream dependents."""
    reverse: Dict[str, List[str]] = {name: [] for name in SERVICE_NAMES}
    for service, deps in DEPENDENCY_GRAPH.items():
        for dep in deps:
            reverse[dep].append(service)
    return reverse


# Pre-compute the reverse graph
REVERSE_GRAPH: Dict[str, List[str]] = build_reverse_graph()

# Base timestamp for all simulated events
_BASE_TIME = datetime(2025, 4, 1, 14, 0, 0, tzinfo=timezone.utc)


def _ts(minutes_ago: int = 0) -> str:
    """Generate an ISO timestamp relative to base time."""
    return (
        (_BASE_TIME - timedelta(minutes=minutes_ago))
        .isoformat()
        .replace("+00:00", "Z")
    )


def build_default_service_states() -> Dict[str, Dict[str, Any]]:
    """Build healthy default state for all 7 services."""
    defaults: Dict[str, Dict[str, Any]] = {}
    for name in SERVICE_NAMES:
        defaults[name] = {
            "name": name,
            "status": "healthy",
            "metrics": {
                "latency_p99_ms": 45.0,
                "error_rate_pct": 0.1,
                "cpu_pct": 30.0,
                "memory_pct": 50.0,
                "requests_per_min": 1200.0,
            },
            "recent_logs": [
                {"timestamp": _ts(0), "level": "INFO", "message": f"{name}: request processed successfully"},
                {"timestamp": _ts(1), "level": "DEBUG", "message": f"{name}: cache hit ratio 98.5%"},
                {"timestamp": _ts(2), "level": "INFO", "message": f"{name}: request processed successfully"},
                {"timestamp": _ts(3), "level": "DEBUG", "message": f"{name}: connection pool stats: active=12, idle=88"},
                {"timestamp": _ts(4), "level": "INFO", "message": f"{name}: health check passed"},
                {"timestamp": _ts(5), "level": "WARN", "message": f"{name}: minor GC pause 15ms (below threshold)"},
                {"timestamp": _ts(6), "level": "INFO", "message": f"{name}: request processed successfully"},
                {"timestamp": _ts(7), "level": "DEBUG", "message": f"{name}: TLS session reused"},
                {"timestamp": _ts(8), "level": "INFO", "message": f"{name}: session refresh completed"},
                {"timestamp": _ts(9), "level": "INFO", "message": f"{name}: request processed successfully"},
                {"timestamp": _ts(10), "level": "DEBUG", "message": f"{name}: metrics exported successfully"},
                {"timestamp": _ts(11), "level": "INFO", "message": f"{name}: background job completed"},
                {"timestamp": _ts(12), "level": "DEBUG", "message": f"{name}: config version check passed"},
                {"timestamp": _ts(13), "level": "INFO", "message": f"{name}: request processed successfully"},
                {"timestamp": _ts(14), "level": "INFO", "message": f"{name}: health check passed"},
            ],
            "dependencies": DEPENDENCY_GRAPH[name],
            "recent_deployments": [
                {
                    "version": "v1.0.0",
                    "timestamp": _ts(1440),
                    "status": "active",
                    "changelog": "- Initial stable release\n- No recent changes",
                }
            ],
        }
    return defaults


def cascade_failure(
    services: Dict[str, Dict[str, Any]],
    root_service: str,
    root_status: str = "down",
) -> Dict[str, Dict[str, Any]]:
    """
    Propagate failure effects upstream through the reverse dependency graph via BFS.

    The root_service is already configured (status, logs, metrics) by the scenario.
    This function propagates degradation to upstream dependents:
    - Level 1 dependents: become 'degraded' with spiked latency/error rates
    - Level 2+ dependents: mildly elevated latency, remain 'healthy'
    """
    services = deepcopy(services)
    visited = {root_service}
    queue: deque = deque()

    # Seed BFS with direct dependents of the root cause
    for dependent in REVERSE_GRAPH.get(root_service, []):
        if dependent not in visited:
            queue.append((dependent, 1))
            visited.add(dependent)

    while queue:
        svc_name, level = queue.popleft()
        svc = services[svc_name]

        if level == 1:
            # Direct dependents: degraded
            svc["status"] = "degraded"
            svc["metrics"]["latency_p99_ms"] = 6000.0 + (level * 1000)
            svc["metrics"]["error_rate_pct"] = 40.0 + (level * 10)
            svc["metrics"]["cpu_pct"] = 60.0
            # Inject cascade symptom logs
            svc["recent_logs"] = [
                {
                    "timestamp": _ts(0),
                    "level": "ERROR",
                    "message": f"upstream {root_service} connection refused",
                },
                {
                    "timestamp": _ts(1),
                    "level": "WARN",
                    "message": f"timeout waiting for {root_service} response",
                },
                {
                    "timestamp": _ts(2),
                    "level": "ERROR",
                    "message": f"circuit breaker opened for {root_service}",
                },
            ] + svc["recent_logs"][:7]
        else:
            # Level 2+: mildly elevated, still healthy
            svc["metrics"]["latency_p99_ms"] = min(
                svc["metrics"]["latency_p99_ms"] + 200.0 * level, 3000.0
            )
            svc["metrics"]["error_rate_pct"] = min(
                svc["metrics"]["error_rate_pct"] + 5.0, 15.0
            )
            svc["recent_logs"] = [
                {
                    "timestamp": _ts(0),
                    "level": "WARN",
                    "message": f"elevated latency detected from downstream services",
                },
            ] + svc["recent_logs"][:9]

        # Continue BFS upstream
        for dependent in REVERSE_GRAPH.get(svc_name, []):
            if dependent not in visited:
                queue.append((dependent, level + 1))
                visited.add(dependent)

    return services
