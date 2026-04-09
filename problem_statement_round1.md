# OpenEnv Hackathon — Round 1 Problem Statement

## The Task

Build a complete, real-world OpenEnv environment that an AI agent can learn from through the standard `step()` / `reset()` / `state()` API.

---

## Key Requirements at a Glance

- Must simulate a real-world task (not games or toys)
- Implement full OpenEnv spec:
  - Typed models
  - `step()` / `reset()` / `state()`
  - `openenv.yaml`
- Minimum **3 tasks with agent graders** (easy → medium → hard, scores/reward 0.0–1.0)
- Meaningful reward function with partial progress signals
- Baseline inference script with reproducible scores
- Deploy to Hugging Face Spaces + working Dockerfile
- README with:
  - environment description
  - action/observation spaces
  - setup instructions

---

## Functional Requirements

### Real-world Task Simulation

The environment must simulate a task humans actually do.  
Not games, not toys.

**Examples:**
- Email triage
- Code review
- Data cleaning
- Scheduling
- Customer support
- Content moderation

---

### OpenEnv Spec Compliance

Implement the full OpenEnv interface:

- Typed `Observation`, `Action`, and `Reward` (Pydantic models)
- `step(action)` → returns `(observation, reward, done, info)`
- `reset()` → returns initial observation
- `state()` → returns current state
- `openenv.yaml` with metadata

Must pass:
```bash
openenv validate
````

---

### Minimum 3 Tasks with Agent Graders

Each task must:

* Define a concrete objective
* Include a programmatic grader
* Output score between **0.0–1.0**

Tasks must follow:

* Easy → Medium → Hard progression

Graders must be:

* Deterministic
* Reproducible
* Clearly defined (success/failure criteria)

---

### Meaningful Reward Function

* Provides signal across the full trajectory
* Rewards partial progress
* Penalizes undesirable behavior:

  * infinite loops
  * destructive actions

---

### Baseline Inference Script

* Uses OpenAI API client
* Reads credentials from environment variables:

  * `OPENAI_API_KEY`
* Produces reproducible baseline scores across all tasks

---

## Detailed Requirements

### Non-Functional Requirements

#### Deploys to Hugging Face Space

* Must be containerized HF Space
* Tagged with `openenv`

#### Containerized Execution

* Must include working `Dockerfile`
* Must run via:

```bash
docker build
docker run
```

#### Documentation

README must include:

* Environment description and motivation
* Action and observation space definitions
* Task descriptions with expected difficulty
* Setup and usage instructions
* Baseline scores

---

## Scoring Breakdown

| Parameter                 | Weight | Description                                                |
| ------------------------- | ------ | ---------------------------------------------------------- |
| Real-world utility        | 30%    | Does it model a real task? Useful for training/evaluation? |
| Task & grader quality     | 25%    | Clear objectives, fair grading, meaningful difficulty      |
| Environment design        | 20%    | State design, reward shaping, action/observation quality   |
| Code quality & compliance | 15%    | Spec adherence, structure, Docker works                    |
| Creativity & novelty      | 10%    | Originality, reward design, domain uniqueness              |

---

## Evaluation Details

### Real-world Utility (30%)

* 0–5: Toy/artificial problem
* 6–15: Valid domain but shallow modeling
* 16–25: Useful for agent evaluation
* 26–30: Excellent, fills real gap

---

### Task & Grader Quality (25%)

* 3+ tasks with difficulty range
* Scores in 0.0–1.0 range
* Deterministic and reproducible
* Hard task challenges frontier models

---

### Environment Design (20%)

* `reset()` produces clean state
* Action/observation types well-defined
* Reward provides useful signal (not sparse)
* Proper episode boundaries

---

### Code Quality & Spec Compliance (15%)

* `openenv validate` passes
* `docker build && docker run` works
* HF Space deploys correctly
* Baseline script reproducible

---

### Creativity & Novelty (10%)

* New domain
* Interesting reward design
* Clever mechanics

---

## Evaluation Criteria

### Phase 1: Automated Validation

Pass/Fail:

* HF Space deploys
* OpenEnv spec compliance
* Docker builds
* Baseline reproduces
* 3+ tasks with graders

---

### Phase 2: Agentic Evaluation

* Baseline agent re-run
* Standard Open LLM agent (e.g. Nemotron 3 Super)
* Score variance check

---

### Phase 3: Human Review

Reviewed by Meta + Hugging Face engineers:

* Real-world utility
* Creativity
* Exploit checks

---

## Disqualification Criteria

* Environment does not deploy/respond
* Plagiarized or trivial modifications
* Graders always return same score
* No baseline inference script

---

## Pre-Submission Checklist (All Must Pass)

* HF Space deploys and responds to `reset()`
* OpenEnv spec validated (`openenv.yaml`, typed models, APIs)
* Dockerfile builds successfully
* Baseline script runs and produces scores
* 3+ tasks with valid graders (0.0–1.0 range)

---

## Mandatory Additional Instructions

Environment variables must be defined:

```
API_BASE_URL   # LLM API endpoint
MODEL_NAME     # Model identifier
HF_TOKEN       # Hugging Face / API key
```

---

### Inference Script Requirements

* File must be named: `inference.py`
* Must be placed in root directory
* Must use OpenAI client
* Must follow strict structured logging:

```
[START]
[STEP]
[END]
```

No deviation allowed in:

* field names
* ordering
* formatting

---

## Infra Restrictions

* Max runtime: **< 20 minutes**
* Must run on:

  * vCPU: 2
  * Memory: 8 GB

---

## Validator

Run pre-submission validation script before submitting.

---

## Sample Inference Script (Reference)

```python
"""
Your goal is to maximize total reward by sending meaningful, substantive messages.
Reply with exactly one message string — no quotes, no prefixes, just the message text.
"""
```

### Logging Format

```python
def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)

def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}", flush=True)

def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(f"[END] success={str(success).lower()} steps={steps} score={score:.3f} rewards={rewards_str}", flush=True)
```

---

## Pre-validation Script (Reference)

```bash
#!/usr/bin/env bash

# Docker build check
docker build ...

# OpenEnv validation
openenv validate
```

---

## Submission Timeline

* Submission window opens: **28th March**

