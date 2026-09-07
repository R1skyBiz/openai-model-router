# Production readiness — v0.1.0-rc1 candidate

**RC blocked on live verification.** The shipped manifest is authenticated
route/read/health only. No credentials were available and no paid canaries ran.
A local package is a candidate artifact, not evidence of production certification.

| Area | Status | Evidence and operating boundary |
|---|---|---|
| Routing | READY | Shared deterministic engine; approved policy/oracle unchanged; independent 179-case corpus passes |
| Classification | READY WITH LIMITATION | Offline classifier and admitted live wrapper tested; one invocation; live structured response unverified |
| Provider | READY WITH LIMITATION | Guarded Responses adapter and bounded cost/time/input/output; standard text only; real calls blocked pending evidence |
| Validation | READY WITH LIMITATION | V0 live path only; V1/V2/V3 retained in offline compositions; stronger requirements block |
| Health | READY WITH LIMITATION | Actual DB/outbox/retention preflight; live evidence freshness rechecked per action; no continuous live probing or production circuit certification |
| Shadow | READY WITH LIMITATION | Prior offline behavior and isolated economics preserved; release composition prohibits live shadow |
| Persistence | READY WITH LIMITATION | SQLite and PostgreSQL 18.4 tested; immutable snapshots and journal reconciliation; one shared local journal filesystem required |
| Idempotency | READY WITH LIMITATION | Transactional claims and scoped keys; uncertain starts never replay; task IDs remain globally unique |
| Budgets | READY WITH LIMITATION | Durable application/task allocations and reservations; unknown spend holds funds; allocation reset requires explicit new operator ID |
| Auth | READY | Per-application token digests/scopes; identity injected server-side; scoped reads; health details authenticated |
| Telemetry | READY WITH LIMITATION | Phase 5 denominators and cost completeness preserved; transactional outbox with leasing; external delivery worker not bundled |
| Dashboard | READY WITH LIMITATION | Release visual matrix passes; local synthetic console; authenticated browser deployment requires an operator-owned credential boundary |
| Migrations | READY WITH LIMITATION | SQLite and PostgreSQL migration/restart tests pass; explicit reversible revision; destructive downgrade of operational evidence is not a safe live rollback |
| Backup/recovery | READY WITH LIMITATION | Restart/reconciliation and migration history tests; coordinated operator backups required; reconcile post-backup spend before resuming |
| Live model access | BLOCKED | No account credential or model-access probe; Luna/Terra/Sol/Astra unverified for this account |
| Live pricing | BLOCKED | Official public sources reviewed; no activated account-verified catalog/canary evidence; historic snapshots unchanged |
| Deployment | READY WITH LIMITATION | Locked package/clean-install smoke and CI container build pass; single-process startup; operator TLS and durable volumes required |
| Privacy | READY | Raw content defaults off; normalized task/journal/outbox only; SDK diagnostics suppressed; sanitized auth/service/CLI failures |
| Operating limits | READY WITH LIMITATION | Eight concurrent local mock actions, 1,000-task analytics run; no multi-host journal, large-scale claim or soak-test certification |

## What remains before live verification

Provide an explicitly authorized account credential through the configured
secret environment name. Verify configured model IDs and reasoning support,
public prices and account access; create new immutable active policy/catalog/
budget/validation versions and evidence references. Bind a dedicated canary
application allocation no larger than the aggregate cost cap. Preflight and
activate, then invoke the guarded canary command with explicit paid opt-in.
Retain its normalized result and reconcile any incomplete cost before more calls.

No default command, environment-key presence, CI job, model lookup, dashboard
view or canary result enables or changes routing policy automatically.

## Boundaries that should not be mistaken for implemented services

Retention intervals are operator minimums, not an automatic pruning daemon.
Outbox batch/lease/retry values describe the consumer contract; only claim/ack
and backlog admission are composed here. Live health uses a short-lived immutable
operator observation; circuit/probe configuration is validated but continuous
probe scheduling is not enabled. The application allocation is a hard lifetime
allocation until explicitly replaced, which is stricter than an automatic period
reset. The candidate does not implement enterprise IAM, TLS termination,
automatic tariff refresh, multi-host journal replication or V2 adaptive routing.

See [Phase 6 report](phase-6-report.md), [performance](phase-6-performance.md),
[dashboard inspection](phase-6-dashboard-review.md), [live evidence](phase-6-live-evidence.md),
and [deployment](deployment.md) for commands and evidence.
