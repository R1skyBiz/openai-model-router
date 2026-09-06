# Telemetry v1

Status: Accepted conceptual contract; persistence and analytics are phased work.

## Entities and correlation

A task is not a model attempt. Every task has a stable task_id and trace_id.
Identifiers are opaque strings; event_id deduplicates delivery. All timestamps
are UTC instants. Durations use milliseconds; money uses decimal amounts with
currency, source and completeness.

| Entity | Grain, relations and required facts |
| --- | --- |
| tasks | One caller intent: task_id, trace_id, application_id, mode (execute/preview), accepted/started/completed timestamps, lifecycle/outcome, consequence, success-criteria version, initial policy version and final decision ID. |
| routing_decisions | One initial/recovery/preview/shadow decision: decision_id, task_id, predecessor ID, role, full RouteDecision fields, effective configuration hash and health snapshot reference. |
| attempts | One model invocation: attempt_id, task_id, decision_id where applicable, parent attempt ID, purpose, role, sequence, route, usage, cost and failure details below. |
| tool_events | One tool call/recovery: tool_event_id, task_id, parent attempt_id when applicable, tool identity/version, safe operation category, timing, status, normalized failure/cause, idempotency/reconciliation metadata, and charges. |
| evaluations | One check/evaluator result: evaluation_id, task_id, target attempt_id, evaluator attempt_id if model-based, profile, check/rubric/validator version, pass/fail/error/skipped outcome, applicable flag, score/scale, safe evidence references and timing. |
| health_checks | One component/model/capability observation: check_id, state, component, scope, timestamps, freshness, latency, error category, circuit state and recovery metadata. |
| policy_versions | Immutable policy ID, schema version, effective config hash, overlay/version, referenced catalog/budget/validation versions, activation/supersession timestamps and retained content. |
| model_catalog_versions | Immutable alias→provider/tier/capability/context/reasoning/availability snapshot with sources and verification timestamps. |
| pricing_versions | Immutable rate/unit/currency/modifier/tool-charge snapshot with sources, verification/effective timestamps and uncertainty. |

Attempts include generation, classifier, evaluator, and shadow model calls, with
`purpose` (generation/classification/evaluation) separate from
`role` (production/shadow). Classification may occur before a routing decision,
so its decision_id may be null while task/configuration references remain required.
Tools do not masquerade as model attempts. Repeated evaluation must not duplicate
a generation attempt or charge.

Each attempt records model alias, provider model ID and returned model identity
when available, model tier, reasoning effort, requested/started/completed
timestamps, input/output/reasoning token usage, cached-read/cache-write usage,
estimated cost, actual cost, quoted and execution-time pricing references,
catalog version, latency, status, normalized failure type (null only on
non-failure), failure source/stage/cause, provider
response ID where supplied, retry/escalation reason, and parent linkage.
Unavailable provider usage/cost is null with an explicit status, never zero.
Statuses include started, succeeded, failed, cancelled and unknown; an abandoned
in-flight attempt is reconciled, not assumed successful.

## Delivery, accounting and privacy

All executions eventually emit telemetry, including failures, cancellation,
budget refusal after paid classification, and recovery. Route previews emit
decision metadata but no generation/tool/evaluator attempts. Classification cost,
if incurred for a route-only request, is recorded separately from execution KPIs.

Use idempotent event ingestion and a durable pending-event mechanism before
production. Retry delivery by event_id; distinguish occurrence time from ingestion
time. Pause new paid work if its telemetry cannot be durably retained.
A best-effort log line does not meet the delivery contract. The SQLAlchemy/Alembic
boundary and unresolved transaction choices are recorded in
[ADR 0007](decisions/0007-storage-boundary.md).

Preserve both the route's quoted estimate and the pricing snapshot effective
when each attempt executes. Admission-time quotes do not freeze provider prices;
changed tariffs require a new immutable pricing snapshot and budget recheck
before dispatch. Historical costs must never be recomputed with today's prices.
Provider-reported charges or
usage-derived charges at the execution-time rates have explicit cost_source values.
Late usage reconciliations append an attributable correction using the original
pricing version; they do not silently rewrite the audit trail. A missing estimate
does not suppress a subsequently observed charge.

Production task cost includes classification, all generation attempts, retries,
required evaluations and tool charges, each charge counted once. Shadow costs
are separate. External tool charges are owned by tool_events, model calls by
attempts; evaluations reference their evaluator attempts without charging again.
Reasoning tokens already included in provider output usage are not added twice.
Cache read/write buckets must reconcile to total input under the provider adapter's
verified usage schema.

Raw prompt and response storage default OFF in
[validation.yaml](../config/validation.yaml). Normal telemetry contains only
classification/routing metadata, usage, cost, latency, tool metadata, outcome,
evaluation and versions. Do not log raw tool arguments/results, URLs with tokens,
provider error bodies, prompts or responses through generic exception logging.
Secrets must never enter telemetry. Use allowlisted fields and sanitized errors.

