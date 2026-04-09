"""
Procedural scenario generator for incident response tasks.

Takes (difficulty, seed) and deterministically produces a Scenario.
Same seed + difficulty = identical scenario. Different seed = different task.
"""

import random
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from .base import Scenario
from .templates import (
    ALERT_DETAIL_FRAGMENTS,
    ALERT_IMPACT_FRAGMENTS,
    ALERT_SYMPTOM_FRAGMENTS,
    ALERT_TEMPLATES,
    CASCADE_LOGS_AMBIGUOUS,
    CASCADE_LOGS_EXPLICIT,
    CAUSE_TO_REMEDIATION,
    CAUSE_TO_RESOURCE,
    CAUSE_TO_RESTART_MODE,
    CHANGELOG_TEMPLATES,
    DIFFICULTY_CONFIG,
    METRIC_PROFILES,
    NOISE_LOGS,
    RED_HERRING_LOGS,
    ROOT_CAUSE_LOGS,
    SERVICE_CONTEXT,
)

try:
    from ..service_graph import (
        DEPENDENCY_GRAPH,
        REVERSE_GRAPH,
        SERVICE_NAMES,
        _ts,
        build_default_service_states,
    )
except ImportError:
    from server.service_graph import (
        DEPENDENCY_GRAPH,
        REVERSE_GRAPH,
        SERVICE_NAMES,
        _ts,
        build_default_service_states,
    )


