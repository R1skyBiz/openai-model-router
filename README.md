# OpenAI Model Router

A configuration-driven Python service for choosing an OpenAI model, reasoning
level, validation strategy, and escalation path for each request.

Phase 1 implements a deterministic, embedded route-only core. It consumes
supplied classification and immutable configuration/environment snapshots,
returns an explainable decision or rejection, and performs no network calls.
The objective is Effective Cost per Successful Task; configured candidate order
is the transparent cold-start prior until success estimates are calibrated.
Phase 2 adds a task classifier and a provider adapter for one Responses API call.
Phase 3 adds bounded mock execution, recovery, SQLite evidence and HTTP adapters.
Phase 4 adds independent validation, scoped health and bounded shadow comparison.
Phase 5 adds read-only telemetry analytics and a local React dashboard.
Phase 6 adds versioned activation, per-application authentication, durable SQL
budgets and local release packaging. The shipped release enables route/read/health
only. **RC blocked on live verification.** See [production readiness](docs/production-readiness.md),
[the Phase 6 report](docs/phase-6-report.md), and [deployment](docs/deployment.md).

Start with [implementation phases](docs/implementation-spec-v1.md),
[architecture](docs/architecture.md), [routing policy](docs/routing-policy-v1.md),
and the [configuration reference](docs/configuration.md). Configuration contains
draft v1 data with explicit verification gaps and disabled live execution.

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+ and npm for the optional local dashboard

## Setup

```bash
uv sync --extra dev
```

Copy the environment template only when you need local provider access:

```bash
cp .env.example .env
```

Default tests and all phase eval runners require no OpenAI API key or network.
Install dependencies once; use `uv run --offline` for subsequent verification.

## Local telemetry dashboard

The dashboard reads persisted evidence through typed APIs. Its six pages cover
Overview, Spend, Routing, Efficacy, Health, and Tasks, with UTC filters, policy
comparisons and safe execution timelines. See [metric definitions](docs/phase-5-metrics.md)
and the [API contract](docs/phase-5-interfaces.md).

Generate explicitly synthetic local evidence and start the read-only API:

```bash
uv sync --extra dev
uv run --offline python scripts/generate_sample_data.py
uv run --offline python scripts/serve_demo.py
```

In another terminal:

```bash
cd dashboard
npm ci
npm run dev
```

Open [the local dashboard](http://127.0.0.1:5173). Vite proxies `/v1` to the local
API at port 8000. The API schema is available at
[local API docs](http://127.0.0.1:8000/docs). The demo server exposes telemetry
reads only. No API key is needed, and no provider call runs.

The generator writes `.demo/synthetic-demo.sqlite3` and an integrity manifest.
Every sample is marked synthetic; costs and scores are fabricated examples.
Generation never overwrites an existing database. For a new date window, use
`--output /path/to/new-demo` and serve it with `--data /path/to/new-demo`.
Health freshness ages normally after generation; it is never refreshed by a read.
Generated databases and frontend build artifacts are ignored by Git.

For UI verification, run `npm test`, `npm run typecheck`, and `npm run build`
from `dashboard/`. Backend analytics and API tests run in the ordinary pytest suite.

## Validate the repository

```bash
uv run pytest
uv run python evals/run_local.py
uv run python evals/run_phase1.py
uv run python evals/run_phase2.py
uv run python evals/run_phase3.py
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

## Phase 3 execution

`from model_router.execution import execute, ExecutionDependencies` exposes the
shared synchronous engine. Call `execute(request, dependencies,
supplied_classification=classification)`; omit classification to use an injected
MockClassifier. Dependencies supply a validated bundle, synthetic environment,
MockProvider, finite ExecutionLimits, trusted ExecutionControls, budget authority,
clock, repository, V0 validator and optional deterministic tools. The
[working test composition](tests/phase3_support.py) supplies a complete example.
No default execution composition enables live work.

Initialize local SQLite explicitly with
`model_router.storage.upgrade_database(database_url)`, then construct
`SQLiteTaskRepository(database_url, journal_path=...)`. This runs the Alembic
migration; construction alone does not create tables. Give the journal a durable
local path. `reconcile_pending()` restores retained completion evidence after a
write failure; uncertain started operations are never automatically replayed.
`pending_outbox()` and `ack_outbox(event_id)` support later idempotent delivery.

`model_router.service.create_app(dependencies)` provides `POST /v1/route`,
`POST /v1/execute` and `GET /v1/tasks/{task_id}`. Route requires supplied
classification. POST bodies contain `request` and `classification`; execute may
omit classification and may additionally specify `idempotency_key`. Authorization,
tool scope, snapshots and budgets come from trusted server dependencies. The HTTP
handlers contain no routing or retry policy. This is local composition, without
production deployment authentication.

Successful execute returns output in memory/the immediate HTTP response. Ordinary
serialization, task retrieval, duplicate replay after restart, database rows and
journal entries retain metadata only. A duplicate returns the original task ID and
status without dispatching again; it cannot recover deliberately unretained output.
This describes the original Phase 3 offline composition. Phase 6 adds explicit
release activation and durable cross-process admission; live release validation
is deliberately V0-only. Raw prompt/output retention remains disabled. See the
[current integration contract](docs/integration.md) for supported release behavior.

## Phase 4: validation, health and bounded offline shadows

Phase 4 implements configured V1/V2 independent semantic calls, the V3 domain
boundary, evaluator-only recovery, scoped fresh health/circuits and isolated
shadow comparison. Production and default shadow/live-probe execution remain
disabled by default. See [the report](docs/phase-4-report.md),
[frozen interfaces](docs/phase-4-interfaces.md), and [ADR 0013](docs/decisions/0013-phase-4-verification-health-shadow.md).

Run `uv run --offline pytest`, `uv run --offline python evals/run_phase4.py --combined`,
and `uv run --offline python evals/run_phase4.py --regressions`.
