# Production readiness — v0.1.0-rc1 candidate

**LIVE-VERIFIED v0.1.0-rc1** as of 2026-09-07. All four requested model/effort
canaries, live Luna classification, and one V0 end-to-end task passed. Total live
spend was **$0.0018026** within the approved $1.00 cap. The shipped manifest remains
authenticated route/read/health only. Nothing was publicly published; this is a
verified release candidate, not production certification.

| Area | Status | Evidence and operating boundary |
|---|---|---|
| Routing | READY | Shared deterministic engine; approved policy/oracle unchanged; independent 179-case corpus passes |
| Classification | READY WITH LIMITATION | Strict live Luna Structured Outputs and provenance passed twice; classifier emits task properties only; broad accuracy remains unmeasured |
| Provider | READY WITH LIMITATION | All four model aliases completed real Responses calls with required efforts and reconciled usage; tiny standard-text scope only |
| Validation | READY WITH LIMITATION | V0 live path only; V1/V2/V3 retained in offline compositions; stronger requirements block |
| Health | READY WITH LIMITATION | Actual DB/outbox/retention preflight; live evidence freshness rechecked per action; no continuous live probing or production circuit certification |
| Shadow | READY WITH LIMITATION | Prior offline behavior and isolated economics preserved; release composition prohibits live shadow |
| Persistence | READY WITH LIMITATION | SQLite and PostgreSQL 18.4 tested; immutable snapshots and journal reconciliation; one shared local journal filesystem required |
| Idempotency | READY WITH LIMITATION | Transactional claims and scoped keys; uncertain starts never replay; task IDs remain globally unique |
| Budgets | READY WITH LIMITATION | Durable application/task allocations and reservations; unknown spend holds funds; allocation reset requires explicit new operator ID |
| Auth | READY | Per-application token digests/scopes; identity injected server-side; scoped reads; health details authenticated |
| Telemetry | READY WITH LIMITATION | Phase 5 denominators and cost completeness preserved; transactional outbox with leasing; external delivery worker not bundled |
| Dashboard | READY WITH LIMITATION | Release visual matrix and isolated live nine-step task timeline pass; authenticated browser deployment still requires an operator-owned credential boundary |
| Migrations | READY WITH LIMITATION | SQLite and PostgreSQL migration/restart tests pass; explicit reversible revision; destructive downgrade of operational evidence is not a safe live rollback |
| Backup/recovery | READY WITH LIMITATION | Restart/reconciliation and migration history tests; coordinated operator backups required; reconcile post-backup spend before resuming |
| Live model access | VERIFIED | Dedicated credential bound to private evidence; Luna none, Terra none, Sol none, Astra low completed; other documented efforts not exhaustively exercised |
| Live pricing | VERIFIED WITH LIMITATION | Official short-context prices reviewed; immutable local activation and 10 usage-accounted calls reconcile to $0.0018026; historical snapshots unchanged |
| Deployment | READY WITH LIMITATION | Locked package/clean-install smoke and CI container build pass; single-process startup; operator TLS and durable volumes required |
| Privacy | READY | Raw content defaults off; normalized task/journal/outbox only; SDK diagnostics suppressed; sanitized auth/service/CLI failures |
| Operating limits | READY WITH LIMITATION | Eight concurrent local mock actions, 1,000-task analytics run; no multi-host journal, large-scale claim or soak-test certification |

## Live verification completed; next operating boundary

[Live evidence](phase-6-live-evidence.md) records exact calls, versions, accounting,
credential binding and residual limits. The existing release runner selected
medium effort for three tier-constrained model checks; three separate existing
provider-test calls verified the required lower efforts without changing policy.
Five persisted tasks reconcile to $0.0009062; four standalone live-eval calls
add $0.0008964. The telemetry surface contains the five pipeline tasks, with no
synthetic data or shadow activity.

The complete offline release gate passed (712 backend and 21 frontend tests,
179/179 combined cases and 22/22 regressions); PostgreSQL passed separately 3/3.
The next milestone is first-application integration and production telemetry,
beginning with LEO. That work has not begun in this task. Production deployment
still requires fresh private account evidence, explicit activation, operator
credentials, durable state and the documented service boundary.

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
