"""
Synthetic data templates for procedural scenario generation.

All raw material the generator draws from: log message templates,
metric profiles, alert fragments, service context, and difficulty config.
"""

from typing import Any, Dict, List, Tuple

# =============================================================================
# Cause-to-remediation mapping
# =============================================================================

CAUSE_TO_REMEDIATION: Dict[str, str] = {
    "bad_deployment": "rollback_deployment",
    "resource_exhaustion": "scale_up",
    "traffic_spike": "scale_up",
    "dependency_failure": "restart_service",
    "configuration_error": "restart_service",
}

# =============================================================================
# Difficulty configuration
# =============================================================================

DIFFICULTY_CONFIG: Dict[str, Dict[str, Any]] = {
    "easy": {
        "eligible_services": [
            "payment-svc", "auth-svc", "checkout-svc", "inventory-svc", "database"
        ],
        "eligible_causes": ["bad_deployment", "resource_exhaustion"],
        "root_status_options": ["down", "degraded"],
        "root_log_levels": ["FATAL", "ERROR"],
        "root_log_count": (4, 6),
        "noise_log_count": (5, 8),
        "cascade_names_root": True,
        "red_herring_count": 0,
        "upstream_metric_multiplier": 0.7,
        "optimal_steps": 3,
        "max_steps": 15,
    },
    "medium": {
        "eligible_services": [
            "frontend", "api-gateway", "auth-svc", "checkout-svc",
            "inventory-svc", "payment-svc", "database",
        ],
        "eligible_causes": [
            "bad_deployment", "resource_exhaustion", "dependency_failure",
            "configuration_error", "traffic_spike",
        ],
        "root_status_options": ["healthy", "degraded"],
        "root_log_levels": ["WARN", "ERROR"],
        "root_log_count": (4, 6),
        "noise_log_count": (6, 10),
        "cascade_names_root": True,
        "red_herring_count": (1, 2),
        "upstream_metric_multiplier": 1.5,
        "optimal_steps": 5,
        "max_steps": 20,
    },
    "hard": {
        "eligible_services": [
            "frontend", "api-gateway", "auth-svc", "checkout-svc",
            "inventory-svc", "payment-svc", "database",
        ],
        "eligible_causes": [
            "bad_deployment", "resource_exhaustion", "dependency_failure",
            "configuration_error", "traffic_spike",
        ],
        "root_status_options": ["healthy"],
        "root_log_levels": ["DEBUG"],
        "root_log_count": (1, 2),
        "noise_log_count": (12, 15),
        "cascade_names_root": False,
        "red_herring_count": (2, 3),
        "upstream_metric_multiplier": 3.0,
        "optimal_steps": 7,
        "max_steps": 25,
    },
}

# =============================================================================
# Metric profiles: (cause_type, difficulty) -> metric ranges
# Each tuple is (min, max) for the RNG to pick from
# =============================================================================

