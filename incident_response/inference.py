"""
Inference Script for Incident Response Environment
===================================================
MANDATORY
- Before submitting, ensure the following variables are defined in your environment configuration:
    API_BASE_URL   The API endpoint for the LLM.
    MODEL_NAME     The model identifier to use for inference.
    HF_TOKEN       Your Hugging Face / API key.
    LOCAL_IMAGE_NAME The name of the local image to use for the environment if you are using from_docker_image()

- The inference script must be named `inference.py` and placed in the root directory of the project
- Participants must use OpenAI Client for all LLM calls using above variables
"""

import asyncio
import json
import os
import textwrap
from typing import Any, Dict, List, Optional

from openai import OpenAI

from incident_response import IncidentResponseAction, IncidentResponseEnv

IMAGE_NAME = os.getenv("IMAGE_NAME")
ENV_URL = os.getenv("ENV_URL", "http://localhost:8000")
API_KEY = os.getenv("HF_TOKEN") or os.getenv("API_KEY")
API_BASE_URL = os.getenv("API_BASE_URL") or "https://router.huggingface.co/v1"
MODEL_NAME = os.getenv("MODEL_NAME") or "openai/gpt-oss-20b"
BENCHMARK = "incident_response"
TEMPERATURE = 0.5
MAX_TOKENS = 4096

# Seed for procedural generation — set to None to use static scenarios
# Using a fixed seed ensures reproducible results across runs
EVAL_SEED = int(os.getenv("EVAL_SEED", "42"))

TASKS = ["easy", "medium", "hard"]

SYSTEM_PROMPT = textwrap.dedent("""\
OUTPUT FORMAT: You must reply with EXACTLY ONE LINE containing a valid action command. No explanation. No commentary. No prose. Just the command.

SERVICE TOPOLOGY:
frontend -> api-gateway -> auth-svc, checkout-svc, inventory-svc
checkout-svc -> payment-svc
inventory-svc -> database

VALID COMMANDS:
check_logs <service> <level>
check_logs <service> <level> <keyword>
check_metrics <service> <metric>
check_metrics <service> <metric> history
check_dependencies <service> <depth>
check_dependencies <service> <depth> metrics
check_deployments <service>
check_deployments <service> changelog
diagnose <service> <cause>
rollback_deployment <service> <version>
scale_up <service> <resource>
restart_service <service> <mode>
escalate <severity>

VALUES:
level: ALL, FATAL, ERROR, WARN, INFO, DEBUG
metric: all, latency, error_rate, cpu, memory, rpm
depth: 1, 2
cause: bad_deployment, resource_exhaustion, dependency_failure, configuration_error, traffic_spike
resource: cpu, memory, connections, replicas
mode: graceful, force
severity: low, medium, high, critical

STRATEGY:
1. check_logs on degraded/down services with level=ERROR first
2. check_dependencies with depth=2 to trace upstream
3. check_deployments changelog on suspected service
4. check_metrics with history on suspected root cause
5. diagnose <service> <cause>
6. Apply fix: rollback_deployment needs version from check_deployments, scale_up needs resource from check_metrics, restart_service needs mode (graceful for config, force for dependency)

RULES:
- ONE command per response. Nothing else.
- NEVER repeat the same command.
- ALWAYS diagnose before remediation.
- NEVER guess version/resource — get them from investigation first.
""").strip()


# ---------------------------------------------------------------------------
# Logging helpers — copied verbatim from sample_inference_script.py
# ---------------------------------------------------------------------------

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}", flush=True)


# ---------------------------------------------------------------------------
# Observation formatting
# ---------------------------------------------------------------------------

def format_observation(obs_data: Dict[str, Any], step: int, history: Optional[List[str]] = None) -> str:
    """Format observation into a readable prompt for the LLM."""
    parts = []

    if obs_data.get("alert"):
        parts.append(f"ALERT: {obs_data['alert']}")

    parts.append(f"\nStep {step}/{obs_data.get('max_steps', '?')}")

    # Show action history so the LLM doesn't repeat itself
    if history:
        parts.append("\nActions taken so far:")
        for h in history:
            parts.append(f"  - {h}")
        parts.append("")

    parts.append("Service Statuses:")
    for svc in obs_data.get("service_statuses", []):
        status = svc.get("status", "unknown")
        marker = "!!!" if status == "down" else "!!" if status == "degraded" else ""
        parts.append(
            f"  {marker} {svc['name']}: {status} "
            f"(latency={svc['latency_p99_ms']:.0f}ms, errors={svc['error_rate_pct']:.1f}%)"
        )

    qr = obs_data.get("last_query_result")
    if qr:
        parts.append(f"\nQuery Result ({qr['query_type']} on {qr['target_service']}):")
        data = qr["data"]
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "message" in item:
                    parts.append(f"  [{item.get('level', '?')}] {item['message']}")
                else:
                    parts.append(f"  {json.dumps(item)}")
        elif isinstance(data, dict):
            for k, v in data.items():
                parts.append(f"  {k}: {v}")
        else:
            parts.append(f"  {data}")

    return "\n".join(parts)


