# Phase 5 integration contract

Frozen before worker delegation. Phase 5 adds read-only local analytics and a
React/TypeScript dashboard. Production execution stays disabled. The baseline
is `3534dca65542b56e94a5273837e78cb5288deaa8`; approved policy/oracle stay unchanged.

## Integration plan and ownership

1. Root freezes these interfaces and dashboard types, owns demo generation,
   integration, docs, review fixes, verification and the single commit/push.
2. Sol High A implements `telemetry/analytics.py` and arithmetic tests.
3. Sol High B implements `telemetry/query.py`, `service/telemetry.py`, the narrow
   app registration hook, API/task timeline tests.
4. Sol High C implements the complete dashboard (shell, shared components and all
   six pages), frontend tests and responsive/theme/accessibility design.
5. A free slot becomes the independent Sol High reviewer after integration.

Shared checkout, disjoint ownership, no worker commits. Three available worker
slots consolidate the six requested workstreams; UI pages share one owner.

## Boundary

`Analytics(tasks, events, *, now, filters, synthetic=False)` consumes tuples of
core TaskResult and ExecutionEvent. It has `summary()`, `spend()`, `routing()`,
`efficacy()`, `policies()`, `models()`, `task_families()` returning JSON-ready
dictionaries matching `dashboard/src/api-types.ts`. Methods own all formulas.
Use decimal strings for monetary values and nullable numeric ratios/latencies.
All response envelopes contain `meta`. Query service reads a consistent SQLite
snapshot of tasks and outbox events; no probes, writes or provider calls.

Analytics filters are a dict: start/end (aware datetime), application/model/effort/
task_family/policy_version/status (optional strings). Default window is preceding
30 UTC days through now. Reject naive or reversed windows. Admission cohort uses
created_at in [start,end). Spend filters charge timestamps in [start,end) over
all eligible tasks, independently of admission time. Model/effort for task KPIs
means initial generation route; spend means actual invoked route. Remaining
filters use task attributes. Blocked tasks are pending/nonterminal for legacy
contract compatibility, separately counted. Cancelled tasks are terminal and
included in denominators. Production metrics exclude synthetic records unless
an explicitly synthetic dataset composition is selected. Demo mode is a separate
marked database, with `meta.synthetic=true` in every response.

Cost objects: amount is null if incomplete; known_subtotal is always a decimal
string; missing_count counts unknown charges; status is known/partial/unavailable.
Empty cohort: monetary amount null and status unavailable (not fabricated zero).
Successful tasks with no incurred charges can have known zero cost. Historical
task totals and actual attempt fees are evidence; never use today's tariffs.
Task totals include all production cost; spend derives charge-level evidence,
including direct validation/tool charges, without double counting evaluator fees.
Timestamp-less fees use correlated outbox events; unplaceable fees are explicitly
reported as unallocated, never silently assigned to the task's completion date.

Summary today/MTD/projection respects non-time filters but uses UTC calendar
windows. Other summary KPIs follow selected admission cohort. Projection is
linear MTD run rate using elapsed seconds in UTC month. Quantiles are nearest
rank. Rates return explicit numerator/denominator and null on zero denominator.
Evaluator groups require identical rubric/check/scale and role; mixed cohort
quality is not comparable. Policy samples under 30 terminal tasks are labeled
insufficient, with no claim of significance (a display guard, not routing policy).

## HTTP and task safety

GET /v1/telemetry/{summary,spend,routing,efficacy,health,models,task-families,policies}
and GET /v1/tasks return typed projections. List uses offset/limit (default 25,
max 100), descending created_at with task_id tie-break. All filters apply.
GET /v1/tasks/{id}?view=timeline returns TaskDetail; existing default metadata
response remains backwards compatible. Timeline pagination uses offset/limit
(default 100, max 500) and total. Events are ordered by timestamp, retaining
SQLite outbox insertion order (`rowid`) on ties. UUID lexical order and global
event-kind ordering do not establish causality. Steps expose safe normalized
facts through explicit allowlists. Fees, usage and latency appear on the owning
completion event; starts do not expose final facts or duplicate charges.
Never serialize arbitrary config/rationale dictionaries or raw prompt/output.
Health uses retained snapshots only, marks expired/future/missing observations
STALE/UNKNOWN, and exposes snapshot times, circuits, outbox counts and observed
failure/latency summaries. Operational readiness is unknown from old evidence;
production readiness remains false. No read launches probes.

`register_telemetry(app, dependencies)` registers telemetry and list endpoints.
`TelemetryQuery(repository, *, now, application_scope, synthetic=False)` composes
analytics and projections. Existing app defaults scope to trusted application;
only explicit local demo app composition permits cross-application inspection.
Unsupported repositories return safe 503. Root demo app can register telemetry
directly without route/execute endpoints. Vite proxies /v1 to localhost:8000.

## Frontend

`api-types.ts` is root-owned. Use backend aggregates only; formatting currency,
ratios and plotting data is permitted, calculating KPIs is not. Six pages:
Overview, Spend, Routing, Efficacy, Health, Tasks. Global UTC date, application,
model, effort, family, policy and status filters. Persist system/light/dark choice.
All pages must handle loading/error/no-data/partial/unknown and synthetic labels.
Accessible chart summaries, tooltips, keyboard focus, reduced motion, responsive
tables and inspectable task timeline. No hard-coded dashboard metric fixtures;
tests can provide typed API fixtures. Charts use restrained colors.
