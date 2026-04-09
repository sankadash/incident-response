# Incident Response Environment — Implementation Spec

## For: Coding Agent implementing the OpenEnv environment

---

## 0. How to Read This Spec

This spec is the single source of truth for the `incident_response` OpenEnv environment. It describes the implemented system — models, actions, scoring, generation, and episode flow.

### Key Files

- `./incident_response/server/app.py` — FastAPI server + custom Gradio UI
- `./incident_response/server/incident_response_environment.py` — core environment class
- `./incident_response/server/gradio_app.py` — custom Gradio dashboard
- `./incident_response/models.py` — Pydantic models (Action, Observation, Reward)
- `./incident_response/client.py` — WebSocket client wrapper (custom ping timeout)
- `./incident_response/openenv.yaml` — metadata file
- `./incident_response/server/Dockerfile` — container definition
- `./incident_response/server/service_graph.py` — topology + cascade logic
- `./incident_response/server/verifier.py` — deterministic scoring [0, 1]
- `./incident_response/server/scenarios/` — static + procedural scenario generation
- `./incident_response/inference.py` — baseline LLM agent

---

## 1. What We Built

**Environment Name:** `incident_response`
**Domain:** Site Reliability Engineering — On-Call Incident Triage

An AI agent receives a production alert about a failing microservice system. It investigates by querying logs (with level/keyword filters), metrics (with history comparison), and dependencies (with transitive depth). It then diagnoses the root cause and takes a parameterized remediation action. Scoring is deterministic, consequence-based, and uses the [0.0, 1.0] range.

---

## 2. The Service Graph

### 2.1 Topology (7 microservices)

```
                    frontend
                       |
                  api-gateway
                 /     |      \
          auth-svc  checkout-svc  inventory-svc
                    |                |
                 payment-svc      database
```

**Dependency graph** (service -> downstream dependencies):
```python
{
    "frontend": ["api-gateway"],
    "api-gateway": ["auth-svc", "checkout-svc", "inventory-svc"],
    "auth-svc": [],
    "checkout-svc": ["payment-svc"],
    "inventory-svc": ["database"],
    "payment-svc": [],
    "database": [],
}
```

### 2.2 Service State Schema

Each service at runtime:
```python
{
    "name": str,
    "status": "healthy" | "degraded" | "down",
    "metrics": {
        "latency_p99_ms": float,
        "error_rate_pct": float,
        "cpu_pct": float,
        "memory_pct": float,
        "requests_per_min": float,
    },
    "recent_logs": [
        {"timestamp": str, "level": str, "message": str},
        ...  # 15 entries at multiple levels (INFO, DEBUG, WARN)
    ],
    "dependencies": [str, ...],
    "recent_deployments": [
        {"version": str, "timestamp": str, "status": str, "changelog": str},
    ],
}
```

### 2.3 Cascade Rules

Failures propagate upstream through the reverse dependency graph via BFS:
1. **Root cause** set to "down" or "degraded" by scenario
2. **Level 1 dependents** become "degraded" with spiked latency/errors
3. **Level 2+ dependents** get mildly elevated latency

Difficulty modulates cascade behavior:
- **Easy**: cascade logs explicitly name the root cause service
- **Medium**: cascade logs name root cause but buried among noise
- **Hard**: cascade logs are ambiguous ("downstream dependency", not naming root)

---

## 3. Pydantic Models

### 3.1 Action (IncidentResponseAction)

```python
class IncidentResponseAction(Action):
    action_type: str                           # one of 9 valid types
    target_service: Optional[str] = None       # required for all except escalate

    # Diagnosis
    diagnosis: Optional[str] = None            # "service:cause_type" for diagnose

    # Investigation parameters
    log_level: Optional[str] = None            # ALL, FATAL, ERROR, WARN, INFO, DEBUG
    keyword: Optional[str] = None              # substring filter for check_logs
    tail: Optional[int] = None                 # entries to return (default 10, max 50)
    metric_name: Optional[str] = None          # latency, error_rate, cpu, memory, rpm, all
    include_history: Optional[bool] = None     # baseline comparison for check_metrics
    depth: Optional[int] = None                # 1 (direct) or 2 (transitive) for check_dependencies
    include_metrics: Optional[bool] = None     # health data per dependency
    include_changelog: Optional[bool] = None   # version diffs for check_deployments

    # Remediation parameters (REQUIRED for their action types)
    target_version: Optional[str] = None       # REQUIRED for rollback_deployment
    resource: Optional[str] = None             # REQUIRED for scale_up (cpu/memory/connections/replicas)
    mode: Optional[str] = None                 # REQUIRED for restart_service (graceful/force)

    # Escalate
    severity: Optional[str] = None             # low/medium/high/critical
    reason: Optional[str] = None               # brief note
```

