"""
Custom Gradio web interface for the Incident Response Environment.

Purpose-built SRE dashboard with service status grid, parameterized
action form, investigation results, step history, and reward tracking.
"""

import json
import random
from typing import Any, Dict, List, Optional

import gradio as gr

try:
    from .incident_response_environment import IncidentResponseEnvironment
    from .scenarios import get_scenario
    from .service_graph import DEPENDENCY_GRAPH, REVERSE_GRAPH
except ImportError:
    from server.incident_response_environment import IncidentResponseEnvironment
    from server.scenarios import get_scenario
    from server.service_graph import DEPENDENCY_GRAPH, REVERSE_GRAPH

try:
    from ..models import IncidentResponseAction
except ImportError:
    from models import IncidentResponseAction

# ── Constants ───────────────────────────────────────────────────────────────

SERVICES = [
    "frontend", "api-gateway", "auth-svc",
    "checkout-svc", "inventory-svc", "payment-svc", "database",
]
ACTION_TYPES = [
    "check_logs", "check_metrics", "check_dependencies", "check_deployments",
    "diagnose", "rollback_deployment", "scale_up", "restart_service", "escalate",
]
LOG_LEVELS = ["ALL", "FATAL", "ERROR", "WARN", "INFO", "DEBUG"]
METRIC_NAMES = ["all", "latency", "error_rate", "cpu", "memory", "rpm"]
RESOURCES = ["cpu", "memory", "connections", "replicas"]
MODES = ["graceful", "force"]
CAUSES = [
    "bad_deployment", "resource_exhaustion", "dependency_failure",
    "configuration_error", "traffic_spike",
]
SEVERITIES = ["low", "medium", "high", "critical"]

STATUS_EMOJI = {"healthy": "🟢", "degraded": "🟡", "down": "🔴"}

CSS = """
.alert-banner {
    background: #fee2e2; border-left: 4px solid #ef4444; padding: 12px 16px;
    border-radius: 4px; margin-bottom: 8px; color: #991b1b; font-weight: 500;
}
.step-entry { border-bottom: 1px solid #e5e7eb; padding: 8px 0; }
.reward-pos { color: #16a34a; font-weight: 600; }
.reward-neg { color: #dc2626; font-weight: 600; }
.reward-zero { color: #6b7280; }
.status-bar {
    background: #1e293b; color: #e2e8f0; padding: 8px 16px;
    border-radius: 6px; font-family: monospace; font-size: 14px;
}
.env-header { border-bottom: 2px solid #334155; padding-bottom: 12px; margin-bottom: 16px; }
"""


# ── Formatting helpers ──────────────────────────────────────────────────────

def _fmt_service_table(statuses: List[Dict]) -> str:
    if not statuses:
        return "*No service data — click Reset to start.*"
    rows = [
        "| Service | Status | Latency (p99) | Error Rate |",
        "|:--------|:------:|:-------------:|:----------:|",
    ]
    for s in statuses:
        emoji = STATUS_EMOJI.get(s.get("status", ""), "⚪")
        name = s.get("name", "?")
        lat = s.get("latency_p99_ms", 0)
        err = s.get("error_rate_pct", 0)
        lat_warn = " ⚠️" if lat > 1000 else ""
        err_warn = " ⚠️" if err > 10 else ""
        rows.append(
            f"| {emoji} **{name}** | {s.get('status', '')} "
            f"| {lat:.0f} ms{lat_warn} | {err:.1f}%{err_warn} |"
        )
    return "\n".join(rows)