METRIC_PROFILES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "bad_deployment": {
        "easy": {
            "latency_p99_ms": (20000, 30000),
            "error_rate_pct": (85, 100),
            "cpu_pct": (3, 10),
            "memory_pct": (8, 15),
            "requests_per_min": (0, 50),
        },
        "medium": {
            "latency_p99_ms": (500, 2000),
            "error_rate_pct": (8, 20),
            "cpu_pct": (40, 65),
            "memory_pct": (55, 70),
            "requests_per_min": (600, 900),
        },
        "hard": {
            "latency_p99_ms": (40, 80),
            "error_rate_pct": (1, 5),
            "cpu_pct": (25, 40),
            "memory_pct": (45, 55),
            "requests_per_min": (1000, 1300),
        },
    },
    "resource_exhaustion": {
        "easy": {
            "latency_p99_ms": (5000, 15000),
            "error_rate_pct": (60, 90),
            "cpu_pct": (90, 99),
            "memory_pct": (85, 98),
            "requests_per_min": (100, 400),
        },
        "medium": {
            "latency_p99_ms": (500, 1500),
            "error_rate_pct": (3, 10),
            "cpu_pct": (88, 96),
            "memory_pct": (80, 92),
            "requests_per_min": (200, 500),
        },
        "hard": {
            "latency_p99_ms": (60, 150),
            "error_rate_pct": (1, 4),
            "cpu_pct": (70, 85),
            "memory_pct": (65, 80),
            "requests_per_min": (900, 1200),
        },
    },
    "dependency_failure": {
        "easy": {
            "latency_p99_ms": (15000, 30000),
            "error_rate_pct": (70, 100),
            "cpu_pct": (5, 15),
            "memory_pct": (40, 55),
            "requests_per_min": (50, 200),
        },
        "medium": {
            "latency_p99_ms": (800, 3000),
            "error_rate_pct": (10, 25),
            "cpu_pct": (30, 50),
            "memory_pct": (50, 65),
            "requests_per_min": (400, 800),
        },
        "hard": {
            "latency_p99_ms": (50, 120),
            "error_rate_pct": (2, 6),
            "cpu_pct": (25, 40),
            "memory_pct": (45, 60),
            "requests_per_min": (900, 1200),
        },
    },
    "configuration_error": {
        "easy": {
            "latency_p99_ms": (10000, 25000),
            "error_rate_pct": (50, 85),
            "cpu_pct": (10, 30),
            "memory_pct": (40, 60),
            "requests_per_min": (100, 500),
        },
        "medium": {
            "latency_p99_ms": (300, 1500),
            "error_rate_pct": (5, 15),
            "cpu_pct": (35, 55),
            "memory_pct": (50, 65),
            "requests_per_min": (500, 900),
        },
        "hard": {
            "latency_p99_ms": (40, 90),
            "error_rate_pct": (1, 4),
            "cpu_pct": (28, 42),
            "memory_pct": (48, 58),
            "requests_per_min": (1000, 1250),
        },
    },
    "traffic_spike": {
        "easy": {
            "latency_p99_ms": (8000, 20000),
            "error_rate_pct": (40, 75),
            "cpu_pct": (92, 99),
            "memory_pct": (80, 95),
            "requests_per_min": (5000, 15000),
        },
        "medium": {
            "latency_p99_ms": (500, 2000),
            "error_rate_pct": (8, 20),
            "cpu_pct": (85, 95),
            "memory_pct": (75, 88),
            "requests_per_min": (3000, 8000),
        },
        "hard": {
            "latency_p99_ms": (60, 150),
            "error_rate_pct": (2, 6),
            "cpu_pct": (65, 80),
            "memory_pct": (60, 75),
            "requests_per_min": (2000, 5000),
        },
    },
}

# =============================================================================
# Service-specific context for parameterized log messages
# =============================================================================

SERVICE_CONTEXT: Dict[str, Dict[str, List[str]]] = {
    "frontend": {
        "components": ["PageRenderer", "SessionHandler", "AssetLoader", "RouteManager"],
        "methods": ["render", "loadPage", "handleSession", "resolveRoute"],
        "operations": ["page render", "asset loading", "session management", "routing"],
    },
    "api-gateway": {
        "components": ["RequestRouter", "RateLimiter", "AuthProxy", "LoadBalancer"],
        "methods": ["routeRequest", "checkRateLimit", "proxyAuth", "selectBackend"],
        "operations": ["request routing", "rate limiting", "auth proxying", "load balancing"],
    },
    "auth-svc": {
        "components": ["TokenValidator", "SessionManager", "OAuthHandler", "PermissionChecker"],
        "methods": ["validateToken", "refreshSession", "handleOAuth", "checkPermission"],
        "operations": ["token validation", "session refresh", "OAuth flow", "permission check"],
    },
    "checkout-svc": {
        "components": ["OrderProcessor", "CartManager", "PaymentBridge", "InventoryChecker"],
        "methods": ["processOrder", "updateCart", "submitPayment", "verifyInventory"],
        "operations": ["order processing", "cart update", "payment submission", "inventory verification"],
    },
    "inventory-svc": {
        "components": ["StockManager", "WarehouseSync", "ReservationHandler", "CacheLayer"],
        "methods": ["checkStock", "syncWarehouse", "reserveItem", "refreshCache"],
        "operations": ["stock check", "warehouse sync", "item reservation", "cache refresh"],
    },
    "payment-svc": {
        "components": ["PaymentProcessor", "TransactionManager", "RefundHandler", "FraudDetector"],
        "methods": ["processTransaction", "authorizePayment", "handleRefund", "checkFraud"],
        "operations": ["payment processing", "transaction authorization", "refund handling", "fraud check"],
    },
    "database": {
        "components": ["ConnectionPool", "QueryExecutor", "ReplicationManager", "IndexOptimizer"],
        "methods": ["getConnection", "executeQuery", "replicateWrite", "optimizeIndex"],
        "operations": ["connection pooling", "query execution", "replication", "index optimization"],
    },
}

