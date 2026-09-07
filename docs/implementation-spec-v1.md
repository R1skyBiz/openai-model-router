# Implementation specification v1

Status: Authoritative staged implementation contract. Phases 0–2 are complete;
[Phase 1 verification](phase-1-report.md) and [Phase 2 verification](phase-2-report.md)
record their exit evidence. Live paths remain disabled. Phase 3 offline execution is implemented; see the
[Phase 3 report](phase-3-report.md) for the explicit evaluator scenario deferral.
Phase 4 offline validation, health and shadow isolation are implemented; see
[Phase 4 report](phase-4-report.md). Phase 5 adds local telemetry analytics and
dashboard views; see [Phase 5 report](phase-5-report.md). Phase 6 has not begun.

## Mission and release boundaries

Optimize Effective Cost per Successful Task under quality, reliability,
capability, latency and budget constraints. The core remains usable as an
embedded library and through HTTP using one engine. Follow
[architecture.md](architecture.md), [routing-policy-v1.md](routing-policy-v1.md),
[configuration.md](configuration.md), and the [Accepted ADRs](decisions/).
Numeric routing policy belongs in config; backend KPI definitions belong in
[telemetry.md](telemetry.md).

This architecture-contract step replaces bootstrap placeholders, populates draft
configuration and records settled decisions. The subsequent dedicated
[evaluation contract](../evals/README.md), recorded in
[ADR 0009](decisions/0009-pre-phase-1-evaluation-contract.md), supplies independent
cases and an offline grader before Phase 1. These steps add no runtime routing, provider,
database, health, dashboard or shadow execution. Budget, recovery, evaluator and
deployment values explicitly marked unresolved must be resolved before the
corresponding enabled execution path is accepted.

## Phase 0 — Bootstrap (complete)

- **Deliverables:** Repository layout, Python packaging and uv lockfile, offline
  import smoke test, JSONL eval scaffolding/validator, config/doc locations,
  ADR slots, .env.example and model-router skill.
- **Explicit non-goals:** Routing logic, typed runtime contracts, provider calls,
  execution, persistence and dashboard.
- **Acceptance criteria:** Package imports on Python 3.12+ without an API key;
  scaffolding is coherent and documents direct later work.
- **Required tests/evals:** Existing pytest smoke test; TOML/YAML parse checks;
  offline JSONL syntax validator; skill validation.
- **Exit criteria:** Approved repository scaffold. Completed; the current
  architecture-contract step is a prerequisite to Phase 1, not runtime work.

## Phase 1 — Deterministic Routing Core

- **Deliverables:** Typed normalized request, classification, decision/rejection,
  failure and snapshot contracts; typed config validation/version loading;
  capability filtering, component aggregation, configured priors/floors/modifiers,
  constraints, effort/validation selection, cost estimates and rationale codes.
  Embedded route entry point consumes supplied classification and mock snapshots.
  Consume the envelope case schema and deterministic graders established in the
  dedicated pre-Phase-1 eval step.
- **Explicit non-goals:** LLM classifier, OpenAI execution, recovery execution,
  SQL persistence, HTTP service implementation, active health probes, semantic
  validators, shadow execution or dashboard.
- **Acceptance criteria:** Same inputs and pinned snapshots produce identical
  output. Classifier data cannot choose the final route. No forbidden framework,
  database, provider SDK or telemetry-transport imports in core. Invalid config
  and impossible hard constraints fail explicitly. Unknown charges never become
  zero. Draft previews expose unresolved execution prerequisites.
- **Required tests/evals:** Config malformed/duplicate keys and references;
  band boundaries and component ranges/sums; model/effort compatibility; family
  floors and documented waivers; budget conflicts; context/cache/output bounds;
  consequence/validation selection; synthetic health filtering; rationale codes;
  deterministic replay and acceptable-envelope fixtures including must-not-use-Astra.
- **Exit criteria:** Deterministic tests and envelope graders pass offline;
  initial policy defaults have documented eval coverage; no later-phase runtime
  dependencies. A full production corpus is required by Phase 6, not this task.