def _fmt_query_result(qr: Optional[Dict]) -> str:
    if qr is None:
        return ""
    qt = qr.get("query_type", "")
    target = qr.get("target_service", "")
    data = qr.get("data", "")
    header = f"**{qt}** on `{target}`\n\n"

    if qt == "check_logs":
        if isinstance(data, list):
            if not data:
                return header + "*No matching log entries.*"
            lines = []
            for entry in data:
                lvl = entry.get("level", "?")
                msg = entry.get("message", "")
                icon = {"FATAL": "🔴", "ERROR": "🔴", "WARN": "🟡", "INFO": "⚪", "DEBUG": "🔵"}.get(lvl, "")
                lines.append(f"{icon} `{lvl:5s}` {msg}")
            return header + "\n\n".join(lines)
        return header + str(data)

    if qt == "check_metrics":
        if isinstance(data, dict):
            if "current" in data and "baseline_1h_ago" in data:
                lines = ["| Metric | Current | Baseline | Delta |", "|:---|---:|---:|---:|"]
                for k, v in data.get("changes", {}).items():
                    delta = v.get("delta", 0)
                    arrow = "📈" if delta > 5 else "📉" if delta < -5 else "➡️"
                    lines.append(
                        f"| `{k}` | {v.get('current', 0):.1f} | {v.get('baseline', 0):.1f} | {arrow} {delta:+.1f} |"
                    )
                return header + "\n".join(lines)
            elif "metric" in data:
                status = data.get("status", "")
                icon = {"CRITICAL": "🔴", "WARNING": "🟡", "normal": "🟢"}.get(status, "")
                hist = ""
                if "baseline_1h_ago" in data:
                    hist = f"\n\nBaseline (1h ago): {data['baseline_1h_ago']:.1f} | Delta: {data.get('delta', 0):+.1f}"
                return (
                    header
                    + f"**{data['metric']}**: `{data.get('value', 0):.1f}` {data.get('unit', '')} "
                    + f"{icon} {status}{hist}"
                )
            else:
                lines = ["| Metric | Value |", "|:---|---:|"]
                for k, v in data.items():
                    lines.append(f"| `{k}` | {v} |")
                return header + "\n".join(lines)
        return header + str(data)

    if qt == "check_dependencies":
        if isinstance(data, list):
            lines = []
            for dep in data:
                emoji = STATUS_EMOJI.get(dep.get("status", ""), "⚪")
                line = f"- {emoji} **{dep.get('name', '?')}** ({dep.get('status', '')})"
                if "metrics" in dep:
                    m = dep["metrics"]
                    line += f" — lat: {m.get('latency_p99_ms', 0):.0f}ms, err: {m.get('error_rate_pct', 0):.1f}%"
                if "dependencies" in dep:
                    for td in dep["dependencies"]:
                        te = STATUS_EMOJI.get(td.get("status", ""), "⚪")
                        sub = f"\n    - {te} **{td.get('name', '?')}** ({td.get('status', '')})"
                        if "metrics" in td:
                            tm = td["metrics"]
                            sub += f" — lat: {tm.get('latency_p99_ms', 0):.0f}ms, err: {tm.get('error_rate_pct', 0):.1f}%"
                        line += sub
                lines.append(line)
            return header + "\n".join(lines)

    if qt == "check_deployments":
        if isinstance(data, list):
            lines = []
            for d in data:
                badge = "🟢 active" if d.get("status") == "active" else "⚫ previous"
                line = f"- **{d.get('version', '?')}** — {badge} ({d.get('timestamp', '')})"
                if "changelog" in d:
                    line += f"\n  ```\n  {d['changelog']}\n  ```"
                lines.append(line)
            return header + "\n".join(lines)

    if qt == "diagnose":
        return header + f"✅ {data}"
    if qt == "error":
        return header + f"❌ {data}"
    if qt in ("escalate", "rollback_deployment", "scale_up", "restart_service"):
        return header + str(data)

    return header + f"```json\n{json.dumps(data, indent=2, default=str)}\n```"


def _fmt_step_log(step_history: List[Dict]) -> str:
    """Full step log with action details and response summaries."""
    if not step_history:
        return "*No steps taken yet.*"
    parts = []
    for i, entry in enumerate(step_history, 1):
        reward = entry.get("reward", 0)
        if reward > 0.01:
            r_class = "🟢"
        elif reward < -0.01:
            r_class = "🔴"
        else:
            r_class = "⚪"

        action_str = entry.get("action_summary", "?")
        parts.append(
            f"**Step {i}** | {r_class} `{reward:+.3f}` | `{action_str}`"
        )
        response = entry.get("response_summary", "")
        if response:
            parts.append(f"> {response}")
        parts.append("")
    return "\n".join(parts)


# ── Simulate Agent ──────────────────────────────────────────────────────────

