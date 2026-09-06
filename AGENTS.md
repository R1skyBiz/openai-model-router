# OpenAI Model Router agent guidance

This repository defines the OpenAI Model Router: application-independent
infrastructure for selecting the lowest-cost execution path likely to succeed
within quality, reliability, capability, latency, and budget constraints.

## Source-of-truth map

- [Implementation phases](docs/implementation-spec-v1.md): scope and exit gates.
- [Routing policy](docs/routing-policy-v1.md): routing and recovery semantics.
- [Architecture](docs/architecture.md): contracts and dependency boundaries.
- [Decision records](docs/decisions/): durable choices and unresolved details.
- `config/` owns versioned policy values and model/provider metadata;
  [configuration reference](docs/configuration.md) defines their interpretation.

## Non-negotiable rules

- Optimize Effective Cost per Successful Task; raw token cost is secondary.
- Keep the routing core application-independent, with framework, provider SDK,
  database, dashboard, and telemetry transport dependencies at the boundaries.
- Keep model IDs, capabilities, reasoning support, pricing, context limits,
  availability, budgets, and policy values in configuration, never Python tables.
- Model and reasoning effort are independent routing variables. The classifier
  classifies tasks; the policy engine selects the final route.
- Higher consequence may increase validation rather than generation tier.
- Keep quality, infrastructure, and tool failures distinct in recovery and KPIs.
- All executions eventually emit correlated telemetry; raw content defaults off
  and secrets never enter telemetry.
- Every decision references a versioned policy. Activated policies are immutable;
  changes create new versions. V1 never autonomously alters routing policy.
- Routing changes require eval coverage, usually acceptable routing envelopes.
- Keep unit and smoke tests deterministic and runnable without
  `OPENAI_API_KEY`. Isolate future live-provider tests and require an explicit
  opt-in for them.
- Use Python 3.12+, `uv`, FastAPI, Pydantic v2, SQLAlchemy/Alembic, and pytest.
- Follow the staged implementation plan; record phase-boundary changes in an ADR.
  The architecture contract precedes Phase 1 and does not authorize runtime work.
