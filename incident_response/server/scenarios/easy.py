"""
Easy scenario: "The Obvious Crash"

payment-svc received a bad deployment (v2.4.0) that crashes on startup.
Logs directly state the problem. Agent needs minimal investigation.
"""

from typing import Any, Dict

try:
    from ..service_graph import _ts, cascade_failure
except ImportError:
    from server.service_graph import _ts, cascade_failure

from .base import Scenario


def setup_easy(services: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Inject payment-svc crash and cascade effects."""
    svc = services["payment-svc"]

    # Root cause: payment-svc is down
    svc["status"] = "down"
    svc["metrics"]["latency_p99_ms"] = 30000.0  # timeout
    svc["metrics"]["error_rate_pct"] = 100.0
    svc["metrics"]["cpu_pct"] = 5.0
    svc["metrics"]["memory_pct"] = 10.0
    svc["metrics"]["requests_per_min"] = 0.0

    # Clear evidence in logs
    svc["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "FATAL",
            "message": "NullPointerException in PaymentProcessor.processTransaction() — version v2.4.0",
        },
        {
            "timestamp": _ts(1),
            "level": "ERROR",
            "message": "Service startup failed: unhandled exception in initialization",
        },
        {
            "timestamp": _ts(2),
            "level": "ERROR",
            "message": "Health check failed: service not responding on port 8080",
        },
        {
            "timestamp": _ts(5),
            "level": "INFO",
            "message": "Deploying version v2.4.0...",
        },
        {
            "timestamp": _ts(6),
            "level": "INFO",
            "message": "Shutting down v2.3.9 for upgrade",
        },
    ]

    # Bad deployment visible
    svc["recent_deployments"] = [
        {"version": "v2.4.0", "timestamp": _ts(15), "status": "active",
         "changelog": "- Refactored PaymentProcessor.processTransaction()\n- Updated serialization format\n- Performance optimization"},
        {"version": "v2.3.9", "timestamp": _ts(1440), "status": "previous",
         "changelog": "- Bug fix: null check in payment validation\n- Updated logging format"},
    ]

    # Cascade upstream: checkout-svc becomes degraded, frontend sees 502s
    services = cascade_failure(services, "payment-svc", "down")

    # Override checkout-svc with scenario-specific symptoms
    checkout = services["checkout-svc"]
    checkout["status"] = "degraded"
    checkout["metrics"]["error_rate_pct"] = 60.0
    checkout["metrics"]["latency_p99_ms"] = 8000.0
    checkout["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "ERROR",
            "message": "upstream payment-svc connection refused",
        },
        {
            "timestamp": _ts(1),
            "level": "ERROR",
            "message": "Failed to process checkout: payment service unavailable",
        },
        {
            "timestamp": _ts(2),
            "level": "WARN",
            "message": "Circuit breaker opened for payment-svc",
        },
        {
            "timestamp": _ts(3),
            "level": "WARN",
            "message": "Retrying payment request (attempt 3/3)...",
        },
        {
            "timestamp": _ts(5),
            "level": "INFO",
            "message": "checkout-svc: request processed successfully",
        },
    ]

    # Frontend sees intermittent 502s
    fe = services["frontend"]
    fe["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "ERROR",
            "message": "502 Bad Gateway from api-gateway for /checkout endpoint",
        },
        {
            "timestamp": _ts(1),
            "level": "WARN",
            "message": "Intermittent errors on checkout flow",
        },
    ] + fe["recent_logs"][:8]

    return services


EASY_SCENARIO = Scenario(
    task_id="easy",
    name="The Obvious Crash",
    alert_text=(
        "ALERT: Checkout flow failing. Customers unable to complete purchases. "
        "Multiple 502 errors reported on frontend."
    ),
    ground_truth={
        "root_cause_service": "payment-svc",
        "root_cause_type": "bad_deployment",
        "correct_remediation": "rollback_deployment",
        "correct_target": "payment-svc",
        "correct_target_version": "v2.3.9",
        "correct_resource": None,
        "correct_restart_mode": None,
        "optimal_steps": 3,
        "max_steps": 15,
    },
    setup_fn=setup_easy,
)