def _build_agent_steps(task_id: str, seed: int) -> List[Dict[str, Any]]:
    """
    Build a realistic agent action sequence that:
    - Adapts to difficulty (more investigation for harder tasks)
    - Makes random mistakes (wrong services, wrong params, repeated actions)
    - Always completes the task before max_steps
    - Varies with seed (different seed = different mistake pattern)

    Uses a separate RNG seeded with seed+1000 so the agent behavior
    differs from the scenario generation (which uses seed directly).
    """
    scenario = get_scenario(task_id, seed=seed)
    gt = scenario.ground_truth
    root = gt["root_cause_service"]
    cause = gt["root_cause_type"]
    remediation = gt["correct_remediation"]
    max_steps = gt["max_steps"]

    # Agent RNG — offset from scenario seed so behavior varies independently
    rng = random.Random(seed + 1000)

    # Compute budget: leave 3 steps for diagnose + remediate + buffer
    budget = max_steps - 3

    # Gather topology info
    upstreams = REVERSE_GRAPH.get(root, [])
    all_others = [s for s in SERVICES if s != root]
    rng.shuffle(all_others)

    # Pick 1-3 red herring services (more for harder difficulties)
    n_herrings = {"easy": 1, "medium": 2, "hard": 3}.get(task_id, 2)
    red_herrings = all_others[:n_herrings]

    steps: List[Dict[str, Any]] = []

    # ── Phase 1: Initial investigation (explore visible symptoms) ──
    # Start with the most visibly affected services (not root cause)
    initial_targets = []
    if upstreams:
        initial_targets.extend(upstreams[:2])
    initial_targets.extend(red_herrings[:1])
    # Deduplicate while preserving order
    seen = set()
    initial_targets = [s for s in initial_targets if not (s in seen or seen.add(s))]

    for svc in initial_targets[:2]:
        action_type = rng.choice(["check_logs", "check_metrics"])
        if action_type == "check_logs":
            steps.append({"action_type": "check_logs", "target_service": svc, "log_level": "ERROR"})
        else:
            steps.append({"action_type": "check_metrics", "target_service": svc, "metric_name": "all"})

    # ── Phase 2: Mistakes — random unproductive actions ──
    n_mistakes = rng.randint(2, min(4, budget - 6))
    mistake_types = [
        # Wrong service investigation
        lambda: {"action_type": rng.choice(["check_logs", "check_metrics"]),
                 "target_service": rng.choice(red_herrings),
                 **({"log_level": rng.choice(LOG_LEVELS)} if rng.random() > 0.5 else {"metric_name": "all"})},
        # Repeat an earlier action (escalating penalty)
        lambda: steps[rng.randint(0, max(0, len(steps) - 1))].copy() if steps else
                {"action_type": "check_metrics", "target_service": rng.choice(red_herrings), "metric_name": "all"},
        # Wrong deployment check
        lambda: {"action_type": "check_deployments", "target_service": rng.choice(red_herrings)},
        # Wrong keyword search
        lambda: {"action_type": "check_logs", "target_service": rng.choice(all_others),
                 "log_level": "ERROR", "keyword": rng.choice(["timeout", "memory", "disk", "network"])},
    ]
    for _ in range(n_mistakes):
        mistake_fn = rng.choice(mistake_types)
        step = mistake_fn()
        # Fix up check_logs to have log_level
        if step.get("action_type") == "check_logs" and "log_level" not in step:
            step["log_level"] = "ERROR"
        # Fix up check_metrics to have metric_name
        if step.get("action_type") == "check_metrics" and "metric_name" not in step:
            step["metric_name"] = "all"
        steps.append(step)

    # ── Phase 3: Productive investigation toward root cause ──
    # Check dependencies to trace the chain
    trace_svc = upstreams[0] if upstreams else root
    steps.append({
        "action_type": "check_dependencies", "target_service": trace_svc,
        "depth": 2, "include_metrics": True,
    })

    # Check logs on root cause
    log_level = rng.choice(["ERROR", "ALL", "WARN"]) if task_id != "hard" else "DEBUG"
    steps.append({"action_type": "check_logs", "target_service": root, "log_level": log_level})

    # Check deployments on root cause (needed for rollback version)
    steps.append({"action_type": "check_deployments", "target_service": root, "include_changelog": True})

    # Check metrics on root cause with history
    steps.append({
        "action_type": "check_metrics", "target_service": root,
        "metric_name": rng.choice(["all", "cpu", "error_rate"]), "include_history": True,
    })

    # ── Phase 4: Maybe another mistake — wrong diagnosis ──
    if rng.random() > 0.3:
        wrong_causes = [c for c in CAUSES if c != cause]
        wrong_target = rng.choice([root] + red_herrings[:1])
        steps.append({
            "action_type": "diagnose", "target_service": wrong_target,
            "diagnosis": f"{wrong_target}:{rng.choice(wrong_causes)}",
        })

    # ── Phase 5: Maybe a failed remediation attempt ──
    if rng.random() > 0.5 and task_id != "easy":
        wrong_svc = rng.choice(red_herrings)
        if remediation == "rollback_deployment":
            steps.append({"action_type": "rollback_deployment", "target_service": wrong_svc,
                          "target_version": f"v{rng.randint(1,3)}.{rng.randint(0,9)}.{rng.randint(0,9)}"})
        elif remediation == "scale_up":
            steps.append({"action_type": "scale_up", "target_service": wrong_svc,
                          "resource": rng.choice(RESOURCES)})
        else:
            steps.append({"action_type": "restart_service", "target_service": wrong_svc,
                          "mode": rng.choice(MODES)})

    # ── Phase 6: Correct diagnosis + remediation (always succeeds) ──
    steps.append({
        "action_type": "diagnose", "target_service": root,
        "diagnosis": f"{root}:{cause}",
    })

    rem_action: Dict[str, Any] = {"action_type": remediation, "target_service": root}
    if remediation == "rollback_deployment":
        rem_action["target_version"] = gt["correct_target_version"]
    elif remediation == "scale_up":
        rem_action["resource"] = gt["correct_resource"]
    elif remediation == "restart_service":
        rem_action["mode"] = gt["correct_restart_mode"]
    steps.append(rem_action)

    # Trim if we somehow exceeded budget (shouldn't happen, but safety)
    return steps[:max_steps - 1]


