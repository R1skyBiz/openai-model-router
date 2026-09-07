# Phase 4 frozen integration contract

The root owns core contracts, config, orchestration, persistence, integration and
final review. Workers own disjoint modules in the shared main checkout; no worker
commits or changes the approved four policy YAMLs or independent oracle.

Production remains disabled. A separate versioned `config/phase4.yaml` supplies
synthetic evaluator bindings, rubric/threshold, invocation/retry bounds and health
limits. The Phase 1 synthetic validation prerequisite is discharged only by real
configured Phase 4 adapters. It does not activate or rewrite approved policy.

ProviderRequest/ProviderEvidence purpose adds `evaluation`; role is separately
recorded on attempts. Each evaluator call has a distinct Attempt (purpose
evaluation), parent generation attempt ID, pinned evaluator/rubric/config evidence,
and ValidationOutcome. V2 invokes the provider independently with task and candidate
content, never accepts a generator self-grade. Provider failures retain source
evaluator in validation evidence; only successful rubric assessment can fail quality.

ValidationService in validation/semantic.py is a single-invocation service:
`plans(decision) -> tuple[EvaluatorBinding, ...]`,
`readiness(decision) -> tuple[str, ...]`,
`evaluate(binding, provider_request) -> (ProviderResult|ProviderFailure, ValidationOutcome)`.
It exposes `config` and `provider`. Root owns all reservations, retries, intent writes,
accounting and health checks. Domain validation is a separate configured registry;
`validate_domain(request, result) -> ValidationOutcome` and `domain_bound`.
V0 remains first and mandatory checks never downgrade. Required evaluation retries
use their own finite counter and never regenerate output on evaluator outage.

HealthService in health/service.py uses injected Clock and HealthConfig; immutable
HealthSnapshot observations contain component/model/capability, freshness, circuit
and sanitized failure evidence. API: `snapshot()`, `observe(component, *, model=None,
capability=None, failure=None, success=False, state=None, required=True)`,
`apply(environment, required_capabilities=())`, `readiness()`, `components()`.
Snapshots and observations are core-owned records. Snapshot reads do not probe.
Circuit half-open probes are explicitly bounded and do not admit general traffic.
Root feeds normalized provider failures, never task quality, into model health.

ShadowService in shadow/service.py owns bounded single comparison execution and
its separate BudgetAuthority. `run(request, production_attempt, *, environment,
controls, before_attempt=None, after_attempt=None) -> ShadowRun` never changes
production output/route/counters. Callback writes persist shadow intent/results.
It reads the bundle's validation.yaml shadow settings (disabled by default),
uses only synthetic MockProvider, and rejects any requested tools or side effects.
Root invokes it after production work succeeds but before terminal persistence.
ShadowRun contains pairing, sampling/version evidence, attempts, outcomes, separate
generation/validation cost, safe status/reason; raw output fields remain excluded.

TaskResult adds evaluator_attempts, domain_validations, health_snapshots,
shadow_runs, production_generation_cost_usd and production_validation_cost_usd.
Existing production total includes evaluation once and excludes all shadow cost.
All evidence is saved transactionally with existing outbox semantics. Evaluator
and shadow intents survive interruption; neither may be blindly replayed on restart.
