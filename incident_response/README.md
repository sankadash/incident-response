---
title: Incident Response Environment Server
emoji: 🚨
colorFrom: red
colorTo: yellow
sdk: docker
pinned: false
app_port: 8000
base_path: /web
tags:
  - openenv
---

# Incident Response Environment

An OpenEnv environment that simulates SRE on-call incident triage in a microservice system. An AI agent receives a production alert, investigates by querying logs, metrics, and dependencies, diagnoses the root cause, and takes a remediation action with the correct parameters. All scoring is deterministic — no LLM-as-judge.

## Motivation

Incident triage is a daily task at every tech organization. When a production system fails, on-call engineers must quickly investigate, identify the root cause, and fix it — often under time pressure. This environment captures that workflow as a structured RL task with clear success criteria, making it useful for training and evaluating AI agents on real-world operational reasoning.

## Service Architecture

The simulated system has 7 microservices with realistic dependencies:

```
frontend -> api-gateway -> {auth-svc, checkout-svc, inventory-svc}
                            checkout-svc -> payment-svc
                            inventory-svc -> database
```

Failures cascade upstream through the dependency graph — a crashed payment service causes checkout failures, which show up as 502s on the frontend.

## Procedural Scenario Generation

The environment supports **seed-based procedural generation**. Each combination of `(difficulty, seed)` produces a unique, deterministic incident:

```bash
curl -X POST http://localhost:8000/reset \
  -H "Content-Type: application/json" \
  -d '{"task_id": "medium", "seed": 42}'
```

- Same seed = identical scenario every time (fully reproducible)
- Different seed = different root cause, symptoms, red herrings
- Without a seed, falls back to 3 curated static scenarios

### Generation Space

80 structurally distinct incident types (service x cause combinations). Each structural variant is further diversified by randomized log messages, metric values, version strings, component names, and alert text.

| Difficulty | Eligible Services | Eligible Causes | Red Herrings | Structural Variants |
|---|---|---|---|---|
| Easy | 5 (leaf/mid services) | 2 (bad_deployment, resource_exhaustion) | 0 | **10** |
| Medium | 7 (all services) | 5 (all cause types) | 1-2 | **35** |
| Hard | 7 (all services) | 5 (all cause types) | 2-3 | **35** |

## Action Space

All actions require parameters that mirror real SRE tooling. Investigation parameters control what data you see. Remediation parameters require knowledge that can only be obtained through prior investigation — preventing brute-force guessing.

### Investigation Actions

| Action | Parameters | Description |
|---|---|---|
| `check_logs` | `target_service` (required), `log_level` (ALL/FATAL/ERROR/WARN/INFO/DEBUG), `keyword` (substring filter), `tail` (entry count, default 10, max 50) | Query filtered log entries. On hard scenarios, evidence is at DEBUG level — agent must specify the right filter. |
| `check_metrics` | `target_service` (required), `metric_name` (all/latency/error_rate/cpu/memory/rpm), `include_history` (bool — compare with 1hr-ago baseline) | Query metrics with thresholds (NORMAL/WARNING/CRITICAL). History comparison reveals what changed. |
| `check_dependencies` | `target_service` (required), `depth` (1=direct, 2=transitive), `include_metrics` (bool) | Query dependency tree. Depth 2 follows the chain to discover root causes 2+ levels deep. |
| `check_deployments` | `target_service` (required), `include_changelog` (bool) | Query deployment history. Changelog contains component names that connect to error logs. |

### Diagnosis Action

| Action | Parameters | Description |
|---|---|---|
| `diagnose` | `target_service` (required), `diagnosis` (required, format: `service:cause_type`) | Record diagnosis. Valid causes: `bad_deployment`, `resource_exhaustion`, `dependency_failure`, `configuration_error`, `traffic_spike` |

### Remediation Actions (require specific parameters)

| Action | Parameters | Description |
|---|---|---|
| `rollback_deployment` | `target_service`, `target_version` (REQUIRED — must match previous stable version from `check_deployments`) | Roll back to a specific version. Wrong version = problem persists. |
| `scale_up` | `target_service`, `resource` (REQUIRED — `cpu`, `memory`, `connections`, or `replicas`. Must match bottleneck from `check_metrics`) | Scale a specific resource. Wrong resource = problem persists. |
| `restart_service` | `target_service`, `mode` (REQUIRED — `graceful` or `force`) | Restart with specified mode. Wrong mode on stateful services risks data loss. |
| `escalate` | `severity` (low/medium/high/critical) | Give up and escalate to senior engineer. |