def _action_summary(action: Dict) -> str:
    """One-line summary of an action dict."""
    at = action.get("action_type", "?")
    target = action.get("target_service", "")
    extras = []
    if action.get("log_level"):
        extras.append(action["log_level"])
    if action.get("keyword"):
        extras.append(f'kw="{action["keyword"]}"')
    if action.get("metric_name"):
        extras.append(action["metric_name"])
    if action.get("include_history"):
        extras.append("history")
    if action.get("depth"):
        extras.append(f"depth={action['depth']}")
    if action.get("include_metrics"):
        extras.append("metrics")
    if action.get("include_changelog"):
        extras.append("changelog")
    if action.get("diagnosis"):
        extras.append(action["diagnosis"])
    if action.get("target_version"):
        extras.append(action["target_version"])
    if action.get("resource"):
        extras.append(action["resource"])
    if action.get("mode"):
        extras.append(action["mode"])
    if action.get("severity"):
        extras.append(action["severity"])
    extra_str = f"({', '.join(extras)})" if extras else ""
    return f"{at} {target} {extra_str}".strip()


def _response_summary(obs_data: Dict) -> str:
    """Short response summary from an observation."""
    qr = obs_data.get("last_query_result")
    if not qr:
        return ""
    qt = qr.get("query_type", "")
    data = qr.get("data", "")
    if qt == "check_logs" and isinstance(data, list):
        return f"{len(data)} log entries returned"
    if qt == "check_metrics" and isinstance(data, dict):
        if "current" in data:
            return "metrics with baseline comparison"
        if "metric" in data:
            return f"{data['metric']}: {data.get('value', '?')} ({data.get('status', '')})"
        return f"{len(data)} metrics"
    if qt == "check_dependencies" and isinstance(data, list):
        return f"{len(data)} dependencies"
    if qt == "check_deployments" and isinstance(data, list):
        return f"{len(data)} deployments"
    if isinstance(data, str):
        return data[:80]
    return qt


# ── Build the Gradio app ───────────────────────────────────────────────────