def parse_action(text: str) -> IncidentResponseAction:
    """Parse LLM response into a parameterized action."""
    text = text.strip()
    for prefix in ["ACTION:", "Action:", "action:"]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()

    parts = text.split()
    if not parts:
        raise ValueError("Empty action")

    action_type = parts[0].lower()

    if action_type == "escalate":
        severity = parts[1] if len(parts) >= 2 else "medium"
        return IncidentResponseAction(action_type="escalate", severity=severity)

    if action_type == "diagnose" and len(parts) >= 3:
        target = parts[1]
        diagnosis = parts[2]
        if ":" not in diagnosis:
            diagnosis = f"{target}:{diagnosis}"
        return IncidentResponseAction(
            action_type="diagnose", target_service=target, diagnosis=diagnosis,
        )

    if action_type == "check_logs" and len(parts) >= 2:
        target = parts[1]
        log_level = parts[2].upper() if len(parts) >= 3 else "ALL"
        keyword = parts[3] if len(parts) >= 4 else None
        return IncidentResponseAction(
            action_type="check_logs", target_service=target,
            log_level=log_level, keyword=keyword,
        )

    if action_type == "check_metrics" and len(parts) >= 2:
        target = parts[1]
        metric_name = parts[2] if len(parts) >= 3 else "all"
        include_history = len(parts) >= 4 and parts[3].lower() in ("history", "true")
        return IncidentResponseAction(
            action_type="check_metrics", target_service=target,
            metric_name=metric_name, include_history=include_history or None,
        )

    if action_type == "check_dependencies" and len(parts) >= 2:
        target = parts[1]
        depth = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1
        include_metrics = len(parts) >= 4 and parts[3].lower() in ("metrics", "true")
        return IncidentResponseAction(
            action_type="check_dependencies", target_service=target,
            depth=depth, include_metrics=include_metrics or None,
        )

    if action_type == "check_deployments" and len(parts) >= 2:
        target = parts[1]
        include_changelog = len(parts) >= 3 and parts[2].lower() in ("changelog", "true")
        return IncidentResponseAction(
            action_type="check_deployments", target_service=target,
            include_changelog=include_changelog or None,
        )

    if action_type == "rollback_deployment" and len(parts) >= 2:
        target = parts[1]
        target_version = parts[2] if len(parts) >= 3 else None
        return IncidentResponseAction(
            action_type="rollback_deployment", target_service=target,
            target_version=target_version,
        )

    if action_type == "scale_up" and len(parts) >= 2:
        target = parts[1]
        resource = parts[2] if len(parts) >= 3 else None
        return IncidentResponseAction(
            action_type="scale_up", target_service=target, resource=resource,
        )

    if action_type == "restart_service" and len(parts) >= 2:
        target = parts[1]
        mode = parts[2] if len(parts) >= 3 else None
        return IncidentResponseAction(
            action_type="restart_service", target_service=target, mode=mode,
        )

    # Only accept known action types — reject prose/explanations
    valid_types = {
        "check_logs", "check_metrics", "check_dependencies", "check_deployments",
        "diagnose", "rollback_deployment", "scale_up", "restart_service", "escalate",
    }
    if action_type not in valid_types:
        raise ValueError(f"Unknown action type: '{action_type}' (parsed from: {text[:50]})")

    if len(parts) >= 2:
        return IncidentResponseAction(action_type=action_type, target_service=parts[1])

    raise ValueError(f"Cannot parse action: {text}")


def action_to_str(action: IncidentResponseAction) -> str:
    """Format action for logging."""
    if action.action_type == "escalate":
        return f"escalate:{action.severity or 'medium'}"
    base = f"{action.action_type}:{action.target_service}"
    if action.diagnosis:
        return f"{action.action_type}:{action.diagnosis}"
    extras = []
    if action.log_level and action.log_level != "ALL":
        extras.append(f"level={action.log_level}")
    if action.keyword:
        extras.append(f"kw={action.keyword}")
    if action.target_version:
        extras.append(action.target_version)
    if action.resource:
        extras.append(action.resource)
    if action.mode:
        extras.append(action.mode)
    if action.depth and action.depth != 1:
        extras.append(f"depth={action.depth}")
    if extras:
        return f"{base}({','.join(extras)})"
    return base


# ---------------------------------------------------------------------------
# Heuristic fallback agent
# ---------------------------------------------------------------------------