Optional future debug capture requires explicit enablement, application policy,
redaction and retention. It is separate from normal events and remains off.
Content retention duration, metadata retention, access controls and deletion
implementation require a deployment decision; no unlimited debug retention is
implied. Validators can use task content in memory without persisting it.

## Backend KPI definitions

The backend owns these definitions and returns metric_definition_version,
window/cohort, filters, denominators, currency, cost completeness, pending counts
and data freshness. The frontend never recalculates success or cost logic.

For task outcome metrics, use execution tasks admitted in the half-open UTC
window [from,to). Exclude route previews, offline fixtures and shadow roles.
Let T be this admitted cohort; C its terminal tasks (succeeded, failed or
cancelled); S its succeeded tasks. Awaiting approval and in-flight tasks remain
pending and are reported separately. Success requires all required validation and
application completion conditions; provider HTTP success alone is insufficient.
Do not silently exclude failed/cancelled tasks or small cohorts.

| KPI | Definition |
| --- | --- |
| Effective Cost per Successful Task (primary) | Total production cost of C, including failed/cancelled tasks and recovery, divided by count(S). |
| First-pass success rate | Tasks in C completed with the initial generation attempt, required checks and no recovery / count(C). |
| Final task success rate | count(S) / count(C); report pending count(T minus C) alongside it. |
| Intelligence escalation rate | Tasks in C with at least one quality-driven effort/tier increase / count(C); break down effort vs tier changes. |
| Infrastructure retry rate | Additional production provider calls caused by TIMEOUT/RATE_LIMIT/PROVIDER_FAILURE / all production provider calls in C; report call purpose. |
| Cost per task | Total production cost of C / count(C), including unsuccessful tasks. |
| Evaluator quality score | Mean valid score for one final applicable evaluation per target attempt and rubric version; show score scale, sample size, coverage, and role. Never mix incompatible rubrics or treat skipped/error as zero. |
| P50/P95 latency | Nearest-rank quantiles of elapsed admission→terminal latency for C, including recovery, validation and approval wait; separately expose active execution latency and per-attempt latency. |
| Tool success rate | Successful production tool call events / terminal production tool call events; retries count as separate events, unresolved calls are reported separately. |
| Model distribution | Initial production generation routes per alias / all initial production generation routes in T; expose attempt-level distribution separately. |
| Reasoning-effort distribution | Initial generation routes per effort / all initial generation routes in T; expose attempt-level distribution separately. |
| Spend by model | Incurred model-call charges grouped by actual invoked alias, including classifier/evaluator purposes; unassigned tool spend is a separate bucket. |
| Spend by task family/application/policy version | Incurred production charges attributed by task family/application and executing policy version; pre-route work uses the task's pinned version. |

Zero denominators return null with a no-data reason, not zero or infinity.
Unknown actual costs make cost aggregates partial: return known subtotal,
missing-cost count and optional separately labeled estimate; do not present a
partial Effective Cost per Successful Task as complete. Estimates never silently
replace actuals. Comparisons state cohort maturity and sampling coverage.

Spend views use charge occurrence time in the requested window, including
in-flight work, rather than terminal-task cohorts. Consequently spend today need
not equal the numerator of a completion KPI. Show production, shadow and
route-preview/classifier spend separately and an explicit all-spend total.

Spend today and MTD use UTC day/month boundaries. Projected monthly spend is
MTD incurred spend / elapsed fraction of UTC month, with forecast_method
`linear_mtd_run_rate`; return null at zero elapsed time and flag partial costs.
This is a run-rate estimate, not a committed budget prediction.

Success by route and effective cost/success group C by initial model/effort and
policy version, attributing all downstream recovery costs to that initial route.
Attempt-level failure views use attempt denominators and explicit labels.
Infrastructure retries, tool recovery and intelligence escalation remain
separate events and rates, even if a task experiences all three.

## Dashboard contract (Phase 5)

| Page | Required views |
| --- | --- |
| Overview | Spend today/MTD/projected, successful tasks, first-pass/final success, effective cost/successful task, intelligence escalation rate and health. |
| Spend | Spend over time and by application, model, task family and reasoning effort, with cost scope and completeness. |
| Routing | Model/effort distributions, configured complexity bands, escalation flow and task-family→model flow. |
| Efficacy | Success by route, effective cost/success, evaluator score/coverage and escalation frequency. |
| Health | Component states, latency, errors, timeouts, rate limits, tool failures and telemetry freshness. |
| Task Explorer | Classification, route, rationale codes/details, attempts, escalations, validation, token/cache usage, costs, latency and all relevant policy/pricing versions. |

Backend aggregations support date, application, model, family, effort, policy,
outcome and role filters where applicable. Include pagination for task detail
collections, small-sample labels and distinct unknown/no-data states.
Shadow comparisons record sampling seed/rate/version, paired production/shadow
attempts and compatible rubrics; they do not inflate production success or hide
shadow expenditure.
