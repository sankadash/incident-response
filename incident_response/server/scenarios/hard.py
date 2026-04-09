"""
Hard scenario: "The Intermittent Poisoned Deploy"

auth-svc received a bad deployment (v1.8.0) that breaks token validation
for ~30% of requests. The service appears completely healthy by all metrics.
The errors manifest as seemingly random failures across MULTIPLE services,
making it look like a distributed issue rather than a single root cause.
"""

from typing import Any, Dict

try:
    from ..service_graph import _ts
except ImportError:
    from server.service_graph import _ts

from .base import Scenario


def setup_hard(services: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Inject subtle auth-svc failure with well-disguised symptoms."""

    # Root cause: auth-svc appears COMPLETELY HEALTHY by every surface metric
    auth = services["auth-svc"]
    auth["status"] = "healthy"
    auth["metrics"]["latency_p99_ms"] = 45.0  # Perfectly normal
    auth["metrics"]["error_rate_pct"] = 2.0  # Barely elevated — noise level
    auth["metrics"]["cpu_pct"] = 28.0  # Normal
    auth["metrics"]["memory_pct"] = 48.0  # Normal
    auth["metrics"]["requests_per_min"] = 1250.0  # Normal

    # Logs: the key evidence is deeply buried among noise, and is only a DEBUG line
    auth["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "INFO",
            "message": "auth-svc: token validation completed (200 OK)",
        },
        {
            "timestamp": _ts(1),
            "level": "INFO",
            "message": "auth-svc: session refresh completed successfully",
        },
        {
            "timestamp": _ts(2),
            "level": "INFO",
            "message": "auth-svc: new user session created",
        },
        {
            "timestamp": _ts(3),
            "level": "INFO",
            "message": "auth-svc: token validation completed (200 OK)",
        },
        {
            "timestamp": _ts(4),
            "level": "DEBUG",
            "message": "legacy token format detected — routing through v1.8.0 compatibility path",
        },
        {
            "timestamp": _ts(5),
            "level": "INFO",
            "message": "auth-svc: health check passed — all endpoints responding",
        },
        {
            "timestamp": _ts(6),
            "level": "INFO",
            "message": "auth-svc: token validation completed (200 OK)",
        },
        {
            "timestamp": _ts(7),
            "level": "DEBUG",
            "message": "v1.8.0 path: token signature mismatch on re-validation (non-critical)",
        },
        {
            "timestamp": _ts(8),
            "level": "INFO",
            "message": "auth-svc: request processed successfully",
        },
        {
            "timestamp": _ts(9),
            "level": "INFO",
            "message": "auth-svc: token validation completed (200 OK)",
        },
    ]

    # Deployment: v1.8.0 was 45 min ago, but there's ALSO a recent config change
    # to create more ambiguity
    auth["recent_deployments"] = [
        {"version": "v1.8.0", "timestamp": _ts(45), "status": "active",
         "changelog": "- Rewrote TokenValidator request handling\n- New validation logic in validateToken()\n- Updated error handling"},
        {"version": "v1.7.3", "timestamp": _ts(4320), "status": "previous",
         "changelog": "- Stable release\n- Minor logging improvements"},
    ]

    # --- MISDIRECTION: Make OTHER services look much more suspicious ---

    # checkout-svc: appears to have its OWN problems (memory leak pattern)
    checkout = services["checkout-svc"]
    checkout["status"] = "degraded"
    checkout["metrics"]["error_rate_pct"] = 22.0
    checkout["metrics"]["latency_p99_ms"] = 2500.0
    checkout["metrics"]["cpu_pct"] = 72.0
    checkout["metrics"]["memory_pct"] = 89.0  # High memory — looks like a leak
    checkout["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "ERROR",
            "message": "order processing failed: unexpected 401 response from upstream",
        },
        {
            "timestamp": _ts(1),
            "level": "WARN",
            "message": "memory usage critical: 89% of heap — potential memory leak detected",
        },
        {
            "timestamp": _ts(2),
            "level": "ERROR",
            "message": "GC pause exceeded 500ms — long stop-the-world event",
        },
        {
            "timestamp": _ts(3),
            "level": "WARN",
            "message": "retry failed: upstream returned 401 for pre-authenticated request",
        },
        {
            "timestamp": _ts(4),
            "level": "INFO",
            "message": "checkout-svc: order processed successfully",
        },
        {
            "timestamp": _ts(5),
            "level": "WARN",
            "message": "object pool growing: 15000 active objects (threshold: 10000)",
        },
        {
            "timestamp": _ts(6),
            "level": "INFO",
            "message": "checkout-svc: request processed successfully",
        },
    ]
    # checkout-svc had a recent deploy too — another red herring
    checkout["recent_deployments"] = [
        {"version": "v4.1.2", "timestamp": _ts(30), "status": "active",
         "changelog": "- Updated cart display logic\n- Minor UI fix\n- No backend changes"},
        {"version": "v4.1.1", "timestamp": _ts(1440), "status": "previous",
         "changelog": "- Stable release\n- Performance improvements"},
    ]

    # api-gateway: shows mixed errors, none pointing clearly at auth
    gw = services["api-gateway"]
    gw["metrics"]["error_rate_pct"] = 15.0
    gw["metrics"]["latency_p99_ms"] = 350.0
    gw["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "ERROR",
            "message": "mixed HTTP errors: 401 (35%), 503 (10%), 200 (55%) on downstream calls",
        },
        {
            "timestamp": _ts(1),
            "level": "WARN",
            "message": "rate limiter triggered for /checkout endpoint — too many retries",
        },
        {
            "timestamp": _ts(2),
            "level": "INFO",
            "message": "api-gateway: request routed successfully",
        },
        {
            "timestamp": _ts(3),
            "level": "WARN",
            "message": "intermittent downstream failures — no single source identified",
        },
        {
            "timestamp": _ts(4),
            "level": "INFO",
            "message": "api-gateway: request routed successfully",
        },
        {
            "timestamp": _ts(5),
            "level": "WARN",
            "message": "backend health check flapping for checkout-svc",
        },
        {
            "timestamp": _ts(6),
            "level": "INFO",
            "message": "api-gateway: request processed successfully",
        },
    ]

    # inventory-svc: also shows auth-related errors but mixed with other noise
    inv = services["inventory-svc"]
    inv["metrics"]["error_rate_pct"] = 12.0
    inv["metrics"]["latency_p99_ms"] = 200.0
    inv["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "WARN",
            "message": "received 401 on internal API call — refreshing service token",
        },
        {
            "timestamp": _ts(1),
            "level": "INFO",
            "message": "inventory-svc: stock level updated successfully",
        },
        {
            "timestamp": _ts(2),
            "level": "WARN",
            "message": "cache miss rate elevated: 30% (threshold: 15%)",
        },
        {
            "timestamp": _ts(3),
            "level": "INFO",
            "message": "inventory-svc: request processed successfully",
        },
        {
            "timestamp": _ts(5),
            "level": "INFO",
            "message": "inventory-svc: request processed successfully",
        },
    ] + inv["recent_logs"][:5]

    # frontend: users see various errors — looks like multiple issues
    fe = services["frontend"]
    fe["metrics"]["error_rate_pct"] = 18.0
    fe["metrics"]["latency_p99_ms"] = 400.0
    fe["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "ERROR",
            "message": "user session expired unexpectedly — redirecting to login",
        },
        {
            "timestamp": _ts(1),
            "level": "WARN",
            "message": "checkout page returned error — showing fallback UI",
        },
        {
            "timestamp": _ts(2),
            "level": "WARN",
            "message": "product page slow to load — possible backend issue",
        },
        {
            "timestamp": _ts(3),
            "level": "ERROR",
            "message": "user reports: 'keeps asking me to log in again'",
        },
        {
            "timestamp": _ts(4),
            "level": "INFO",
            "message": "frontend: page rendered successfully",
        },
        {
            "timestamp": _ts(5),
            "level": "WARN",
            "message": "mixed errors across checkout and browse flows — unclear pattern",
        },
    ] + fe["recent_logs"][:4]

    # payment-svc: slight elevation to add noise
    pay = services["payment-svc"]
    pay["metrics"]["error_rate_pct"] = 5.0
    pay["recent_logs"] = [
        {
            "timestamp": _ts(0),
            "level": "WARN",
            "message": "payment request rejected: upstream auth token invalid",
        },
        {
            "timestamp": _ts(2),
            "level": "INFO",
            "message": "payment-svc: transaction processed successfully",
        },
        {
            "timestamp": _ts(4),
            "level": "INFO",
            "message": "payment-svc: request processed successfully",
        },
    ] + pay["recent_logs"][:7]

    return services


HARD_SCENARIO = Scenario(
    task_id="hard",
    name="The Intermittent Poisoned Deploy",
    alert_text=(
        "ALERT: Multiple services experiencing intermittent errors. Checkout "
        "degraded with high memory usage. Users reporting random logouts "
        "and failed transactions. No clear single point of failure identified."
    ),
    ground_truth={
        "root_cause_service": "auth-svc",
        "root_cause_type": "bad_deployment",
        "correct_remediation": "rollback_deployment",
        "correct_target": "auth-svc",
        "correct_target_version": "v1.7.3",
        "correct_resource": None,
        "correct_restart_mode": None,
        "optimal_steps": 7,
        "max_steps": 25,
    },
    setup_fn=setup_hard,
)
