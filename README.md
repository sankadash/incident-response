# Incident Response — OpenEnv Environment

An [OpenEnv](https://github.com/meta-pytorch/OpenEnv) environment for training and evaluating AI agents on SRE incident triage. Built for the OpenEnv Hackathon.

## What It Does

An AI agent is dropped into a production incident in a 7-service microservice system. It must:

1. **Investigate** — query logs (with level/keyword filters), metrics (with baseline history), dependency trees (with depth control), and deployment changelogs
2. **Diagnose** — identify the root cause service and failure type
3. **Remediate** — apply the correct fix with the correct parameters (rollback to a specific version, scale the right resource, restart with the right mode)

All scoring is deterministic. No LLM-as-judge. Wrong actions carry consequence-based penalties that reflect real-world severity.

## Quick Start

```bash
cd incident_response
uv sync
uv run server                  # start environment at http://localhost:8000
uv run inference.py             # run baseline LLM agent (needs HF_TOKEN)
```

## Architecture

```
incident_response/              # The OpenEnv environment (deployable to HF Spaces)
├── server/
│   ├── app.py                  # FastAPI + custom Gradio dashboard
│   ├── incident_response_environment.py  # Core step/reset/state logic
│   ├── service_graph.py        # 7-service topology + cascade BFS
│   ├── verifier.py             # Deterministic [0,1] scoring engine
│   ├── gradio_app.py           # Custom web dashboard
│   ├── Dockerfile              # Container for HF Spaces
│   └── scenarios/
│       ├── generator.py        # Seed-based procedural scenario generation
│       ├── templates.py        # Log/metric/alert templates for generation
│       ├── easy.py             # Static: payment-svc bad deployment
│       ├── medium.py           # Static: database connection pool exhaustion
│       └── hard.py             # Static: auth-svc intermittent bad deploy
├── models.py                   # Pydantic: Action (12 param fields), Observation, Reward
├── client.py                   # WebSocket client (extended ping timeout)
├── inference.py                # Baseline LLM agent with OpenAI client
├── validate-submission.sh      # Pre-submission checks (HF ping, Docker build, openenv validate)
└── openenv.yaml                # OpenEnv manifest
```

## Key Features

### Parameterized Actions
Every tool requires parameters that mirror real SRE tooling:
- `check_logs payment-svc ERROR deployment` — filtered log queries
- `check_metrics database cpu history` — metric with baseline comparison
- `check_dependencies checkout-svc 2 metrics` — transitive dependency trace
- `rollback_deployment payment-svc v2.3.9` — version from check_deployments
- `scale_up database connections` — resource from check_metrics

Remediation parameters can only be discovered through investigation — no brute-forcing.

### Procedural Generation
80 structurally distinct incident types generated from `(difficulty, seed)`. Same seed = reproducible. Different seed = new task. Prevents rote memorization.

```bash
curl -X POST http://localhost:8000/reset \
  -d '{"task_id": "hard", "seed": 42}'
```

### Dense Reward Signal
Every step returns a reward in [0.0, 1.0]:
- 0.55–0.70: Productive investigation on root cause
- 0.40: Neutral valid action
- 0.10–0.30: Repeated actions (escalating penalty)
- 0.05: Malformed actions
- 0.02–0.10: Wrong remediation

Terminal score via 4-component verifier: diagnosis (40%) + remediation (30%) + efficiency (20%) + safety (10%).

### Difficulty Scaling

| | Easy | Medium | Hard |
|---|---|---|---|
| Root cause | Visibly down | Hidden behind cascade | Appears healthy |
| Evidence | FATAL/ERROR logs | WARN mixed with noise | DEBUG buried in INFO |
| Red herrings | None | 1-2 services | 2-3 with fake deploys |
| Optimal steps | 3 | 5 | 7 |

## Environment Variables

For running inference:

| Variable | Required | Default |
|---|---|---|
| `HF_TOKEN` | Yes | — |
| `API_BASE_URL` | No | `https://router.huggingface.co/v1` |
| `MODEL_NAME` | No | `Qwen/Qwen2.5-72B-Instruct` |
| `IMAGE_NAME` | No | `incident_response-env:latest` (for Docker mode) |
| `ENV_URL` | No | `http://localhost:8000` (for local server mode) |
| `EVAL_SEED` | No | `42` |

## Deployment

### HuggingFace Spaces

```bash
cd incident_response
uv run openenv push
```

### Validation

```bash
cd incident_response
./validate-submission.sh https://your-space.hf.space
```

Checks: HF Space responds to `/reset`, Docker builds, `openenv validate` passes.

## HF Space

Live at: [huggingface.co/spaces/sankadash/incident-response](https://huggingface.co/spaces/sankadash/incident-response)

## License

Built on [OpenEnv](https://github.com/meta-pytorch/OpenEnv) (BSD License).