### Cause-to-Remediation Mapping

| Cause Type | Correct Remediation | Required Parameter |
|---|---|---|
| `bad_deployment` | `rollback_deployment` | `target_version` (previous stable version) |
| `resource_exhaustion` | `scale_up` | `resource` (the exhausted resource) |
| `traffic_spike` | `scale_up` | `resource` (typically `replicas` or `cpu`) |
| `dependency_failure` | `restart_service` | `mode=force` (clear stuck connections) |
| `configuration_error` | `restart_service` | `mode=graceful` (reload config safely) |

## Observation Space

| Field | Type | Description |
|---|---|---|
| `alert` | `str \| null` | Alert text (only on first observation after reset) |
| `service_statuses` | `list[ServiceStatus]` | Status of all 7 services: name, status, latency_p99_ms, error_rate_pct |
| `last_query_result` | `QueryResult \| null` | Result from the most recent action |
| `step_number` | `int` | Current step in the episode |
| `max_steps` | `int` | Maximum steps before episode auto-terminates |
| `available_actions` | `list[str]` | Valid action types |
| `reward` | `float` | Per-step reward in [0.0, 1.0] |

## Reward System

All rewards are in **[0.0, 1.0]**. Higher is better. The system provides per-step feedback (not just terminal scores), enabling dense reward signal for RL training.

### Per-Step Reward Tiers

Every action receives an immediate reward based on its quality:

| Tier | Reward | Examples |
|---|---|---|
| **Highly productive** | 0.55 - 0.70 | Investigating root cause service with good params, correct diagnosis |
| **Productive** | 0.40 - 0.55 | Investigating related services, using depth=2 or include_history |
| **Neutral** | 0.35 - 0.40 | Valid investigation on unrelated service (first time) |
| **Diminishing** | 0.10 - 0.30 | Repeated exact same action (escalating: 0.30, 0.25, 0.20, 0.15, 0.10) |
| **Malformed** | 0.05 | Invalid action type, missing required target, unknown service |
| **Wrong remediation** | 0.02 - 0.10 | Wrong target (0.02), wrong action type (0.08), wrong params (0.10) |

### Investigation Reward Bonuses

Stacked on top of the base reward (0.40), capped at 0.70 total:

| Factor | Bonus | How It's Earned |
|---|---|---|
| Investigating root cause service | +0.10 | Target is the actual failing service |
| Adjacent to root cause (dependency path) | +0.05 | Target is upstream/downstream of root cause |
| Checking degraded/down service | +0.02 to +0.03 | Targeting visibly unhealthy services |
| Exploring new service (first time) | +0.02 | Haven't checked this service before |
| Using depth=2 (transitive dependencies) | +0.02 | Traces the full dependency chain |
| Using include_history (baseline comparison) | +0.02 | Reveals what recently changed |
| Using include_changelog (deployment diffs) | +0.02 | Connects code changes to errors |
| Correct log level on root cause | +0.02 | log_level matches evidence level in logs |

### Diagnosis Rewards

| Outcome | Reward |
|---|---|
| Exact match (correct service + cause) | **0.70** |
| Right service, wrong cause | **0.50** |
| Wrong diagnosis | **0.15** |
| Missing diagnosis field | **0.05** |

### Terminal (Episode End) Score

When the episode ends (correct fix, escalation, or max steps), the verifier computes a final score:

```
total = 0.40 * diagnosis + 0.30 * remediation + 0.20 * efficiency + 0.10 * safety
```

All component scores are in [0.0, 1.0]:

| Component | Weight | 1.0 | ~0.5 | 0.0 |
|---|---|---|---|---|
| **Diagnosis** | 40% | Correct service + cause | Right service, wrong cause (0.6) | No diagnosis made |
| **Remediation** | 30% | Correct action + target + params | Escalated (0.5) | Wrong target |
| **Efficiency** | 20% | At or under optimal steps | Halfway through budget | Ran out of time |
| **Safety** | 10% | No premature destructive actions | 2 premature (0.5) | 4+ premature |