### 3.2 Observation (IncidentResponseObservation)

```python
class IncidentResponseObservation(Observation):
    alert: Optional[str] = None                # present only on first observation after reset()
    service_statuses: List[ServiceStatus]       # all 7 services
    last_query_result: Optional[QueryResult]    # result of last action
    step_number: int
    max_steps: int
    available_actions: List[str]
    # Inherited: done (bool), reward (float), metadata (dict)
```

### 3.3 Reward

```python
class Reward(BaseModel):
    total: float              # 0.0 to 1.0
    diagnosis_score: float    # 0.0 to 1.0
    remediation_score: float  # 0.0 to 1.0
    efficiency_score: float   # 0.0 to 1.0
    safety_score: float       # 0.0 to 1.0
```

---

## 4. Action Space — Full Reference

### 4.1 Investigation Actions

| Action Type | Parameters | Returns in QueryResult.data |
|---|---|---|
| `check_logs` | `target_service` (required), `log_level` (default ALL), `keyword` (optional), `tail` (default 10, max 50) | Filtered log entries matching level + keyword |
| `check_metrics` | `target_service` (required), `metric_name` (default all), `include_history` (optional) | Metric data with thresholds/status; if history: current vs baseline with delta |
| `check_dependencies` | `target_service` (required), `depth` (default 1, max 2), `include_metrics` (optional) | Dependency list with status; depth=2 includes transitive; metrics adds latency/error_rate/cpu |
| `check_deployments` | `target_service` (required), `include_changelog` (optional) | Deployment history; changelog shows what changed between versions |

### 4.2 Diagnosis Action

| Action Type | Parameters | Effect |
|---|---|---|
| `diagnose` | `target_service` + `diagnosis` = `"<service>:<cause>"` | Records the agent's diagnosis. Can be called multiple times; only the last one counts. |

Valid cause types: `bad_deployment`, `resource_exhaustion`, `dependency_failure`, `configuration_error`, `traffic_spike`

### 4.3 Remediation Actions (require specific parameters)

| Action Type | Required Parameters | Validation |
|---|---|---|
| `rollback_deployment` | `target_service`, `target_version` (must match previous stable version from check_deployments) | Missing version: reward=0.05. Wrong version: symptoms return, reward=0.10. |
| `scale_up` | `target_service`, `resource` (cpu/memory/connections/replicas — must match bottleneck from check_metrics) | Missing resource: reward=0.05. Wrong resource: symptoms return, reward=0.10. |
| `restart_service` | `target_service`, `mode` (graceful for config_error, force for dependency_failure) | Missing mode: reward=0.05. Wrong mode: episode ends with heavy verifier penalty. |
| `escalate` | `severity` (low/medium/high/critical) | Ends episode. Remediation score = 0.5. |

### 4.4 Cause-to-Remediation Mapping

| Cause Type | Correct Remediation | Required Parameter |
|---|---|---|
| `bad_deployment` | `rollback_deployment` | `target_version` (previous stable version) |
| `resource_exhaustion` | `scale_up` | `resource` (exhausted resource) |
| `traffic_spike` | `scale_up` | `resource` (typically `replicas` or `cpu`) |
| `dependency_failure` | `restart_service` | `mode=force` |
| `configuration_error` | `restart_service` | `mode=graceful` |

### 4.5 Cause-to-Resource Mapping (for scale_up)

| Cause | Service | Correct Resource |
|---|---|---|
| resource_exhaustion | database | connections |
| resource_exhaustion | payment-svc | connections |
| resource_exhaustion | frontend | memory |
| resource_exhaustion | api-gateway | cpu |
| resource_exhaustion | auth-svc, checkout-svc, inventory-svc | memory |
| traffic_spike | database | connections |
| traffic_spike | all others | replicas |

### 4.6 Terminal Conditions