## Phase 2 — Classifier + OpenAI Provider (complete)

- **Deliverables:** Classifier adapter returning family/subclass, scores, flags
  and confidence; versioned classifier configuration; ModelProvider interface,
  OpenAIProvider and scripted MockProvider; normalized response/usage/failures;
  account/model/capability and pricing verification for enabled live paths.
- **Explicit non-goals:** Production execution/recovery loops, autonomous agents,
  persistent task service, active circuit breakers or dashboard.
- **Acceptance criteria:** Classifier never selects final model/effort. OpenAI
  SDK types remain in the adapter. All provider/model calls normalize usage,
  cached/reasoning tokens, timing and failure source without leaking secrets.
  Unknown metadata blocks affected live paths.
- **Required tests/evals:** Mock classifier malformed output and component bounds;
  confidence/provenance; provider contract fixtures, unsupported capability,
  rate limit, timeout, provider outage, response IDs and cache accounting.
  Optional live classifier/provider canaries require explicit opt-in, key and
  budget; they are separate from default tests.
- **Exit criteria:** Mock and adapter contract tests pass; classification evals
  reviewed; live prerequisites verified for any enabled path or clearly left
  disabled. No general execution orchestrator yet.

## Phase 3 — Execution + Escalation

- **Deliverables:** Bounded task orchestrator, budget admission/reservation,
  idempotency, tool interface, distinct quality/infrastructure/tool recovery,
  task/attempt lifecycle, applicable basic V0 acceptance checks and telemetry
  events. Initial persistence/writer and migrations capture every execution.
  Implement route/execute/task HTTP adapters using the shared engine.
- **Explicit non-goals:** General semantic evaluation framework, active health
  canaries/circuit management, sampled shadow execution, dashboard or unbounded
  autonomy. Use injected health snapshots until Phase 4.
- **Acceptance criteria:** Resolve finite attempts/time/cost and backoff values
  before live execution. Confirmed quality failures may increase effort then
  tier; infrastructure/tool failures never automatically increase intelligence.
  Preserve original failure and diagnostic evidence. No silent side-effect
  replay; approvals and remaining budget gate each action. Route-only never
  executes task generation/tools/evaluators. Persist correlated events and
  execution-time prices, with durable retryable delivery.
- **Required tests/evals:** Scripted Terra/medium→Terra/high→Sol/medium; quality
  success after effort increase; infrastructure retries and safe fallback;
  tool timeout without tier jump; unsupported capability, malformed output,
  evaluator-unavailable gate, cancellation, deadline/attempt/budget exhaustion,
  idempotency conflicts, persistence failure and event deduplication.
  Test HTTP/embedded parity and route-only nonexecution.
- **Exit criteria:** Recovery and accounting pass deterministic scenarios;
  storage engine/transaction choices are recorded in an ADR; V0-only execution
  works with mocks, while unavailable stronger validation blocks affected tasks.
  Every execution outcome has recoverable telemetry.

## Phase 4 — Validation + Health + Evals

- **Deliverables:** V0 check framework, V1/V2 evaluator adapters, V3 domain
  bindings, evidence/approval enforcement; component/model/capability health
  snapshots and circuits; liveness/readiness/component HTTP endpoints; offline
  outcome evals; bounded sampled shadow extension with read-only/replayed inputs.
- **Explicit non-goals:** Evaluator calls for every task, automatic policy edits,
  uncontrolled shadow tool effects, universal domain validator, dashboard.
- **Acceptance criteria:** Resolve enabled evaluator/rubric/threshold bindings,
  probe cadence, freshness/circuit limits and shadow budgets in versioned config.
  Keep evaluator failures distinct from generation quality. Degraded safe paths
  continue; unsafe paths fail readiness/admission. Shadow output never reaches
  caller and shadow spend stays separate. Sampling remains off unless configured.
