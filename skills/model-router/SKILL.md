---
name: model-router
description: Work on the OpenAI Model Router architecture, configuration, routing policy, evaluations, and implementation while preserving its application-independent core.
---

# OpenAI Model Router

Read `AGENTS.md` first. Use the relevant documents under `docs/` as the source
of truth, and record durable architecture choices in `docs/decisions/`.

Keep routing decisions independent of FastAPI, provider SDKs, persistence, and
telemetry transports. Put model IDs, pricing, reasoning levels, budgets,
validation profiles, and routing rules in `config/` and load them through typed
boundaries.

Keep default tests and evaluations deterministic and offline. Any future live
provider check must be isolated, opt-in, and explicit about its credential and
cost requirements.

Before implementing a phase, verify that its contracts and acceptance criteria
are defined in `docs/implementation-spec-v1.md` and that unresolved policy
choices are documented.