### Remediation Parameter Scoring

| Outcome | Remediation Score |
|---|---|
| Correct action + target + correct params | **1.0** |
| Escalated | **0.5** |
| Correct action + target + wrong resource | **0.3** |
| Correct action + target + wrong version | **0.2** |
| Right target + wrong action type | **0.15** |
| Correct action + target + wrong restart mode | **0.1** |
| Wrong target | **0.0** |

### Anti-Reward-Hacking

- Premature correct fix (no diagnosis) is capped at `min(score * 0.25, 0.15)` — guessing the fix without investigating yields almost nothing
- Remediation requires investigation-derived parameters (version strings, resource types) that cannot be guessed
- Repeat detection uses full action signatures (type + target + all params) — different params on the same service are not penalized

## Tasks

### Static Scenarios (no seed)

#### Easy: "The Obvious Crash"
`payment-svc` crashes from a bad deployment. Logs show `FATAL: NullPointerException`. Agent needs to find the previous version (`v2.3.9`) and roll back.
- **Max steps:** 15 | **Optimal steps:** 3

#### Medium: "The Cascading Slowdown"
Database connection pool exhaustion cascades through inventory and checkout. `checkout-svc` has the worst visible metrics (55% errors, 12s latency) but the root cause is `database`. Agent must trace dependencies and identify `connections` as the bottleneck resource.
- **Max steps:** 20 | **Optimal steps:** 5

#### Hard: "The Intermittent Poisoned Deploy"
`auth-svc` deploys a bad version breaking 30% of token validations. The service appears **healthy** by all metrics. `checkout-svc` looks like the problem (degraded, high memory, recent deploy). Evidence is buried in DEBUG logs. Agent must use log level filters and check deployments with changelogs to connect the dots.
- **Max steps:** 25 | **Optimal steps:** 7

### Procedural Scenarios (with seed)

| Aspect | Easy | Medium | Hard |
|---|---|---|---|
| Root cause visibility | Down or degraded | Mildly elevated | Appears completely healthy |
| Log evidence | FATAL/ERROR, explicit | WARN mixed with noise | 1-2 DEBUG buried in 12-15 INFO |
| Cascade behavior | Logs name root cause | Logs name root cause but noisy | Ambiguous references |
| Upstream vs root metrics | Root looks worse | Upstream looks worse | Upstream looks far worse |
| Red herrings | None | 1-2 services | 2-3 services with fake deploys |
| Alert text | Points near root cause | Upstream symptoms | Scattered multi-service |

## Episode State Machine

```
reset(task_id, seed?) --> INITIAL STATE (alert + service overview)
        |
        v
   INVESTIGATION LOOP <-----------+
   |  check_logs(level, keyword)   |
   |  check_metrics(name, history) |
   |  check_dependencies(depth)    |
   |  check_deployments(changelog) |
   |  diagnose ------------------->+
   |
   v (remediation with params / escalate / max_steps)
   EPISODE END --> verifier score [0.0, 1.0]
```

**Terminal conditions:**
1. Correct remediation with correct parameters → `done=True`, verifier score
2. `escalate` → `done=True`, remediation_score=0.5
3. `step_number >= max_steps` → `done=True`, verifier score with whatever was recorded
4. Wrong remediation → target temporarily appears healthy, symptoms return next step

## Setup & Usage

### Docker

```bash
cd incident_response
docker build -t incident_response-env:latest -f server/Dockerfile .
docker run -p 8000:8000 incident_response-env:latest
```

### Local Development

```bash
cd incident_response
uv sync
uv run server
```

### Web Dashboard

Visit `http://localhost:8000/web` for the interactive Gradio dashboard with:
- Service status grid with color-coded health indicators
- Parameterized action form with conditional fields
- Formatted investigation results (logs, metrics, dependency trees, deployment changelogs)
- Episode history with per-step rewards
- Cumulative reward chart

To enable the web interface locally:
```bash
ENABLE_WEB_INTERFACE=true uv run server
```

### API Examples