- **Required tests/evals:** Applicable/skipped deterministic checks, independent
  semantic evaluation, unavailable/failed evaluators, domain checks, shadow
  sampling and pair attribution in both cheaper/stronger directions, no side
  effects; stale health, circuit transitions, model/tool/database/writer outages.
  Live paid evals/probes stay opt-in.
- **Exit criteria:** Validation, health and shadow isolation pass deterministic
  tests; component freshness/recovery policies are reviewed; failure taxonomy and
  routing-envelope coverage are expanded toward the release corpus.

## Phase 5 — Telemetry Dashboard

- **Deliverables:** Backend KPI aggregation and planned telemetry HTTP endpoints;
  Overview, Spend, Routing, Efficacy, Health and Task Explorer pages. Filters,
  drilldowns, model/effort flows, cost completeness and policy comparisons.
- **Explicit non-goals:** Frontend-owned KPI definitions, raw prompt/response
  storage by default, distributed observability stack or enterprise analytics.
- **Acceptance criteria:** Task vs attempt denominators follow telemetry.md;
  cost/success includes failed work; infrastructure retry and intelligence
  escalation remain separate. Shadow/preview costs, unknown usage, no-data,
  pending cohorts and stale health are explicit.
- **Required tests/evals:** Fixed-data aggregation reconciliations, zero
  denominators, partial costs, UTC windows, late usage, mixed rubrics, task/attempt
  counts, policy attribution, dashboard endpoint/UI smoke and privacy checks.
- **Exit criteria:** All six pages render backend results correctly; aggregates
  reconcile to immutable attempt/tool charges; task explorer explains decisions
  without exposing raw content or secrets.

## Phase 6 — Integration Hardening

- **Deliverables:** Embedded/HTTP parity, deployment authentication and permission
  boundaries, config activation/rollback, migration/recovery procedures,
  retention decisions, bounded execution under concurrency and release docs.
  Production v1 routing corpus has at least 100 cases.
- **Explicit non-goals:** Cross-provider routing, RL, autonomous policy rewriting,
  unrestricted self-modification, Kubernetes, Kafka, microservices, enterprise
  IAM, premature distributed observability and unbounded agent execution.
- **Acceptance criteria:** All families represented; boundaries, budgets,
  tool/provider failures, long context, escalation and must-not-use-Astra covered.
  Hard constraints pass deterministic graders and envelopes permit legitimate
  alternatives. Both entry modes use one routing engine. Enabled live paths
  have verified prices/access, configured budgets, validation and durable events.
- **Required tests/evals:** Full offline suite and ≥100-case corpus; concurrent
  budget/idempotency, restarts/event replay, auth isolation, secrets/redaction,
  version pinning/rollback, migration recovery, deadline/load smoke; explicitly
  opted-in limited live-provider checks when releasing live integrations.
- **Exit criteria:** No unresolved production-blocking fields for enabled paths;
  release evidence records configuration versions, test/eval results and known
  limitations. Policy changes have human review and immutable activation records.

## Current unresolved decisions and their gates

| Question | Resolve by |
| --- | --- |
| Calibrated success/cost estimator, confidence handling thresholds and latency prediction | Before enabling calibrated selection; keep configured priors explicit meanwhile. |
| Account access, hosted tools, tool/image charges, cache-price composition and nonstandard service tiers | Phase 2, per enabled execution path. |
| Application dollar/time limits, retry/backoff ceilings and cost reservation method | Phase 3 live execution. |
| Database engine, durable event transaction/replay mechanics and idempotency retention | Phase 3 persistence ADR. |
| Evaluator models/rubrics/thresholds, domain validators, health thresholds/cadence and shadow budgets | Phase 4 enabled paths. |
| Deployment auth, metadata/debug retention and release operating thresholds | Phase 6 production gate. |

The approved ladder, objective, taxonomy, score dimensions, failure distinction,
provider boundary, telemetry/privacy principles and non-autonomous policy
governance are settled. Unresolved tuning is not an excuse to hard-code values
or skip a phase gate.
