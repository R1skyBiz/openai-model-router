# OpenAI Model Router

A configuration-driven Python service for choosing an OpenAI model, reasoning
level, validation strategy, and escalation path for each request.

The bootstrap is complete and the v1 architecture contract is documented.
The objective is Effective Cost per Successful Task. Routing and provider
execution have not been implemented; Phase 1 has not started.

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

The bootstrap tests do not need an OpenAI API key.

## Validate the repository

```bash
uv run pytest
uv run python evals/run_local.py
```

The current pytest suite checks the package import; the eval runner validates
JSONL syntax only. The routing-envelope graders and production corpus are future
phase work. Neither command currently proves runtime routing behavior.

## Repository map

- `src/model_router/`: application-independent routing package and future
  boundary modules
- `config/`: model catalog, policy, budget, and validation configuration
- `docs/`: implementation specifications, architecture notes, and decisions
- `evals/`: offline evaluation runner, cases, graders, and ignored results
- `tests/`: unit, integration, and smoke tests
- `migrations/`: future Alembic migrations
- `dashboard/`: future operational dashboard
- `skills/model-router/`: Codex skill instructions for this project
