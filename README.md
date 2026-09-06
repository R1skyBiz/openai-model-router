# OpenAI Model Router

A configuration-driven Python service for choosing an OpenAI model, reasoning
level, validation strategy, and escalation path for each request.

This repository currently contains the project bootstrap only. Routing and
provider execution are intentionally deferred to the implementation phases
documented under `docs/`.

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

## Validate the bootstrap

```bash
uv run pytest
```

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
