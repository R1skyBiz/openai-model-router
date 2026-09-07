# Phase 6 frozen release criteria and ownership

Frozen before delegation on 2026-09-07 against Phase 5 `471128e1504b7e7218d6c1b297d30955824973b3`; initial working tree clean. Root read AGENTS, authoritative architecture/policy/configuration/telemetry/integration/health documents, Accepted ADRs and Phase 1–5 reports and inspected runtime/storage/service/live guards/dashboard/packaging.

## Release criteria

1. Preserve approved four-file policy and independent oracle byte-for-byte. Existing routing remains canonical, all 179 cases and 22 Phase 4 regressions pass.
2. Default live execution OFF regardless of credentials. Explicit versioned activation fails closed on missing operational limits, auth, migrations, immutable references, evaluator/health dependencies or live access/pricing evidence. No public publication.
3. Auth resolves application and route/read/execute/health permissions server-side. Request IDs cannot change tenant scope. Synthetic unauthenticated demo stays loopback-only. Health liveness public; detailed readiness/components protected in authenticated service.
4. SQLAlchemy SQLite and PostgreSQL adapters provide atomic claims, optimistic saves, durable task/application reservations, immutable version snapshots and leased outbox delivery. Unknown paid outcomes hold funds and never replay automatically. Local journal uses cross-process locking and fsync. PostgreSQL tests must actually run or be reported BLOCKED.
5. Safe production composition pins a release/config version. Operational config is separate from unchanged draft policy files; loading does not activate. Health is real dependency evidence, never fabricated live-model availability. Activation does not bypass model API guards.
6. Separate live tooling requires explicit opt-in, external verified config, credentials, aggregate cap, current model/effort/pricing/account evidence; persist safe attempt/cost report and stop on unknown cost. No live invocation in default suites. Missing credentials means RC blocked on live verification.
7. Reproducible package/service/dashboard build, migration/rollback/backup instructions and CI-equivalent offline suite. Test installed wheel outside checkout. Container build must run or be reported BLOCKED.
8. Load baseline: bounded local concurrency 8, 1,000 synthetic tasks for query measurement; route P95 <250ms, retrieval P95 <250ms, telemetry P95 <2s and mock execute >=2 tasks/s as initial release targets, measured without paid provider time. Report actual metrics/memory and failures; no scale claim beyond measured workload.
9. Desktop light/dark, tablet, mobile, task explorer, empty, partial costs, degraded health and long timeline visual verification. Only release-blocking UI fixes.
10. Two independent read-only security/reliability and economics/integrity reviews; resolve material findings centrally. Full backend/frontend/evals/migration/restart/concurrency/privacy/config/package/skill/whitespace gates and truthful readiness table required.

## Shared interface boundaries

- Root owns orchestration/core integration, live canary integration, reports, release criteria, ADR, final verification and git delivery. Workers never commit or change oracle/approved policy.
- A owns `src/model_router/release/` except root-owned runtime/live modules, `config/releases/`, focused `tests/test_phase6_release*`. Expose `load_release(path)`, `preflight(...)`, `activate(...)`; communicate exact schema early. Activation retains canonical immutable manifest and verifies runtime dependencies.
- B owns `src/model_router/service/`, `tests/test_phase6_auth*`; maintain existing create_app(dependencies) offline compatibility. Add `create_authenticated_app(applications=...)` with immutable credential-digest to per-application ExecutionDependencies and scopes; no mutable global/current-app state. Each sub-app query and dependencies permanently scoped. Root release runtime calls this factory.
- C owns `src/model_router/storage/`, `migrations/versions/0003*`, `tests/test_phase6_storage*`, `tests/test_phase6_budget*`. Preserve SQLiteTaskRepository compatibility; add SQLTaskRepository accepting SQLite/PostgreSQL. `SQLBudgetAuthority(repository, application_id, allocation_id, application_ceiling, task_ceiling)` implements existing remaining/reserve/settle port. Allocation never automatically resets. Persist task ownership and reject cross-scope access. Migration helper must work from installed wheel; coordinate packaging with root.
- Later workers own load harness/tests, packaging/CI, docs and live tooling in disjoint files after handoff. Three Sol High slots reused; reviewers independent from implementation.

## Baseline gap matrix

| Area | Baseline | Required closure |
| --- | --- | --- |
| Routing | READY offline | Regression/oracle integrity |
| Classification/provider | BLOCKED live | Explicit guarded integration and canary tooling; no credentials available |
| Validation | READY WITH LIMITATION | Bound synthetic bindings; explicit live evaluator prerequisites |
| Health | READY WITH LIMITATION | Dependency preflight, freshness and honest process-local scope |
| Shadow | READY WITH LIMITATION | Remain disabled in release candidate; separate durable budget if enabled later |
| Persistence/idempotency | BLOCKED production | PostgreSQL adapter, cross-process coordination and restart tests |
| Budgets | BLOCKED production | Durable transactional task/application allocation |
| Auth | BLOCKED | Per-application credentials/scopes and isolation |
| Telemetry | READY WITH LIMITATION | Portable ordering, leased outbox and measured query limits |
| Dashboard | READY WITH LIMITATION | Full release visual matrix |
| Migrations/backup | BLOCKED release | Installed migration resources, roundtrip/restore procedure |
| Deployment | BLOCKED | Locked package/build/CI/start commands |
| Privacy | READY WITH LIMITATION | Auth and production error/log review |
| Live access/pricing | BLOCKED | Public docs checked; account never probed, no key present |
| Operating limits | BLOCKED | Bounded load/failure measurements |

Public model and Responses reference pages were opened on 2026-09-07. Public documentation cannot establish this account's access. Any pricing refresh creates a new snapshot and never rewrites historical records.