# =============================================================================
# Root cause log templates per (cause_type, log_level)
# Parameterized with: {component}, {method}, {version}, {prev_version},
#   {service}, {dep}, {pct}, {count}, {ms}, {port}
# =============================================================================

ROOT_CAUSE_LOGS: Dict[str, Dict[str, List[str]]] = {
    "bad_deployment": {
        "FATAL": [
            "NullPointerException in {component}.{method}() — version {version}",
            "SIGSEGV: segfault in {component} binary [{version}]",
            "Unhandled panic in {component}: index out of bounds — {version}",
            "Fatal: schema migration failed in {version} — incompatible column type",
            "OutOfMemoryError during {component}.{method}() startup — {version}",
            "FATAL: {component} initialization failed — missing dependency in {version}",
            "Unrecoverable error: {method}() returned null after {version} upgrade",
            "FATAL: binary crash on startup — core dump generated [{version}]",
        ],
        "ERROR": [
            "Service startup failed: unhandled exception during initialization",
            "Health check failed: process exited with code 1",
            "Failed to bind port {port}: address already in use after deploy",
            "Error loading configuration: {version} config schema incompatible",
            "{component} threw uncaught exception in request handler",
            "Deployment {version} failed readiness probe after 30s",
            "Error: {method}() contract violation — expected non-null return",
            "Service unhealthy: 5 consecutive failed health checks since {version}",
        ],
        "WARN": [
            "Increased error rate detected since deployment {version}",
            "{component}: intermittent failures in {method}() — investigating",
            "Rollback candidate: {version} showing elevated errors vs {prev_version}",
            "Deprecation warning: {method}() using legacy code path in {version}",
            "Request latency p99 elevated since {version} deployment",
            "Canary analysis: {version} error rate {pct}% above baseline",
        ],
        "DEBUG": [
            "{version} path: signature mismatch on re-validation (non-critical)",
            "legacy format detected — routing through {version} compatibility path",
            "{component}: fallback decoder triggered for {pct}% of requests [{version}]",
            "trace: {method}() took alternate branch in {version} — result differs",
            "{version} compatibility: token format validation using new parser",
            "debug: {component} request processing divergence between {version} and {prev_version}",
            "{method}() intermittent null return on {version} code path — retry succeeded",
            "v{version} path: deserialization mismatch for {pct}% of payloads (non-fatal)",
        ],
        "INFO": [
            "Deploying version {version}...",
            "Shutting down {prev_version} for upgrade",
            "{service}: deployment {version} initiated by CI/CD pipeline",
            "Rolling update: {version} replacing {prev_version}",
        ],
    },
    "resource_exhaustion": {
        "FATAL": [
            "OutOfMemoryError: Java heap space — unable to allocate {count} bytes",
            "FATAL: maximum connections reached — cannot accept new requests",
            "OOM killer invoked: process {service} using {pct}% of available memory",
            "FATAL: thread pool exhausted — {count}/{count} threads blocked",
        ],
        "ERROR": [
            "too many connections — pool exhausted (max={count}, active={count})",
            "connection request timed out after {ms}ms, no available connections",
            "memory allocation failed: heap at {pct}% capacity",
            "disk space critically low: {pct}% used on /data volume",
            "{component} pool saturated: {count} waiting requests",
            "CPU throttling detected: process limited to {pct}% of requested CPU",
            "Error: file descriptor limit reached ({count}/{count})",
            "Failed to spawn worker thread: resource temporarily unavailable",
        ],
        "WARN": [
            "connection pool utilization at {pct}% — approaching limit",
            "slow query detected: {method}() took {ms}ms (threshold: 1000ms)",
            "memory usage warning: {pct}% of heap — GC pressure increasing",
            "CPU utilization sustained above 90% for 5 minutes",
            "request queue depth: {count} pending (threshold: 50)",
            "connection pool stats: active={count}, idle=0, waiting={count}",
        ],
        "DEBUG": [
            "connection pool: {count} active, {count} idle — utilization {pct}%",
            "{component}: memory footprint growing — current {pct}% of limit",
            "GC stats: {count} collections in last minute, avg pause {ms}ms",
            "resource monitor: CPU {pct}%, memory {pct}%, connections {count}",
        ],
        "INFO": [
            "{service}: request processed successfully",
            "{service}: health check passed",
            "connection pool initialized: max={count}",
        ],
    },
    "dependency_failure": {
        "FATAL": [
            "FATAL: cannot reach {dep} — DNS resolution failed",
            "FATAL: TLS handshake failed with {dep} — certificate expired",
            "Unable to establish connection to {dep}: connection refused",
            "FATAL: {dep} health check failed 10 consecutive times",
        ],
        "ERROR": [
            "connection refused by {dep} on port {port}",
            "timeout connecting to {dep} after {ms}ms",
            "{dep} returned HTTP 503 — service unavailable",
            "circuit breaker OPEN for {dep} — too many consecutive failures",
            "DNS lookup failed for {dep}.internal: NXDOMAIN",
            "TLS certificate for {dep} expired {count} hours ago",
            "connection to {dep} reset by peer — possible crash",
            "{dep} not responding to health probes — marking unavailable",
        ],
        "WARN": [
            "retry attempt {count}/3 for {dep} request — still failing",
            "{dep} latency spike detected: p99 = {ms}ms",
            "falling back to cached data — {dep} unreachable",
            "circuit breaker half-open for {dep} — testing recovery",
        ],
        "DEBUG": [
            "connection to {dep}: intermittent timeouts ({pct}% of requests)",
            "{dep} health check: 1/{count} endpoints responding",
            "trace: {method}() fallback path triggered for {dep} calls",
            "debug: DNS cache entry for {dep} stale — refreshing",
        ],
        "INFO": [
            "{service}: request processed successfully",
            "{service}: health check passed",
            "connection to {dep} established successfully",
        ],
    },
    "configuration_error": {
        "FATAL": [
            "FATAL: failed to parse configuration — invalid YAML at line {count}",
            "Configuration error: missing required field '{component}'",
            "FATAL: {service} cannot start — invalid config version",
            "Config validation failed: {method} endpoint misconfigured",
        ],
        "ERROR": [
            "configuration key '{component}' has invalid value — using broken default",
            "feature flag '{method}' enabled but required dependency not configured",
            "error: environment variable {component}_URL not set — requests will fail",
            "invalid TLS configuration: certificate path does not exist",
            "config reload failed: new config rejected by validation",
            "misconfigured rate limit: {count} req/s (should be {count})",
            "error parsing connection string: invalid format for {dep}",
            "configuration mismatch: service expects v2 protocol but {dep} speaks v1",
        ],
        "WARN": [
            "config value for {component} looks suspicious: '{method}'",
            "deprecated config key detected — migration required",
            "feature flag '{method}' state inconsistent across replicas",
            "config sync: local config diverged from config server",
        ],
        "DEBUG": [
            "config loaded: {component}.{method} = {count} (override from env)",
            "feature flag '{method}' resolved to enabled via config server",
            "debug: config key '{component}' defaulting to fallback value",
            "trace: {method}() using config path A instead of path B",
        ],
        "INFO": [
            "{service}: configuration loaded successfully",
            "{service}: request processed successfully",
            "config version: {version}",
        ],
    },
    "traffic_spike": {
        "FATAL": [
            "FATAL: request queue overflow — {count} requests dropped",
            "FATAL: load balancer cannot distribute — all backends saturated",
            "OOM under load: {count} concurrent requests exhausted heap",
        ],
        "ERROR": [
            "rate limiter triggered: {count} req/s exceeds limit of {count}",
            "request queue full: dropping oldest {count} requests",
            "thread pool exhausted: all {count} workers busy",
            "HTTP 429 Too Many Requests — client rate exceeded",
            "backend overloaded: response time {ms}ms exceeds SLA",
            "connection pool drained by burst: {count} queued connections",
            "auto-scaling triggered but new instances not ready",
            "load shedding active: rejecting {pct}% of incoming requests",
        ],
        "WARN": [
            "traffic volume {pct}% above normal for this time of day",
            "request rate: {count} req/min (baseline: {count} req/min)",
            "upstream reports elevated traffic — brace for load",
            "auto-scaler cooldown: cannot scale further for {count} more seconds",
            "connection backlog: {count} pending connections in accept queue",
        ],
        "DEBUG": [
            "traffic monitor: {count} req/s (normal: {count} req/s)",
            "load balancer: weighted round-robin adjusting for backend latency",
            "rate limiter: {count} tokens remaining in bucket (refill in {ms}ms)",
            "trace: request queued for {ms}ms before processing",
        ],
        "INFO": [
            "{service}: request processed successfully",
            "{service}: health check passed",
            "traffic report: {count} req/min",
        ],
    },
}