1. Correct remediation with correct parameters -> `done=True`, full score computed
2. `restart_service` with correct target but wrong mode -> `done=True`, heavy param penalty
3. `escalate` -> `done=True`, remediation_score=0.5
4. `step_number >= max_steps` -> `done=True`, score computed with whatever was recorded
5. Wrong remediation (wrong target, wrong action, wrong version/resource) -> symptoms return next step, `done=False`

---

## 5. Reward System

**All rewards and scores are in [0.0, 1.0].** No negative values anywhere.

### 5.1 Per-Step Rewards (immediate feedback)

Every step returns a reward signal in the observation. This provides per-step training signal.

**Reward tiers:**

| Tier | Reward | Description |
|---|---|---|
| Productive investigation (root cause) | **0.55 - 0.70** | base_reward (0.40) + investigation bonus (up to 0.20), capped at 0.70 |
| Productive investigation (related) | **0.40 - 0.55** | base_reward (0.40) + smaller bonus |
| Neutral investigation (unrelated) | **0.40** | base_reward only |
| Repeated action (1st repeat) | **0.30** | Diminishing: 0.30, 0.25, 0.20, 0.15, 0.10 (floor) |
| Correct diagnosis | **0.70** | Exact match |
| Partial diagnosis (right service) | **0.50** | Right service, wrong cause |
| Wrong diagnosis | **0.15** | Wrong but agent tried |
| Malformed action / missing param | **0.05** | Invalid type, missing target, unknown service |
| Wrong remediation (wrong params) | **0.10** | Wrong version/resource, symptoms return |
| Wrong action type on right target | **0.08** | Potentially dangerous |
| Wrong target remediation | **0.02** | Disrupting healthy service |

**Investigation bonus breakdown** (additive, capped at 0.20):

| Condition | Bonus |
|---|---|
| Investigating root cause service | +0.10 |
| Investigating service on dependency path | +0.05 |
| Investigating degraded service | +0.02 |
| Investigating down service | +0.03 |
| First time checking this service | +0.02 |
| Using depth=2 on check_dependencies | +0.02 |
| Using include_history on check_metrics | +0.02 |
| Using include_changelog on check_deployments | +0.02 |
| Checking logs of root cause with matching level | +0.02 |

**Repeat penalty (escalating, parameter-aware):**

Repeats are detected by full action signature: `(action_type, target_service, log_level, keyword, diagnosis, target_version, resource, mode)`. Same type + target but different parameters = NOT a repeat.

| Repeat Count | Base Reward |
|---|---|
| 0 (first time) | 0.40 |
| 1 | 0.30 |
| 2 | 0.25 |
| 3 | 0.20 |
| 4 | 0.15 |
| 5+ | 0.10 (floor) |

**Premature remediation:** If the agent attempts a remediation action before any `diagnose` action, base_reward is capped at 0.15.

**Lucky guess cap:** If the agent gets the correct remediation without ever calling `diagnose`, the terminal reward is capped at `min(score * 0.25, 0.15)`.

### 5.2 Final Episode Score (verifier)

Computed when `done=True`. All component scores in **[0.0, 1.0]**.

```
total = 0.40 * diagnosis + 0.30 * remediation + 0.20 * efficiency + 0.10 * safety
```

**Diagnosis Score (40% weight):**

| Condition | Score |
|---|---|
| Exact match (service:cause_type) | 1.0 |
| Right service, wrong cause | 0.6 |
| Wrong diagnosis | 0.25 |
| No diagnosis made | 0.0 |

**Remediation Score (30% weight):**

| Condition | Score |
|---|---|
| Correct action + target + correct params | 1.0 |
| Escalated (gave up) | 0.5 |
| Correct action + target + wrong scale resource | 0.3 |
| Correct action + target + wrong rollback version | 0.2 |
| Right target + wrong action type | 0.15 |
| Correct action + target + wrong restart mode | 0.1 |
| Wrong target | 0.0 |

**Efficiency Score (20% weight):**

| Condition | Score |
|---|---|
| steps_taken <= optimal | 1.0 |
| steps_taken >= max_steps | 0.0 |
| Between | Linear: `max(0.0, 1.0 - (steps_taken - optimal) / (max_steps - optimal))` |

**Safety Score (10% weight):**

| Premature Destructive Actions | Score |
|---|---|
| 0 | 1.0 |
| 1 | 0.75 |
| 2 | 0.50 |
| 3 | 0.25 |
| 4+ | 0.0 |

### 5.3 Score Examples

