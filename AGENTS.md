# OpenAI Model Router agent guidance

This repository is the home of the OpenAI Model Router. It will provide a
configuration-driven routing layer that selects models, reasoning levels, and
validation or escalation behavior for a request.

## Working agreements

- Treat `docs/` as the source of truth for architecture and routing policy.
- Record durable architecture choices as decision records in `docs/decisions/`.
- Keep the routing core application-independent. Put framework and transport
  integration at the package boundaries.
- Keep model IDs, pricing, reasoning levels, budgets, validation rules, and
  routing policy in `config/`, rather than hard-coding them in Python.
- Keep unit and smoke tests deterministic and runnable without
  `OPENAI_API_KEY`. Isolate future live-provider tests and require an explicit
  opt-in for them.
- Use Python 3.12+, `uv`, FastAPI, Pydantic v2, SQLAlchemy/Alembic, and pytest.
- Follow the staged implementation plan in `docs/implementation-spec-v1.md`;
  do not pull later-phase behavior into an earlier phase without documenting
  the decision.