# =============================================================================
# Cascade symptom log templates (for upstream services)
# {downstream} = the root cause service name
# =============================================================================

CASCADE_LOGS_EXPLICIT: List[Dict[str, str]] = [
    {"level": "ERROR", "message": "upstream {downstream} connection refused"},
    {"level": "ERROR", "message": "timeout waiting for {downstream} response ({ms}ms exceeded)"},
    {"level": "ERROR", "message": "{downstream} returned HTTP 503 — marking unavailable"},
    {"level": "WARN", "message": "circuit breaker OPEN for {downstream} — too many failures"},
    {"level": "WARN", "message": "retry attempt 3/3 for {downstream} — still failing"},
    {"level": "ERROR", "message": "failed to complete request: {downstream} dependency unavailable"},
    {"level": "WARN", "message": "falling back to degraded mode — {downstream} unreachable"},
    {"level": "ERROR", "message": "{downstream} health check failed — removing from pool"},
]

CASCADE_LOGS_AMBIGUOUS: List[Dict[str, str]] = [
    {"level": "ERROR", "message": "downstream dependency returned error — request failed"},
    {"level": "WARN", "message": "intermittent failures on downstream calls — source unclear"},
    {"level": "ERROR", "message": "unexpected error from backend service — retrying"},
    {"level": "WARN", "message": "elevated error rate on outbound requests — no single source identified"},
    {"level": "ERROR", "message": "request processing failed: upstream returned unexpected status"},
    {"level": "WARN", "message": "backend instability detected — multiple services showing errors"},
    {"level": "WARN", "message": "internal API call failed — checking circuit breakers"},
    {"level": "ERROR", "message": "dependency health degraded — falling back to cached response"},
]