class ScenarioGenerator:
    """Deterministic scenario generator driven by (difficulty, seed)."""

    def __init__(self, difficulty: str, seed: int):
        if difficulty not in DIFFICULTY_CONFIG:
            raise ValueError(f"Unknown difficulty '{difficulty}'. Available: easy, medium, hard")
        self.difficulty = difficulty
        self.seed = seed
        self.rng = random.Random(seed)
        self.cfg = DIFFICULTY_CONFIG[difficulty]

    def generate(self) -> Scenario:
        """Generate a complete Scenario deterministically."""
        root_service, cause_type = self._pick_root_cause()
        remediation = CAUSE_TO_REMEDIATION[cause_type]

        # Pre-compute all generated data
        root_state = self._build_root_cause_state(root_service, cause_type)
        cascade_overrides = self._build_cascade_overrides(root_service, cause_type)
        red_herrings = self._build_red_herrings(root_service)
        alert_text = self._generate_alert(root_service, root_state)

        # Build the setup_fn closure
        def setup_fn(services: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
            # Apply root cause state
            svc = services[root_service]
            svc["status"] = root_state["status"]
            svc["metrics"] = root_state["metrics"]
            svc["recent_logs"] = root_state["recent_logs"]
            svc["recent_deployments"] = root_state["recent_deployments"]

            # Apply cascade effects to upstream dependents
            for svc_name, overrides in cascade_overrides.items():
                s = services[svc_name]
                s["status"] = overrides.get("status", s["status"])
                s["metrics"].update(overrides.get("metrics", {}))
                if "recent_logs" in overrides:
                    s["recent_logs"] = overrides["recent_logs"] + s["recent_logs"][:3]
                if "recent_deployments" in overrides:
                    s["recent_deployments"] = overrides["recent_deployments"]

            # Apply red herrings
            for svc_name, herring in red_herrings.items():
                s = services[svc_name]
                s["metrics"].update(herring.get("metrics", {}))
                if "recent_logs" in herring:
                    s["recent_logs"] = herring["recent_logs"] + s["recent_logs"][:4]
                if "recent_deployments" in herring:
                    s["recent_deployments"] = herring["recent_deployments"]
                if "status" in herring:
                    s["status"] = herring["status"]

            return services

        # Build ground truth with remediation parameters
        ground_truth = {
            "root_cause_service": root_service,
            "root_cause_type": cause_type,
            "correct_remediation": remediation,
            "correct_target": root_service,
            "correct_target_version": None,
            "correct_resource": None,
            "correct_restart_mode": None,
            "optimal_steps": self.cfg["optimal_steps"],
            "max_steps": self.cfg["max_steps"],
        }

        if remediation == "rollback_deployment":
            ground_truth["correct_target_version"] = f"v{self._prev_version}"
        elif remediation == "scale_up":
            ground_truth["correct_resource"] = self._pick_resource(cause_type, root_service)
        elif remediation == "restart_service":
            ground_truth["correct_restart_mode"] = self._pick_restart_mode(cause_type)

        return Scenario(
            task_id=self.difficulty,
            name=f"{self.difficulty.title()} (seed={self.seed}): {root_service}/{cause_type}",
            alert_text=alert_text,
            ground_truth=ground_truth,
            setup_fn=setup_fn,
        )

    # ----- Step 1: Pick root cause -----

    def _pick_root_cause(self) -> Tuple[str, str]:
        service = self.rng.choice(self.cfg["eligible_services"])
        cause = self.rng.choice(self.cfg["eligible_causes"])
        return service, cause

    # ----- Step 2: Build root cause state -----

    def _build_root_cause_state(self, service: str, cause_type: str) -> Dict[str, Any]:
        profile = METRIC_PROFILES[cause_type][self.difficulty]
        status = self.rng.choice(self.cfg["root_status_options"])

        metrics = {
            "latency_p99_ms": self._rand_range(profile["latency_p99_ms"]),
            "error_rate_pct": self._rand_range(profile["error_rate_pct"]),
            "cpu_pct": self._rand_range(profile["cpu_pct"]),
            "memory_pct": self._rand_range(profile["memory_pct"]),
            "requests_per_min": self._rand_range(profile["requests_per_min"]),
        }

        # Generate version strings and store for ground truth
        version = self._gen_version()
        prev_version = self._gen_version()
        self._version = version
        self._prev_version = prev_version

        # Pick a downstream dependency for dep-related templates
        deps = DEPENDENCY_GRAPH.get(service, [])
        dep = self.rng.choice(deps) if deps else "external-api"

        ctx = SERVICE_CONTEXT.get(service, SERVICE_CONTEXT["database"])
        component = self.rng.choice(ctx["components"])
        method = self.rng.choice(ctx["methods"])

        params = {
            "service": service,
            "version": version,
            "prev_version": prev_version,
            "component": component,
            "method": method,
            "dep": dep,
            "port": self.rng.choice([8080, 8443, 9090, 3000, 5432]),
            "pct": self.rng.randint(30, 95),
            "count": self.rng.randint(50, 500),
            "ms": self.rng.randint(1000, 15000),
        }

        # Build logs
        logs = self._build_root_logs(cause_type, service, params)

        # Build deployments
        deployments = self._build_deployments(cause_type, version, prev_version)

        return {
            "status": status,
            "metrics": metrics,
            "recent_logs": logs,
            "recent_deployments": deployments,
        }

    def _build_root_logs(
        self, cause_type: str, service: str, params: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """Build log entries for the root cause service."""
        cause_templates = ROOT_CAUSE_LOGS[cause_type]
        cfg = self.cfg

        # Signal logs (the actual evidence)
        signal_logs = []
        for level in cfg["root_log_levels"]:
            templates = cause_templates.get(level, [])
            if templates:
                count = min(self.rng.randint(*cfg["root_log_count"]), len(templates))
                selected = self.rng.sample(templates, count)
                for tmpl in selected:
                    signal_logs.append({
                        "timestamp": _ts(self.rng.randint(0, 10)),
                        "level": level,
                        "message": self._format_template(tmpl, params),
                    })

        # Info/deploy logs (context)
        info_templates = cause_templates.get("INFO", [])
        if info_templates:
            info_count = min(2, len(info_templates))
            for tmpl in self.rng.sample(info_templates, info_count):
                signal_logs.append({
                    "timestamp": _ts(self.rng.randint(5, 15)),
                    "level": "INFO",
                    "message": self._format_template(tmpl, params),
                })

        # Noise logs
        noise_count = self.rng.randint(*cfg["noise_log_count"])
        noise_params = {**params, "ms": self.rng.randint(10, 50)}
        for _ in range(noise_count):
            tmpl = self.rng.choice(NOISE_LOGS)
            signal_logs.append({
                "timestamp": _ts(self.rng.randint(0, 12)),
                "level": "INFO",
                "message": self._format_template(tmpl, noise_params),
            })

        # Shuffle for realism
        self.rng.shuffle(signal_logs)
        return signal_logs[:20]

    def _build_deployments(
        self, cause_type: str, version: str, prev_version: str
    ) -> List[Dict[str, Any]]:
        # Pick a changelog template
        templates = CHANGELOG_TEMPLATES.get(cause_type, CHANGELOG_TEMPLATES["bad_deployment"])
        ctx = SERVICE_CONTEXT.get("database", SERVICE_CONTEXT["database"])
        changelog_params = {
            "component": self.rng.choice(ctx["components"]),
            "method": self.rng.choice(ctx["methods"]),
            "dep": "external-api",
        }
        changelog = self._format_template(self.rng.choice(templates), changelog_params)

        if cause_type == "bad_deployment":
            return [
                {
                    "version": f"v{version}",
                    "timestamp": _ts(self.rng.randint(10, 60)),
                    "status": "active",
                    "changelog": changelog,
                },
                {
                    "version": f"v{prev_version}",
                    "timestamp": _ts(1440),
                    "status": "previous",
                    "changelog": "- Stable release\n- Minor bug fixes",
                },
            ]
        else:
            return [
                {
                    "version": f"v{prev_version}",
                    "timestamp": _ts(self.rng.randint(1440, 4320)),
                    "status": "active",
                    "changelog": "- Stable release\n- No recent changes",
                },
            ]

    # ----- Step 3: Build cascade overrides -----

    def _build_cascade_overrides(
        self, root_service: str, cause_type: str
    ) -> Dict[str, Dict[str, Any]]:
        """Build metric/log overrides for upstream dependents of the root cause."""
        overrides: Dict[str, Dict[str, Any]] = {}
        multiplier = self.cfg["upstream_metric_multiplier"]
        names_root = self.cfg["cascade_names_root"]

        root_profile = METRIC_PROFILES[cause_type][self.difficulty]
        root_err = self._rand_range(root_profile["error_rate_pct"])
        root_lat = self._rand_range(root_profile["latency_p99_ms"])

        visited = {root_service}
        queue = []
        for dep in REVERSE_GRAPH.get(root_service, []):
            if dep not in visited:
                queue.append((dep, 1))
                visited.add(dep)

        while queue:
            svc_name, level = queue.pop(0)

            # Upstream metrics scaled by difficulty multiplier
            if level == 1:
                err_pct = min(root_err * multiplier * (1.1 ** level), 60.0)
                lat_ms = min(root_lat * multiplier * (1.1 ** level), 15000.0)
                svc_status = "degraded" if err_pct > 15 else "healthy"
            else:
                err_pct = min(root_err * multiplier * 0.5, 20.0)
                lat_ms = min(root_lat * multiplier * 0.4, 5000.0)
                svc_status = "healthy"

            # Build cascade logs
            log_pool = CASCADE_LOGS_EXPLICIT if names_root else CASCADE_LOGS_AMBIGUOUS
            cascade_log_count = self.rng.randint(2, 4)
            selected_logs = self.rng.choices(log_pool, k=cascade_log_count)
            logs = []
            for entry in selected_logs:
                logs.append({
                    "timestamp": _ts(self.rng.randint(0, 5)),
                    "level": entry["level"],
                    "message": entry["message"].format(
                        downstream=root_service,
                        ms=self.rng.randint(3000, 12000),
                    ),
                })

            overrides[svc_name] = {
                "status": svc_status,
                "metrics": {
                    "latency_p99_ms": round(lat_ms, 1),
                    "error_rate_pct": round(err_pct, 1),
                    "cpu_pct": round(self.rng.uniform(40, 75), 1),
                },
                "recent_logs": logs,
            }

            # Continue BFS upstream
            for dep in REVERSE_GRAPH.get(svc_name, []):
                if dep not in visited:
                    queue.append((dep, level + 1))
                    visited.add(dep)

        return overrides

    # ----- Step 4: Red herrings -----

    def _build_red_herrings(self, root_service: str) -> Dict[str, Dict[str, Any]]:
        """Inject misleading evidence into non-root-cause services."""
        rh_count_cfg = self.cfg["red_herring_count"]
        if isinstance(rh_count_cfg, int):
            rh_count = rh_count_cfg
        else:
            rh_count = self.rng.randint(*rh_count_cfg)

        if rh_count == 0:
            return {}

        # Pick services to be red herrings (exclude root cause)
        candidates = [s for s in SERVICE_NAMES if s != root_service]
        rh_count = min(rh_count, len(candidates))
        herring_services = self.rng.sample(candidates, rh_count)

        herrings: Dict[str, Dict[str, Any]] = {}
        for svc_name in herring_services:
            params = {
                "pct": self.rng.randint(75, 95),
                "ms": self.rng.randint(200, 800),
                "count": self.rng.randint(100, 500),
            }

            # Misleading logs
            log_count = self.rng.randint(2, 4)
            selected = self.rng.choices(RED_HERRING_LOGS, k=log_count)
            logs = []
            for entry in selected:
                logs.append({
                    "timestamp": _ts(self.rng.randint(0, 5)),
                    "level": entry["level"],
                    "message": self._format_template(entry["message"], params),
                })

            # Elevated metrics
            herring_data: Dict[str, Any] = {
                "metrics": {
                    "memory_pct": round(self.rng.uniform(78, 93), 1),
                    "cpu_pct": round(self.rng.uniform(65, 88), 1),
                    "error_rate_pct": round(self.rng.uniform(8, 25), 1),
                    "latency_p99_ms": round(self.rng.uniform(500, 3000), 1),
                },
                "recent_logs": logs,
                "status": "degraded" if self.rng.random() > 0.4 else "healthy",
            }

            # Fake recent deployment (makes it look like a bad deploy candidate)
            if self.rng.random() > 0.3:
                fake_version = self._gen_version()
                herring_data["recent_deployments"] = [
                    {
                        "version": f"v{fake_version}",
                        "timestamp": _ts(self.rng.randint(15, 90)),
                        "status": "active",
                    },
                    {
                        "version": f"v{self._gen_version()}",
                        "timestamp": _ts(self.rng.randint(1440, 4320)),
                        "status": "previous",
                    },
                ]

            herrings[svc_name] = herring_data

        return herrings

    # ----- Step 5: Alert text -----

    def _generate_alert(
        self, root_service: str, root_state: Dict[str, Any]
    ) -> str:
        """Generate alert text that describes visible symptoms, NOT the root cause."""
        # For easy, alert can mention the affected area
        # For medium/hard, alert should be misleading (describe upstream symptoms)
        if self.difficulty == "easy":
            visible = root_service
            symptom_key = "service_down" if root_state["status"] == "down" else "high_error_rate"
        else:
            # Pick a non-root service that would be visibly affected
            upstreams = REVERSE_GRAPH.get(root_service, [])
            if upstreams:
                visible = self.rng.choice(upstreams)
            else:
                visible = self.rng.choice([s for s in SERVICE_NAMES if s != root_service])
            symptom_key = self.rng.choice(["high_error_rate", "high_latency", "intermittent"])

        symptom_templates = ALERT_SYMPTOM_FRAGMENTS[symptom_key]
        symptom = self.rng.choice(symptom_templates).format(
            pct=self.rng.randint(20, 60),
            ms=self.rng.randint(2000, 10000),
        )
        impact = self.rng.choice(ALERT_IMPACT_FRAGMENTS)
        detail = self.rng.choice(ALERT_DETAIL_FRAGMENTS)
        template = self.rng.choice(ALERT_TEMPLATES)

        return template.format(
            visible_service=visible,
            symptom=symptom,
            impact=impact,
            detail=detail,
        )

    # ----- Remediation parameter helpers -----

    def _pick_resource(self, cause_type: str, service: str) -> str:
        """Determine the correct resource for scale_up based on cause and service."""
        mapping = CAUSE_TO_RESOURCE.get(cause_type, {})
        return mapping.get(service, self.rng.choice(["cpu", "memory", "connections"]))

    def _pick_restart_mode(self, cause_type: str) -> str:
        """Determine correct restart mode based on cause type."""
        return CAUSE_TO_RESTART_MODE.get(cause_type, "graceful")

    # ----- Utility methods -----

    def _rand_range(self, rng_tuple: Tuple[float, float]) -> float:
        return round(self.rng.uniform(rng_tuple[0], rng_tuple[1]), 1)

    def _gen_version(self) -> str:
        return f"{self.rng.randint(1, 5)}.{self.rng.randint(0, 15)}.{self.rng.randint(0, 9)}"

    def _format_template(self, template: str, params: Dict[str, Any]) -> str:
        """Safe format that ignores missing keys."""
        try:
            return template.format(**params)
        except KeyError:
            return template


def generate_scenario(difficulty: str = "easy", seed: int = 0) -> Scenario:
    """Public API: generate a deterministic scenario."""
    gen = ScenarioGenerator(difficulty=difficulty, seed=seed)
    return gen.generate()