```bash
# Reset with a procedurally generated scenario
curl -X POST http://localhost:8000/reset \
  -H "Content-Type: application/json" \
  -d '{"task_id": "hard", "seed": 42}'

# Investigation with parameters
curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"action": {"action_type": "check_logs", "target_service": "payment-svc", "log_level": "ERROR", "keyword": "deployment"}}'

curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"action": {"action_type": "check_metrics", "target_service": "database", "metric_name": "cpu", "include_history": true}}'

curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"action": {"action_type": "check_dependencies", "target_service": "checkout-svc", "depth": 2, "include_metrics": true}}'

curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"action": {"action_type": "check_deployments", "target_service": "payment-svc", "include_changelog": true}}'

# Diagnose
curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"action": {"action_type": "diagnose", "target_service": "database", "diagnosis": "database:resource_exhaustion"}}'

# Remediation with required parameters
curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"action": {"action_type": "rollback_deployment", "target_service": "payment-svc", "target_version": "v2.3.9"}}'

curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"action": {"action_type": "scale_up", "target_service": "database", "resource": "connections"}}'

curl -X POST http://localhost:8000/step \
  -H "Content-Type: application/json" \
  -d '{"action": {"action_type": "restart_service", "target_service": "auth-svc", "mode": "graceful"}}'
```

### WebSocket (for multi-step episodes)

HTTP endpoints are stateless. For multi-step episodes, use WebSocket at `/ws`:

```python
from incident_response import IncidentResponseAction, IncidentResponseEnv

async with IncidentResponseEnv(base_url="http://localhost:8000") as env:
    result = await env.reset(task_id="medium", seed=42)
    result = await env.step(IncidentResponseAction(
        action_type="check_logs", target_service="checkout-svc",
        log_level="ERROR", keyword="timeout",
    ))
    result = await env.step(IncidentResponseAction(
        action_type="check_dependencies", target_service="checkout-svc",
        depth=2, include_metrics=True,
    ))
```

### Environment Variables

```bash
export API_BASE_URL="https://router.huggingface.co/v1"
export MODEL_NAME="Qwen/Qwen2.5-72B-Instruct"
export HF_TOKEN="your-token-here"
export EVAL_SEED=42  # seed for procedural generation
```

### Run Inference

```bash
cd incident_response
uv run inference.py
```

## Deploying to Hugging Face Spaces

```bash
cd incident_response
uv run openenv push
```

## Project Structure

```
incident_response/
├── openenv.yaml                    # OpenEnv manifest
├── pyproject.toml                  # Dependencies
├── models.py                       # Pydantic models (Action, Observation, Reward)
├── client.py                       # WebSocket client (with extended ping timeout)
├── __init__.py                     # Package exports
├── inference.py                    # Baseline LLM inference agent
├── validate-submission.sh          # Pre-submission validation script
└── server/
    ├── app.py                      # FastAPI application + custom Gradio builder
    ├── gradio_app.py               # Custom incident response Gradio dashboard
    ├── incident_response_environment.py  # Core environment (step/reset/state)
    ├── service_graph.py            # 7-service topology + cascade BFS
    ├── verifier.py                 # Deterministic [0,1] scoring engine
    ├── Dockerfile                  # Container definition
    └── scenarios/
        ├── base.py                 # Scenario dataclass
        ├── templates.py            # Synthetic data templates + metric thresholds
        ├── generator.py            # Procedural scenario generator
        ├── easy.py                 # Static easy scenario
        ├── medium.py               # Static medium scenario
        └── hard.py                 # Static hard scenario
```

## Evaluation Philosophy

- **Deterministic verification**: All scores computed from ground-truth dicts with zero randomness
- **No LLM-as-judge**: Grading is entirely programmatic
- **Fully reproducible**: Same seed + difficulty + actions = same score, every time
- **All rewards in [0, 1]**: Compatible with standard RL frameworks and hackathon scoring requirements
- **Dense per-step feedback**: Every action receives a reward, not just the terminal step. Productive investigation earns more than wasted repetition.
- **Consequence-aware scoring**: Wrong remediation parameters reflect real-world severity — wrong restart mode on stateful services scores lower than wrong scaling resource
- **Anti-reward-hacking**: Remediation requires investigation-derived parameters (version strings, resource types). Skipping investigation and guessing is capped at 0.15 maximum.
- **Anti-memorization**: Procedural generation produces 80 structurally distinct incident types with per-seed surface variation