# =============================================================================
# Red herring ingredients
# =============================================================================

RED_HERRING_LOGS: List[Dict[str, str]] = [
    {"level": "WARN", "message": "memory usage critical: {pct}% of heap — potential memory leak detected"},
    {"level": "ERROR", "message": "GC pause exceeded {ms}ms — long stop-the-world event"},
    {"level": "WARN", "message": "cache miss rate elevated: {pct}% (threshold: 15%)"},
    {"level": "WARN", "message": "object pool growing: {count} active objects (threshold: 10000)"},
    {"level": "ERROR", "message": "thread pool near exhaustion: {count}/{count} threads active"},
    {"level": "WARN", "message": "disk I/O latency spike: write latency {ms}ms (normal: 5ms)"},
    {"level": "WARN", "message": "connection churn detected: {count} new connections in last minute"},
    {"level": "ERROR", "message": "request timeout: internal processing exceeded {ms}ms SLA"},
    {"level": "WARN", "message": "log volume spike: {count} entries/min (normal: 200)"},
    {"level": "WARN", "message": "health check response time degraded: {ms}ms (threshold: 100ms)"},
    {"level": "ERROR", "message": "socket buffer overflow: {count} bytes dropped"},
    {"level": "WARN", "message": "CPU steal time elevated: {pct}% — possible noisy neighbor"},
]

# =============================================================================
# Noise / healthy service log templates
# =============================================================================

NOISE_LOGS: List[str] = [
    "{service}: request processed successfully",
    "{service}: health check passed",
    "{service}: session refresh completed successfully",
    "{service}: connection established",
    "{service}: cache hit for frequently accessed key",
    "{service}: response sent in {ms}ms",
    "{service}: new session created",
    "{service}: request processed successfully",
    "{service}: background job completed",
    "{service}: metrics exported successfully",
    "{service}: configuration reloaded",
    "{service}: TLS certificate valid for {count} more days",
]

# =============================================================================
# Alert text fragments
# =============================================================================

ALERT_SYMPTOM_FRAGMENTS: Dict[str, List[str]] = {
    "high_error_rate": [
        "{pct}% of requests failing",
        "error rate elevated above {pct}%",
        "significant increase in error responses",
    ],
    "high_latency": [
        "p99 latency exceeding {ms}ms",
        "response times degraded — {ms}ms average",
        "severe latency on critical endpoints",
    ],
    "service_down": [
        "service completely unresponsive",
        "not responding to health checks",
        "returning 503 on all endpoints",
    ],
    "intermittent": [
        "intermittent failures across multiple endpoints",
        "sporadic errors with no clear pattern",
        "some requests succeeding, others failing unpredictably",
    ],
}