def heuristic_action(
    obs_data: Dict[str, Any],
    step: int,
    history: List[str],
) -> IncidentResponseAction:
    """Simple heuristic fallback if LLM call fails."""
    statuses = obs_data.get("service_statuses", [])

    # Find most affected services
    down = [s for s in statuses if s["status"] == "down"]
    degraded = sorted(
        [s for s in statuses if s["status"] == "degraded"],
        key=lambda s: -s["error_rate_pct"],
    )
    elevated = sorted(
        [s for s in statuses if s["status"] == "healthy" and s["error_rate_pct"] > 5],
        key=lambda s: -s["error_rate_pct"],
    )

    targets = down + degraded + elevated

    # Phase 1: Check logs of most affected services (use ERROR level)
    checked_logs = [h for h in history if "check_logs:" in h]
    if len(checked_logs) < 2 and targets:
        for t in targets:
            if not any(t["name"] in h for h in checked_logs):
                return IncidentResponseAction(
                    action_type="check_logs", target_service=t["name"],
                    log_level="ERROR",
                )

    # Phase 2: Check dependencies (depth=2 to trace root cause)
    checked_deps = [h for h in history if "check_dependencies:" in h]
    if not checked_deps and targets:
        return IncidentResponseAction(
            action_type="check_dependencies", target_service=targets[0]["name"],
            depth=2, include_metrics=True,
        )

    # Phase 3: Check deployments with changelog
    checked_deploys = [h for h in history if "check_deployments:" in h]
    if not checked_deploys and targets:
        return IncidentResponseAction(
            action_type="check_deployments", target_service=targets[0]["name"],
            include_changelog=True,
        )

    # Phase 4: Diagnose the worst service
    diagnosed = [h for h in history if "diagnose:" in h]
    if not diagnosed and targets:
        target = targets[0]["name"]
        cause = "bad_deployment" if down else "resource_exhaustion"
        return IncidentResponseAction(
            action_type="diagnose",
            target_service=target,
            diagnosis=f"{target}:{cause}",
        )

    # Phase 5: Remediate (with placeholder params — heuristic can't know the version)
    if targets:
        target = targets[0]["name"]
        if down:
            return IncidentResponseAction(
                action_type="rollback_deployment", target_service=target,
                target_version="v1.0.0",  # best guess
            )
        return IncidentResponseAction(
            action_type="scale_up", target_service=target,
            resource="connections",
        )

    return IncidentResponseAction(action_type="escalate", severity="high")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_task(env, client: OpenAI, task_id: str, seed: Optional[int] = None) -> None:
    """Run a single task and log results."""
    task_label = f"{task_id}_seed{seed}" if seed is not None else task_id
    log_start(task=task_label, env=BENCHMARK, model=MODEL_NAME)

    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False
    history: List[str] = []

    try:
        reset_kwargs = {"task_id": task_id}
        if seed is not None:
            reset_kwargs["seed"] = seed
        result = await env.reset(**reset_kwargs)
        obs_data = result.observation.model_dump(exclude={"done", "reward", "metadata"})
        done = result.done

        max_steps = obs_data.get("max_steps", 25)
        for step in range(1, max_steps + 1):
            if done:
                break

            prompt = format_observation(obs_data, step, history)

            # Try LLM
            try:
                completion = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    stream=False,
                )
                response_text = (completion.choices[0].message.content or "").strip()
                # Try to parse the first line that looks like an action
                lines = response_text.split("\n")
                action = None
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("//"):
                        continue
                    try:
                        action = parse_action(line)
                        break
                    except ValueError:
                        continue

                if action is None:
                    action = heuristic_action(obs_data, step, history)
            except Exception as exc:
                print(f"[DEBUG] LLM call failed: {exc}", flush=True)
                action = heuristic_action(obs_data, step, history)

            result = await env.step(action)
            obs_data = result.observation.model_dump(exclude={"done", "reward", "metadata"})
            reward = result.reward or 0.0
            done = result.done
            error = None

            rewards.append(reward)
            steps_taken = step
            history.append(action_to_str(action))

            log_step(
                step=step,
                action=action_to_str(action),
                reward=reward,
                done=done,
                error=error,
            )

            if done:
                break

        # Score = final terminal reward (verifier score, already in [0, 1])
        score = rewards[-1] if rewards else 0.0
        score = min(max(score, 0.0), 1.0)
        success = score > 0.5

    finally:
        try:
            await env.close()
        except Exception as e:
            print(f"[DEBUG] env.close() error: {e}", flush=True)
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)


async def main() -> None:
    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    for task_id in TASKS:
        if IMAGE_NAME:
            env = await IncidentResponseEnv.from_docker_image(IMAGE_NAME)
        else:
            env = IncidentResponseEnv(base_url=ENV_URL, message_timeout_s=300, connect_timeout_s=30)
        await run_task(env, client, task_id, seed=EVAL_SEED)


if __name__ == "__main__":
    asyncio.run(main())