| Agent Behavior | Diag | Rem | Eff | Safety | **Total** |
|---|---|---|---|---|---|
| Perfect run (3 steps, all correct) | 1.0 | 1.0 | 1.0 | 1.0 | **1.00** |
| Right service wrong cause, correct fix | 0.6 | 1.0 | 0.8 | 1.0 | **0.90** |
| Wrong diagnosis, correct fix | 0.25 | 1.0 | 0.5 | 1.0 | **0.60** |
| Lucky guess (no diagnosis, correct fix) | 0.0 | 1.0 | 1.0 | 1.0 | **capped 0.15** |
| Escalate immediately | 0.0 | 0.5 | 1.0 | 1.0 | **0.45** |
| Max steps, no action taken | 0.0 | 0.0 | 0.0 | 1.0 | **0.10** |
| Wrong target, max steps | 0.0 | 0.0 | 0.0 | 0.0 | **0.00** |

---

## 6. Procedural Scenario Generation

### 6.1 Architecture

```
(difficulty, seed) -> ScenarioGenerator -> Scenario(task_id, name, alert_text, ground_truth, setup_fn)
```

`random.Random(seed)` drives all decisions. Same seed = identical scenario.

### 6.2 Generation Space

80 structurally distinct incident types. Seeds vary surface details.

| Difficulty | Services | Causes | Structural Variants |
|---|---|---|---|
| Easy | 5 | 2 (bad_deployment, resource_exhaustion) | **10** |
| Medium | 7 | 5 (all) | **35** |
| Hard | 7 | 5 (all) | **35** |

### 6.3 Difficulty Modulation

| Aspect | Easy | Medium | Hard |
|---|---|---|---|
| Root cause status | down/degraded | healthy/degraded | always healthy |
| Root cause log levels | FATAL, ERROR | WARN, ERROR | DEBUG (1-2 entries) |
| Root cause log count | 4-6 | 4-6 | 1-2 |
| Noise log count | 5-8 | 6-10 | 12-15 |
| Cascade names root | yes | yes (but noisy) | no (ambiguous) |
| Red herring count | 0 | 1-2 | 2-3 |
| Upstream metric multiplier | 0.7x root | 1.5x root | 3.0x root |
| Optimal / max steps | 3 / 15 | 5 / 20 | 7 / 25 |

### 6.4 Ground Truth Dict

```python
{
    "root_cause_service": str,          # which service failed
    "root_cause_type": str,             # why it failed
    "correct_remediation": str,         # action_type to fix it
    "correct_target": str,              # service to apply fix to
    "correct_target_version": str|None, # for rollback_deployment
    "correct_resource": str|None,       # for scale_up
    "correct_restart_mode": str|None,   # for restart_service
    "optimal_steps": int,
    "max_steps": int,
}
```

### 6.5 Static Scenarios (backward compatible)

When `seed=None`, three curated static scenarios are used:

**Easy** — "The Obvious Crash": payment-svc bad deployment, rollback to v2.3.9
**Medium** — "The Cascading Slowdown": database connection pool exhaustion, scale_up connections
**Hard** — "The Intermittent Poisoned Deploy": auth-svc bad deployment, rollback to v1.7.3

---

## 7. Episode State Machine

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
   EPISODE END --> verifier scores [0.0 to 1.0]
```

**reset()** accepts `task_id` (easy/medium/hard) and optional `seed` via kwargs.
**step()** returns per-step reward [0.0, 1.0] + terminal verifier score on done.

---

## 8. File Structure

```
incident_response/
├── __init__.py
├── client.py                              # WebSocket client (ping_timeout=300s)
├── inference.py                           # Baseline LLM agent
├── models.py                              # Action (15 fields), Observation, Reward
├── openenv.yaml                           # Metadata + 3 task definitions
├── pyproject.toml                         # Dependencies
├── README.md                              # Full documentation
├── outputs/                               # Output directory
└── server/
    ├── __init__.py
    ├── app.py                             # FastAPI server + custom Gradio UI
    ├── gradio_app.py                      # Custom incident response dashboard
    ├── Dockerfile                         # Container definition
    ├── incident_response_environment.py   # Core environment (step/reset/state)
    ├── service_graph.py                   # 7-service topology + cascade BFS
    ├── verifier.py                        # [0,1] consequence-based scoring
    └── scenarios/
        ├── __init__.py                    # get_scenario(task_id, seed) dispatch
        ├── base.py                        # Scenario dataclass
        ├── templates.py                   # Log templates, metric profiles, configs
        ├── generator.py                   # ScenarioGenerator(difficulty, seed)
        ├── easy.py                        # Static: payment-svc bad_deployment
        ├── medium.py                      # Static: database resource_exhaustion
        └── hard.py                        # Static: auth-svc bad_deployment