ALERT_IMPACT_FRAGMENTS: List[str] = [
    "Customers unable to complete purchases",
    "Users reporting random logouts and failed transactions",
    "Multiple 502 errors reported on frontend",
    "User-facing latency exceeding acceptable thresholds",
    "Order processing significantly impacted",
    "Customer support tickets spiking",
    "Revenue impact — checkout conversion dropping",
    "Page load times degraded for all users",
    "Authentication failures affecting user sessions",
    "API consumers reporting elevated error rates",
]

ALERT_TEMPLATES: List[str] = [
    "ALERT: {visible_service} experiencing {symptom}. {impact}. {detail}",
    "ALERT: {symptom} detected on {visible_service}. {impact}.",
    "ALERT: Production incident — {visible_service} {symptom}. {impact}. {detail}",
    "ALERT: {impact}. {visible_service} shows {symptom}. {detail}",
]

ALERT_DETAIL_FRAGMENTS: List[str] = [
    "Multiple services may be affected",
    "No clear single point of failure identified",
    "Investigation needed — unclear root cause",
    "Monitoring dashboards showing elevated errors across the stack",
    "PagerDuty triggered — on-call engineer notified",
    "Possible cascade effect from backend services",
    "Situation developing — more details needed",
    "Incident started approximately 15 minutes ago",
]

# =============================================================================
# Cause → correct resource mapping (for scale_up)
# =============================================================================

CAUSE_TO_RESOURCE: Dict[str, Dict[str, str]] = {
    "resource_exhaustion": {
        "database": "connections",
        "payment-svc": "connections",
        "frontend": "memory",
        "api-gateway": "cpu",
        "auth-svc": "memory",
        "checkout-svc": "memory",
        "inventory-svc": "memory",
    },
    "traffic_spike": {
        "database": "connections",
        "payment-svc": "replicas",
        "frontend": "replicas",
        "api-gateway": "replicas",
        "auth-svc": "replicas",
        "checkout-svc": "replicas",
        "inventory-svc": "replicas",
    },
}

# =============================================================================
# Cause → correct restart mode mapping
# =============================================================================

CAUSE_TO_RESTART_MODE: Dict[str, str] = {
    "configuration_error": "graceful",
    "dependency_failure": "force",
}

# =============================================================================
# Changelog templates per cause type
# =============================================================================

CHANGELOG_TEMPLATES: Dict[str, List[str]] = {
    "bad_deployment": [
        "- Refactored {component}.{method}()\n- Updated dependency versions\n- Performance optimization for {method}",
        "- Rewrote {component} request handling\n- Migrated to new serialization format\n- Added retry logic",
        "- Fixed race condition in {component}\n- Updated {method}() signature\n- Removed deprecated fallback path",
        "- Major refactor of {component}\n- New validation logic in {method}()\n- Updated error handling",
        "- Replaced legacy {component} implementation\n- New {method}() code path\n- Updated unit tests",
    ],
    "resource_exhaustion": [
        "- No code changes — config-only release\n- Adjusted pool settings\n- Updated monitoring thresholds",
        "- Routine maintenance release\n- Updated base image\n- No functional changes",
    ],
    "dependency_failure": [
        "- Updated client library for {dep}\n- Added connection timeout configuration\n- Minor logging improvements",
        "- Bumped {dep} SDK version\n- Updated retry policy\n- Added circuit breaker config",
    ],
    "configuration_error": [
        "- Updated configuration schema\n- Added new feature flag: {method}\n- Migrated config format to v2",
        "- New config key: {component}_enabled\n- Updated validation rules\n- Added config versioning",
    ],
    "traffic_spike": [
        "- Added auto-scaling support\n- Updated load balancer configuration\n- Performance improvements",
        "- New rate limiting strategy\n- Updated connection pool sizing\n- Added backpressure handling",
    ],
}

# =============================================================================
# Metric thresholds for detailed check_metrics output
# =============================================================================

METRIC_THRESHOLDS: Dict[str, Dict[str, Any]] = {
    "latency_p99_ms": {"warning": 200.0, "critical": 1000.0, "unit": "ms"},
    "error_rate_pct": {"warning": 5.0, "critical": 20.0, "unit": "%"},
    "cpu_pct": {"warning": 70.0, "critical": 90.0, "unit": "%"},
    "memory_pct": {"warning": 75.0, "critical": 90.0, "unit": "%"},
    "requests_per_min": {"warning_low": 100.0, "unit": "req/min"},
}

METRIC_NAME_MAP: Dict[str, str] = {
    "latency": "latency_p99_ms",
    "error_rate": "error_rate_pct",
    "cpu": "cpu_pct",
    "memory": "memory_pct",
    "rpm": "requests_per_min",
}
