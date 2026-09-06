# OpenAI Model Router

A configuration-driven Python service for choosing an OpenAI model, reasoning
level, validation strategy, and escalation path for each request.

Phase 1 implements a deterministic, embedded route-only core. It consumes
supplied classification and immutable configuration/environment snapshots,
returns an explainable decision or rejection, and performs no network calls.
The objective is Effective Cost per Successful Task; configured candidate order
is the transparent cold-start prior until success estimates are calibrated.
Phase 2 adds a task classifier and a provider adapter for one Responses API call.
Production execution remains disabled; Phase 3 orchestration has not begun.

Start with [implementation phases](docs/implementation-spec-v1.md),
[architecture](docs/architecture.md), [routing policy](docs/routing-policy-v1.md),
and the [configuration reference](docs/configuration.md). Configuration contains
draft v1 data with explicit verification gaps and disabled live execution.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync --extra dev
```

Copy the environment template only when you need local provider access:

```bash
cp .env.example .env
```

Default tests and both phase eval runners require no OpenAI API key or network.
Install dependencies once; use `uv run --offline` for subsequent verification.

## Validate the repository

```bash
uv run pytest
uv run python evals/run_local.py
uv run python evals/run_phase1.py
uv run python evals/run_phase2.py
```

The pytest suite checks contracts, configuration, routing, dependency boundaries,
the independent grader, and real-router envelope results. The
[pre-Phase-1 evaluation contract](evals/README.md) contains 179 cases, strict
schemas, acceptable envelopes, and passing/invalid hypothetical observations.
`run_local.py` preserves the independent corpus validator/grader.
`run_phase1.py` runs 142 applicable cases through the router and lists every
skipped classification/recovery case. See the [Phase 1 report](docs/phase-1-report.md).
`run_phase2.py` exercises all 19 classification seeds through scripted classifier
outputs and the unchanged independent grader. These are schema/adapter checks,
not measurements of live model accuracy. Recovery scenarios remain Phase 3-only.
See the [Phase 2 completion report](docs/phase-2-report.md) for verification and review.

## Embedded routing

```python
from model_router.core import Classification, EnvironmentSnapshot, Request
from model_router.policy.loader import load_bundle
from model_router.router import route

bundle = load_bundle("config")
request = Request(
    task_id="example", trace_id="example-trace", consequence="low",
    requirements=["text_input", "text_output"],
    context={"input_tokens": 1000, "expected_output_tokens": 100},
)
classification = Classification(
    task_family="extract", provenance="caller-v1", confidence=0.95,
    components={"reasoning_depth": 2, "step_dependency": 2,
                "context_synthesis": 1, "technical_precision": 4,
                "ambiguity": 0, "tool_orchestration": 0,
                "reliability_requirement": 2},
)
snapshot = EnvironmentSnapshot(
    snapshot_id="preview-v1", clock="2026-09-06T20:00:00Z",
    pricing_version="approved-standard-text-2026-09-06",
)
decision = route(request, classification, snapshot, bundle)
```

This draft preview selects a route with `executable=False` and explicit readiness
blockers. It does not execute generation, tools, validation, or recovery. Typed
validation errors identify malformed inputs/configuration; expected policy
impossibility returns `RouteRejection`. Caller limits may only tighten trusted
application bounds. Request content is excluded from normal serialization.

For retained local eval evidence:

```bash
uv run python evals/run_phase1.py --report evals/results/phase1-report.json \
  --results evals/results/phase1-observations.jsonl
uv run python evals/run_local.py --results evals/results/phase1-observations.jsonl --allow-subset
```

## Optional paid provider check

Live access is disabled in both classifier and live-eval configuration. Default
tests remove credentials and block sockets; the marked provider canary is skipped.
To intentionally run it, supply an environment-injected API key and a separate
copy of `config/live-eval.yaml` with current account/price verification, today's
verification date, an explicit positive total dollar cap, and `enabled: true`.
The verification fields are operator attestations, not account probes. The
canary makes one bounded text call and writes safe usage/cost evidence under
`evals/results/`. It does not enable production execution in `budgets.yaml`.

```bash
RUN_LIVE_OPENAI_TESTS=1 OPENAI_LIVE_EVAL_CONFIG=/path/to/reviewed-live-eval.yaml \
  uv run pytest tests/live/test_openai_canary.py
```

The classifier eval runner separately supports an explicitly paid run; see
[the eval guide](evals/README.md). No live model accuracy or account access is
claimed by the offline test results.

## Repository map

- `src/model_router/`: core contracts, strict configuration, deterministic policy
  modules, canonical embedded router, classifier, and single-call provider adapters
- `config/`: model catalog, policy, budget, validation and classifier configuration
- `docs/`: implementation specifications, architecture notes, and decisions
- `evals/`: offline evaluation runner, cases, graders, and ignored results
- `tests/`: unit, integration, and smoke tests
- `migrations/`: future Alembic migrations
- `dashboard/`: future operational dashboard
- `skills/model-router/`: Codex skill instructions for this project
