---
name: model-router
description: Work on this repository's OpenAI Model Router architecture, configuration, routing policy, evaluations, and staged implementation while preserving its application-independent core.
---

# OpenAI Model Router

Read [AGENTS.md](../../AGENTS.md) first. The repository root is two levels above
this skill directory; resolve the links here relative to this file.

Use [implementation phases](../../docs/implementation-spec-v1.md) to establish
the authorized phase and its exit criteria. Architecture-contract work updates
documents/configuration; it does not start Phase 1 runtime implementation.

For routing changes, read [routing policy](../../docs/routing-policy-v1.md) and
[configuration semantics](../../docs/configuration.md). Use
[architecture](../../docs/architecture.md) for core contracts/dependency direction,
[telemetry](../../docs/telemetry.md) for cost and KPI definitions,
[health](../../docs/health-audit.md) for failure readiness, and
[integration](../../docs/integration.md) for library/HTTP boundaries.
Record durable choices in [ADRs](../../docs/decisions/); mark settled decisions
Accepted while identifying unresolved details explicitly.

Optimize Effective Cost per Successful Task. Keep classifier output separate
from final model selection, reasoning effort independent of model tier, and
quality escalation distinct from infrastructure retries and tool recovery.
Consequence can strengthen validation/evidence/approval rather than generation.

Keep model/provider metadata and tunable policy in config. Activated policy,
catalog, pricing and overlay snapshots are immutable. Mark unverified data;
never invent prices, interpret unknown costs as zero, or use current prices for
historical attempts. Applications configure overlays/adapters; core code never
branches on application identity. V1 does not autonomously rewrite policy.

For routing changes, add deterministic acceptable-envelope eval coverage with
hard constraints, including routes that must not use Astra. Respect the current
phase: the dedicated pre-Phase-1 evaluation contract is authorized separately
from architecture-only work and implements no runtime routing or provider calls.
Use [the eval guide](../../evals/README.md) for the independent corpus, schemas,
and offline grader. Never derive expected routes from routing implementation or
candidate tables. Run positive and intentionally invalid fixtures plus the
offline checks; report fixture grading separately from real routing quality.
Live calls remain opt-in.
Preserve task/attempt separation, eventual telemetry, raw-content-off defaults
and secret exclusion.

When this skill changes, validate its frontmatter and links with the available
skill validator. Validate changed YAML/TOML, run pytest and the offline eval
validator, and inspect the diff for duplicated policy values or phase leakage.
Commit/push only within the user's authorized scope.
