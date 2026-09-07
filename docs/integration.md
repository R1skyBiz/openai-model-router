# Integration v1

Status: Embedded route-only API and Phase 2 classifier / single-invocation
provider adapters are implemented. Phase 3 supplies bounded offline execution
and the route/execute/task HTTP adapters. See [Phase 3 report](phase-3-report.md).

## Shared engine and boundaries

Embedded callers and FastAPI call the same routing engine with the same normalized
request and immutable configuration snapshots. The core accepts supplied
classification and health/budget facts; adapters obtain those facts and translate
framework/SDK/database types. See [architecture.md](architecture.md) for
RouteDecision, RouteRejection and ModelProvider contracts.

The embedded routing boundary is
`route(request, classification, environment_snapshot, policy_bundle) -> RouteDecision | RouteRejection`
in `model_router.router`; inputs are the frozen records in `model_router.core`
and a validated bundle from `model_router.policy.loader.load_bundle`.
It performs no network I/O. The execution orchestration boundary is conceptually
`execute(request, adapters) -> TaskResult`; it owns provider calls, recovery,
validation, budget checks and event delivery. Execution signatures and async
conventions remain later-phase design details.

Initial adapters are OpenAIProvider and MockProvider. MockProvider scripts
outputs, usage, failures and timeouts without network or API credentials;
validation execution remains future work. Live-provider tests are isolated and
opt-in. [Phase 2 interfaces](phase-2-interfaces.md) define the synchronous
single-invocation port and classifier wrapper. Framework-specific
conveniences never introduce a second policy engine.

## Minimum HTTP endpoints

| Method/path | Request and response contract |
| --- | --- |
| POST /v1/route | Normalized task request; RouteDecision or RouteRejection. Does not execute task generation, task tools, validators or shadows. |
| POST /v1/execute | Task request with idempotency/authorization controls; TaskResult including task/trace IDs, status, final output if succeeded, final decision and failure/validation references. |
| GET /v1/tasks/{task_id} | Authorized task metadata and linked decisions, attempts, tool events, evaluations and costs; paginated child collections. |
| GET /v1/telemetry/summary | Backend KPI aggregates, time window, filters, denominator counts, cost completeness and freshness. |
| GET /v1/telemetry/models | Model/effort distributions, spend and efficacy aggregates with explicit route/attempt grain. |
| GET /v1/telemetry/task-families | Family aggregates and family→model flow. |
| GET /v1/telemetry/policies | Comparable policy cohorts, pinned versions, costs, success and escalation outcomes. |
| GET /health/live | Process liveness only. |
| GET /health/ready | Enabled-operation readiness and overall state, including safe DEGRADED mode. |
| GET /health/components | Sanitized component/model/capability observations, freshness and circuit state. |

The Phase 1 route function still requires supplied classification. A future
composition layer may use the Phase 2 classifier when no trusted classification
is supplied; the HTTP adapter arrives in Phase 3. Any
paid classification requires explicit routing/classification budget admission.
Its cost is recorded with purpose=classification and task mode=preview; generation,
task tools and evaluators remain forbidden. Supplied classification gives a fully
offline route preview. A route preview is not authorization or a durable budget
reservation for a later execute request.

TaskResult status distinguishes succeeded, failed, cancelled and awaiting_approval;
a failed check is not a successful result. Required validation/evidence must be
complete before returning accepted output. Only production output reaches the
caller; task explorer can expose shadow metadata with an explicit role label.

Successful synchronous operations use 200; missing resources use 404; invalid
input/schema uses 422; conflicting idempotency payload uses 409. Routing
constraint rejections use 422 with a typed envelope; required unavailable
dependencies use 503. Health readiness uses 200/503 for ready/not ready.
A completed execution may return 200 with a failed TaskResult: HTTP transport
success is not task success. Async jobs/streaming and their response semantics
are unresolved and not required by this minimum contract.

Errors carry task_id/trace_id when available, code, normalized failure_type where
applicable, safe message, retryable flag, violated constraints and policy_version.
Provider bodies and secrets must not leak into this envelope.

## Admission and application policy

Resolve a trusted application identity and its configuration overlay outside the
core; callers cannot choose another application's permissions by sending an ID.
Requests may tighten limits and validation but cannot relax authorized bounds.
Keep authentication at the service/application boundary. Concrete deployment
authentication and tenant authorization are Phase 6 decisions; enterprise IAM
is a v1 non-goal.

Pin policy, catalog, validation, budget and overlay versions at admission, and
record the initial pricing quote. Before every paid invocation, capture the
tariff effective for that invocation and recheck estimated cost, deadline,
remaining budget, live health and required approval evidence. Retain changed
price quotes as new decision/accounting facts without modifying the task's
policy. A previously returned decision is not proof the model is still healthy
or the caller can still afford execution.

An idempotency key is scoped by trusted application identity and a normalized
request digest. An identical retry returns the existing task/result; a different
payload with that key is rejected. Retention and atomic storage mechanics are
unresolved until execution/storage phases. Tool side effects require their own
idempotency/reconciliation strategy; retries must not duplicate external actions.

Applications provide tool/evidence/approval/domain-validator adapters or
configuration, never `if application == ...` branches in the routing core.
HTTP and embedded behavior must remain equivalent given the same snapshots.

## Local and release conventions

Use Python 3.12+, uv, Pydantic v2, FastAPI and SQLAlchemy/Alembic at their stated
boundaries. Keep credentials in environment/secret injection, never config,
request telemetry or committed fixtures. The existing .env.example remains the
local convention; no key is required for default tests through Phase 2.

Backend analytics implement [telemetry.md](telemetry.md); the dashboard renders
returned definitions and denominators. Integration hardening verifies version
rollout/rollback, persistence recovery, privacy, permission boundaries, budget
concurrency, compatibility and the production eval gate.

## Phase 3 concrete API

`model_router.execution.execute(request, dependencies, *, supplied_classification=None)`
returns the normalized TaskResult. `ExecutionDependencies` is explicit and contains
no hidden global composition. The frozen contract and state transitions are in
[Phase 3 interfaces](phase-3-interfaces.md). `service.create_app(dependencies)` is
a thin synchronous FastAPI adapter. Route-only currently requires supplied
classification; it never invokes a classifier/provider/tool/validator.

All execute inputs are normalized Request records (task/trace IDs required).
The HTTP envelope has `request`, optional `classification` for execution, and
optional `idempotency_key`; callers cannot replace trusted execution controls.
Task retrieval is metadata-only. Application authentication remains a deployment
gate; this local service must not be exposed as an authenticated production API.

## Phase 4 verification composition

`ExecutionDependencies` optionally receives `semantic: ValidationService`,
`health: HealthService`, and `shadow: ShadowService`. V0 remains the default.
The orchestrator gates the required validation profile, reserves and persists
every evaluator invocation, retries evaluator infrastructure without generation,
and isolates optional shadow output and spend. Health snapshots are consumed by
the existing route engine and retained in the task transaction. Required checks
never silently downgrade. Production execution remains disabled.

`GET /health/live` is process-only. `/health/ready` checks shared operation
readiness and returns 200 or 503. `/health/components` exposes sanitized scoped
snapshot observations. None launches a provider call. Supplying no health service
reports execution readiness unavailable. Route previews still execute no evaluator,
provider, tool or shadow work. Task metadata includes evaluator and shadow evidence
but never their raw output; only production output is in the immediate execute
response. See [ADR 0013](decisions/0013-phase-4-verification-health-shadow.md).