def build_gradio_demo() -> gr.Blocks:
    """Build the complete Gradio demo (mounted directly, no Playground tab)."""

    with gr.Blocks(title="Incident Response Environment") as demo:

        # ── Shared environment instance (per-session via gr.State) ──
        env_state = gr.State(None)  # holds the IncidentResponseEnvironment instance
        episode_data = gr.State({
            "active": False, "history": [], "rewards": [],
            "step": 0, "max_steps": 0, "cumulative": 0.0,
        })

        # ── Header ──
        gr.Markdown(
            """
            <div class="env-header">

            # 🚨 Incident Response Environment

            **SRE On-Call Incident Triage** — An AI agent receives a production alert about a failing
            microservice system. Investigate logs, metrics, and dependencies to diagnose the root cause,
            then take the correct remediation action. Scored on diagnosis accuracy, remediation correctness,
            investigation efficiency, and operational safety. All scoring is deterministic.

            </div>
            """
        )

        # ── Status bar ──
        status_bar = gr.Markdown(
            '<div class="status-bar">Episode not started — select a difficulty and seed, then click Reset</div>'
        )

        # ── Alert ──
        alert_box = gr.Markdown("", visible=False)

        # ── Top row: Services + Current Result ──
        with gr.Row(equal_height=False):
            with gr.Column(scale=1):
                gr.Markdown("### 📊 Service Status")
                services_md = gr.Markdown("*Click Reset to load services.*")
            with gr.Column(scale=1):
                gr.Markdown("### 🔍 Current Investigation Result")
                results_md = gr.Markdown("*Execute an action to see results here.*")

        # ── Middle row: Actions + Step History ──
        with gr.Row(equal_height=False):
            with gr.Column(scale=1):
                gr.Markdown("### ⚡ Actions")
                with gr.Group():
                    with gr.Row():
                        task_dd = gr.Dropdown(["easy", "medium", "hard"], value="easy", label="Difficulty", scale=1)
                        seed_input = gr.Number(value=42, label="Seed", precision=0, scale=1)
                    with gr.Row():
                        reset_btn = gr.Button("🔄 Reset Episode", variant="primary")
                        sim_btn = gr.Button("🤖 Simulate Agent", variant="secondary")

                gr.Markdown("---")

                with gr.Group():
                    action_dd = gr.Dropdown(ACTION_TYPES, value="check_logs", label="Action Type")
                    service_dd = gr.Dropdown(SERVICES, value="payment-svc", label="Target Service")

                    # Conditional fields
                    log_level_dd = gr.Dropdown(LOG_LEVELS, value="ERROR", label="Log Level", visible=True)
                    keyword_input = gr.Textbox(label="Keyword", placeholder="timeout, deployment...", visible=True)
                    metric_dd = gr.Dropdown(METRIC_NAMES, value="all", label="Metric", visible=False)
                    history_cb = gr.Checkbox(label="Include History", visible=False)
                    depth_dd = gr.Dropdown(["1", "2"], value="1", label="Depth", visible=False)
                    inc_metrics_cb = gr.Checkbox(label="Include Metrics", visible=False)
                    changelog_cb = gr.Checkbox(label="Include Changelog", visible=False)
                    diagnosis_input = gr.Textbox(label="Diagnosis", placeholder="service:cause_type", visible=False)
                    version_input = gr.Textbox(label="Target Version", placeholder="v2.3.9", visible=False)
                    resource_dd = gr.Dropdown(RESOURCES, value="connections", label="Resource", visible=False)
                    mode_dd = gr.Dropdown(MODES, value="graceful", label="Mode", visible=False)
                    severity_dd = gr.Dropdown(SEVERITIES, value="high", label="Severity", visible=False)

                    step_btn = gr.Button("▶️ Execute Step", variant="primary", size="lg")

            with gr.Column(scale=1):
                gr.Markdown("### 📜 Step History")
                history_md = gr.Markdown("*No steps taken yet.*", max_height=500)

        # ── Bottom: Reward Chart ──
        with gr.Row():
            reward_chart = gr.LinePlot(
                value=None, x="step", y="cumulative",
                title="Cumulative Reward",
            )

        # ── Toggle parameter visibility ──
        def toggle_params(action_type):
            return {
                log_level_dd: gr.update(visible=action_type == "check_logs"),
                keyword_input: gr.update(visible=action_type == "check_logs"),
                metric_dd: gr.update(visible=action_type == "check_metrics"),
                history_cb: gr.update(visible=action_type == "check_metrics"),
                depth_dd: gr.update(visible=action_type == "check_dependencies"),
                inc_metrics_cb: gr.update(visible=action_type == "check_dependencies"),
                changelog_cb: gr.update(visible=action_type == "check_deployments"),
                diagnosis_input: gr.update(visible=action_type == "diagnose"),
                version_input: gr.update(visible=action_type == "rollback_deployment"),
                resource_dd: gr.update(visible=action_type == "scale_up"),
                mode_dd: gr.update(visible=action_type == "restart_service"),
                severity_dd: gr.update(visible=action_type == "escalate"),
                service_dd: gr.update(visible=action_type != "escalate"),
            }

        action_dd.change(
            toggle_params, inputs=[action_dd],
            outputs=[
                log_level_dd, keyword_input, metric_dd, history_cb,
                depth_dd, inc_metrics_cb, changelog_cb, diagnosis_input,
                version_input, resource_dd, mode_dd, severity_dd, service_dd,
            ],
        )

        # ── Reset handler ──
        def handle_reset(task, seed, env_inst, ep_data):
            env = IncidentResponseEnvironment()
            obs = env.reset(task_id=task, seed=int(seed))
            obs_dict = obs.model_dump()
            max_steps = obs_dict.get("max_steps", 15)

            new_ep = {
                "active": True, "history": [], "rewards": [],
                "step": 0, "max_steps": max_steps, "cumulative": 0.0,
            }
            alert = obs_dict.get("alert", "")
            alert_md = f'<div class="alert-banner">🚨 {alert}</div>' if alert else ""

            return (
                env,
                new_ep,
                f'<div class="status-bar">Step 0 / {max_steps} | Reward: 0.00 | Cumulative: 0.00</div>',
                _fmt_service_table(obs_dict.get("service_statuses", [])),
                "*Execute an action to investigate the incident.*",
                "*No steps taken yet.*",
                None,
                gr.update(visible=bool(alert), value=alert_md),
            )

        reset_btn.click(
            handle_reset,
            inputs=[task_dd, seed_input, env_state, episode_data],
            outputs=[env_state, episode_data, status_bar, services_md, results_md, history_md, reward_chart, alert_box],
        )

        # ── Step handler ──
        def handle_step(
            action_type, service, log_level, keyword, metric, inc_history,
            depth, inc_metrics, changelog, diagnosis, version, resource,
            mode, severity, env_inst, ep_data,
        ):
            if env_inst is None or not ep_data.get("active"):
                return (
                    env_inst, ep_data,
                    '<div class="status-bar">⚠️ Episode not active — click Reset first</div>',
                    "", "*No results.*", _fmt_step_log(ep_data.get("history", [])),
                    None, gr.update(),
                )

            # Build action
            kwargs: Dict[str, Any] = {"action_type": action_type}
            if action_type != "escalate":
                kwargs["target_service"] = service
            if action_type == "check_logs":
                kwargs["log_level"] = log_level
                if keyword and keyword.strip():
                    kwargs["keyword"] = keyword.strip()
            elif action_type == "check_metrics":
                kwargs["metric_name"] = metric
                if inc_history:
                    kwargs["include_history"] = True
            elif action_type == "check_dependencies":
                kwargs["depth"] = int(depth)
                if inc_metrics:
                    kwargs["include_metrics"] = True
            elif action_type == "check_deployments":
                if changelog:
                    kwargs["include_changelog"] = True
            elif action_type == "diagnose":
                kwargs["diagnosis"] = diagnosis
            elif action_type == "rollback_deployment":
                kwargs["target_version"] = version
            elif action_type == "scale_up":
                kwargs["resource"] = resource
            elif action_type == "restart_service":
                kwargs["mode"] = mode
            elif action_type == "escalate":
                kwargs["severity"] = severity

            action = IncidentResponseAction(**kwargs)
            obs = env_inst.step(action)
            obs_dict = obs.model_dump()
            reward = obs_dict.get("reward", 0)
            done = obs_dict.get("done", False)

            ep_data["step"] += 1
            ep_data["rewards"].append(reward)
            ep_data["cumulative"] += reward
            ep_data["history"].append({
                "action_summary": _action_summary(kwargs),
                "response_summary": _response_summary(obs_dict),
                "reward": reward,
            })
            if done:
                ep_data["active"] = False

            import pandas as pd
            chart_data = pd.DataFrame({
                "step": list(range(1, len(ep_data["rewards"]) + 1)),
                "cumulative": [sum(ep_data["rewards"][:i + 1]) for i in range(len(ep_data["rewards"]))],
            })

            status_icon = "✅ RESOLVED" if done and reward > 0 else "❌ FAILED" if done else "🔄"
            status_md = (
                f'<div class="status-bar">'
                f'{status_icon} Step {ep_data["step"]} / {ep_data["max_steps"]} | '
                f'Step Reward: {reward:+.3f} | Cumulative: {ep_data["cumulative"]:+.3f}'
                f'</div>'
            )

            return (
                env_inst, ep_data, status_md,
                _fmt_service_table(obs_dict.get("service_statuses", [])),
                _fmt_query_result(obs_dict.get("last_query_result")),
                _fmt_step_log(ep_data["history"]),
                chart_data,
                gr.update(),
            )

        step_btn.click(
            handle_step,
            inputs=[
                action_dd, service_dd, log_level_dd, keyword_input, metric_dd,
                history_cb, depth_dd, inc_metrics_cb, changelog_cb,
                diagnosis_input, version_input, resource_dd, mode_dd,
                severity_dd, env_state, episode_data,
            ],
            outputs=[
                env_state, episode_data, status_bar, services_md,
                results_md, history_md, reward_chart, alert_box,
            ],
        )

        # ── Simulate Agent handler ──
        def handle_simulate(task, seed, _env_inst, _ep_data):
            env = IncidentResponseEnvironment()
            obs = env.reset(task_id=task, seed=int(seed))
            obs_dict = obs.model_dump()
            max_steps = obs_dict.get("max_steps", 15)

            ep = {
                "active": True, "history": [], "rewards": [],
                "step": 0, "max_steps": max_steps, "cumulative": 0.0,
            }

            alert = obs_dict.get("alert", "")
            alert_md = f'<div class="alert-banner">🚨 {alert}</div>' if alert else ""

            agent_steps = _build_agent_steps(task, int(seed))
            last_obs_dict = obs_dict

            for action_dict in agent_steps:
                if not ep["active"]:
                    break
                action = IncidentResponseAction(**action_dict)
                obs = env.step(action)
                obs_dict = obs.model_dump()
                reward = obs_dict.get("reward", 0)
                done = obs_dict.get("done", False)

                ep["step"] += 1
                ep["rewards"].append(reward)
                ep["cumulative"] += reward
                ep["history"].append({
                    "action_summary": _action_summary(action_dict),
                    "response_summary": _response_summary(obs_dict),
                    "reward": reward,
                })
                if done:
                    ep["active"] = False
                last_obs_dict = obs_dict

            import pandas as pd
            chart_data = pd.DataFrame({
                "step": list(range(1, len(ep["rewards"]) + 1)),
                "cumulative": [sum(ep["rewards"][:i + 1]) for i in range(len(ep["rewards"]))],
            })

            final_reward = ep["rewards"][-1] if ep["rewards"] else 0
            status_icon = "✅ RESOLVED" if not ep["active"] and final_reward > 0 else "❌ FAILED" if not ep["active"] else "🔄"
            status_md = (
                f'<div class="status-bar">'
                f'🤖 Agent Simulation Complete | {status_icon} | '
                f'{ep["step"]} steps | Final: {final_reward:+.3f} | Cumulative: {ep["cumulative"]:+.3f}'
                f'</div>'
            )

            return (
                env, ep, status_md,
                _fmt_service_table(last_obs_dict.get("service_statuses", [])),
                _fmt_query_result(last_obs_dict.get("last_query_result")),
                _fmt_step_log(ep["history"]),
                chart_data,
                gr.update(visible=bool(alert), value=alert_md),
            )

        sim_btn.click(
            handle_simulate,
            inputs=[task_dd, seed_input, env_state, episode_data],
            outputs=[
                env_state, episode_data, status_bar, services_md,
                results_md, history_md, reward_chart, alert_box,
            ],
        )

    return demo