```

---

## 9. Inference Script

**File:** `./incident_response/inference.py`

### 9.1 Environment Variables

```bash
API_BASE_URL    # LLM API endpoint (default: https://router.huggingface.co/v1)
MODEL_NAME      # Model identifier (default: Qwen/Qwen2.5-72B-Instruct)
HF_TOKEN        # API key
EVAL_SEED       # Seed for procedural generation (default: 42)
ENV_URL         # Server URL for local mode (default: http://localhost:8000)
IMAGE_NAME      # Docker image name (if using from_docker_image)
```

### 9.2 Structured Logging

```
[START] task=<task>_seed<seed> env=incident_response model=<model>
[STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
[END]   success=<true|false> steps=<n> score=<0.000> rewards=<r1,r2,...,rn>
```

Score is the final terminal reward (verifier score), clamped to [0.0, 1.0].

### 9.3 Expected Baseline Scores

| Task | Expected Score | Typical Steps |
|---|---|---|
| Easy | 0.85 - 1.0 | 3 - 5 |
| Medium | 0.55 - 0.75 | 6 - 10 |
| Hard | 0.30 - 0.55 | 8 - 15 |

---

## 10. Metric Thresholds

Used by `check_metrics` with specific `metric_name` to assess status:

| Metric | Warning | Critical | Unit |
|---|---|---|---|
| latency_p99_ms | 200 | 1000 | ms |
| error_rate_pct | 5 | 20 | % |
| cpu_pct | 70 | 90 | % |
| memory_pct | 75 | 90 | % |
| requests_per_min | <100 (low) | — | req/min |

---

## 11. Web Interface

**File:** `./incident_response/server/gradio_app.py`

Custom Gradio dashboard at `/web` (enabled via `ENABLE_WEB_INTERFACE=true`). Passed to `create_app()` via the `gradio_builder` parameter.

### Features:
- **Alert Banner** — colored alert text on episode reset
- **Service Status Grid** — 7 services with emoji indicators (🟢🟡🔴), latency, error rate
- **Parameterized Action Form** — action type dropdown with conditional parameter fields
- **Investigation Results** — formatted by query type (logs with level colors, metrics with thresholds, deps as tree, deployments with changelogs)
- **Episode History** — table of all actions with per-step rewards
- **Cumulative Reward Chart** — line plot tracking total reward over time
- **Task/Seed Selection** — difficulty dropdown + seed input for procedural generation

---

## 12. Client

**File:** `./incident_response/client.py`

WebSocket client extending `EnvClient` with:
- Custom `_connect()` override: `ping_timeout=300`, `ping_interval=60` (handles slow LLM calls)
- `_step_payload()` uses `action.model_dump(exclude_none=True, exclude={"metadata"})` for all fields
- `_parse_result()` reconstructs nested `ServiceStatus` and `QueryResult` objects

---

## 13. Infrastructure Constraints

| Constraint | Budget |
|---|---|
| vcpu=2, memory=8GB | All in-memory dicts (~few KB) |
| Runtime < 20 min | Max 60 total steps across 3 tasks |
| Docker build | Template Dockerfile, no exotic deps |
| HF Space responds to reset() | FastAPI starts in < 5 seconds |

---

## 14. Validation

```bash
# From project root
cd incident_response && openenv validate && cd ..
bash pre_validation.sh <hf_space_url>
```

### Pre-Submission Checklist

- [ ] `openenv validate` passes
- [ ] HF Space deploys and responds to `reset()`
- [ ] Dockerfile builds successfully
- [ ] `inference.py` runs and produces [START]/[STEP]/[END] output
- [ ] 3 tasks with valid graders (score range [0.0, 1.0])
- [ ] Procedural generation: same seed = identical scenario
- [ ] Per-step rewards: positive for productive investigation, low for bad actions
- [ ] Remediation requires parameters from investigation (version, resource, mode)
- [ ] All rewards and scores in [0.0, 1.0] — no negative values
