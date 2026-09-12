# Phase 6 — Integration hardening and release candidate

**LIVE-VERIFIED v0.1.0-rc1.** Candidate version: `v0.1.0-rc1`
(Python package `0.1.0rc1`). This is local preparation only; no public package,
GitHub release, or adaptive-routing work is authorized or performed.

The shipped `config/releases/route-only-v1.yaml` supports authenticated route,
read and health operations. Execution is off. The separate live composition is
covered by offline admission/integration tests and now verified against a dedicated
OpenAI credential with tiny standard-text V0 canaries. Production readiness is enumerated in [the readiness table](production-readiness.md).

## Multi-agent work and integration

Root architect/integrator used Astra; workers and independent reviewers used Sol
High as requested. Root inspected the clean Phase 5 baseline
`547bcea6be4e6bc4f285a2cc3db61ce15a092ee5`, authoritative docs and production gates,
then froze [the gap matrix/interfaces](phase-6-interfaces.md) and
[ADR 0015](decisions/0015-phase-6-release-boundary.md) before delegation.

| Owner | Scope |
|---|---|
| Activation worker | Strict versioned release schema, loader, preflight, immutable activation receipt, CLI and focused tests |
| Auth worker | Server-derived identity, bearer digests/scopes, isolated HTTP apps; subsequently package/build/CI/deployment |
| Storage worker | SQLite/PostgreSQL task/idempotency/outbox coordination, durable allocation/reservations, migration/restart tests |
| Root | Live admission/classifier integration, runtime composition, capped canary tooling, load harness, dashboard audit, public contract and release reports |
| Independent security reviewer | Read-only auth, isolation, persistence, restart, secrets, live opt-in and readiness review |
| Independent economics reviewer | Read-only cost integrity, budgets, live quotes, immutable history and oracle review |

Workers shared the tree with file ownership boundaries. Root resolved integration
changes centrally; no merge conflict required discarding work. Two worker commands
stalled at approval boundaries; workers were recovered and checks resumed. The
browser's first navigation also stalled; visual checks subsequently completed with
stable viewport captures.

## Production configuration and security

`model-router inspect/preflight/activate/serve` separates loading from activation.
Preflight validates every referenced hash/version, finite policy/operational
limits, evaluator scope, database migration/connectivity, outbox/retention, auth,
health freshness and live account/pricing evidence. Activation fsyncs an exclusive
immutable receipt. Startup verifies receipt identity, all expected checks and
operations, then repeats actual preflight. Live checks repeat at paid action
boundaries. A key alone cannot enable execution.

Application tokens are injected from environment references, at least 32 bytes,
hashed in memory and compared in constant time. Every authenticated child app has
a permanent trusted identity; caller `application_id` is rejected. Route/read/
execute/health scopes are separate. Task and telemetry access is scoped; public
health is liveness only. Detailed health/docs require health permission. Default
bind is loopback; externally exposed service requires operator TLS termination.

Raw prompt and output content is excluded from ordinary serialization, database,
journal, outbox and dashboard. Immediate successful execute output is returned to
the authorized caller but deliberately cannot be recovered by duplicate replay.
SDK logging and exception bodies are suppressed/sanitized at boundaries. No raw
provider exception or connection DSN is printed by the release CLI.

## Persistence and budgets

The SQL repository uses unique idempotency/task claims, transactional state and
outbox persistence, optimistic updates, immutable snapshots and cross-process
journal locking. PostgreSQL uses row/transaction locks; SQLite serializes writes.
Outbox claim/ack leases preserve at-least-once delivery and event-ID deduplication.
A transport dispatcher is not bundled.

Application/task allocation and action reservations survive reconstruction and
restart. Allocation IDs are independent of release versions. Hard live admission
uses the configured input/output maximum and the greatest relevant cache/input
rate; caller token/cache hints cannot reduce the reservation. Classifier spend is
reserved and persisted before invocation, then included exactly once in task cost.
Unknown outcomes hold reservations and stop further live paid work. Started
uncertain actions are retained without automatic replay.

A quiescent SQLite backup/restore test uses the database backup API, preserves
allocation/outbox/idempotency evidence, and verifies no duplicate dispatch. Do not
copy only the main SQLite file while WAL is active. Operational backups must include
the durable journal and all reservation/history evidence. Restoring an earlier
budget ledger requires spend reconciliation before paid service resumes.

## Final live verification — 2026-09-07

The final pass used baseline `27c295092cf8feca56093cf8d6fcc0b1fbd6a60b`.
After explicit credential and spend approval, a dedicated Model Router key was
created securely and bound to private immutable account evidence. All four exact
model IDs were retrievable; Luna `none`, Terra `none`, Sol `none`, and Astra `low`
completed paid Responses execution. Both real Luna `low` classifier calls passed
strict Structured Outputs with provenance and all seven complexity components.

The end-to-end task `canary-65d07de1176f41f78870e01aadaac26d` passed live
classification → unchanged router → Luna `none` → V0 provider-success validation
→ SQLite persistence/outbox → telemetry. It cost $0.0003282 and took 4,060.757 ms.
The separate classifier result was also fed through the unchanged Phase 1 engine.
Its task-property schema cannot select a generation model, effort or validation.

**Total spend: $0.0018026 across 10 calls**, below the approved **$1.00** aggregate
cap and the stricter **$0.60** combined allocated ceilings. The existing release
runner exercised Terra/Sol/Astra at `medium`; three deliberate additional checks
through the existing explicit-effort provider test covered the required efforts.
The separate classifier check followed that runner. No automatic retry, shadow,
tool call, policy tuning, or unsupported semantic validation was introduced.

The isolated live telemetry cohort has five successful tasks, six paid pipeline
invocations, eleven settled reservations and 37 outbox events. Its $0.0009062
subtotal plus $0.0008964 in standalone live-eval evidence reconciles exactly.
The rendered local dashboard and nine-step end-to-end timeline were inspected;
raw prompt/output content and credentials are excluded, and synthetic flags are
false. Read-only retained evidence correctly leaves current health UNKNOWN.

The [live evidence note](phase-6-live-evidence.md) and its linked machine-readable
record contain per-call safe usage/cost/latency/correlation and version evidence.
Official short-context prices agree with historical snapshots. Fresh local
immutable versions supplied activation status and finite operating limits;
route-selection semantics and the approved source policy/oracle remain unchanged.
The shipped route-only manifest was not enabled for public execution.

This pass fixes no runtime code. It establishes tiny live canary behavior, not
broad classifier quality, every reasoning effort, long-context economics,
V1/V2/V3 live validation, production reliability or application integration.
No package, release, container or public service was published. LEO integration
and V2 work remain outside this task.

## Performance and dashboard

[The local load report](phase-6-performance.md) records eight concurrent requests,
80 mock executions and a 1,000-task analytics dataset. Authenticated route P50/P95
was 10.78/19.33 ms; the activated route-only release was 10.93/14.48 ms. Retrieval
was 15.06/19.67 ms; mock execution throughput 40.21 tasks/s; telemetry P95
673.10 ms; dashboard task-query P95 662.29 ms. All frozen targets
passed. Execute P95 was 759.39 ms under SQLite contention. Peak RSS growth was
~165 MiB including dataset creation; no long-duration leak claim is made.

[Dashboard release inspection](phase-6-dashboard-review.md) passed desktop light,
desktop dark, tablet, narrow mobile, Task Explorer, empty filters, partial cost,
stale/degraded health and the 18-step task timeline. No gratuitous redesign was
made. Accessible names, labels, headings and visible focus were inspected; this
is not a complete assistive-technology certification. Cosmetic density/muted text
preferences remain nonblocking. The dashboard is read-only; a production browser
credential boundary is an operator integration limitation.

## Independent reviews

Security/reliability review found and root fixed: mismatched credential source,
incomplete activation-receipt validation, missing live runtime opt-in readiness,
undischarged durable period-budget admission, a sentinel-ID isolation error in
that first fix, and direct model-probe SDK access. The final reviewer reported no
remaining material code finding. Root also added successful-classifier unknown-cost
blocking, report-before-probe persistence, sanitized CLI failures and unsupported
configuration rejection. Live account evidence is bound to the exact injected
credential fingerprint, so rotation requires renewed evidence. Focused tests cover the fixes, including actual release
activation → authenticated execute with provider stub and two-app isolation.

The independent economics review found two issues: pre-dispatch refusals inflated
provider-call metrics, and preflight accepted unsupported token envelopes. Both
were fixed with regressions. Exact durable-budget arithmetic was also hardened
against caller Decimal precision. The reviewer passed 72 focused tests plus
179/179 and 22/22, and reported no remaining material finding.
Those reviews were offline; the subsequent final live pass above resolved the
account/model/canary release blocker without changing runtime code.

## Regression and release verification

The independent oracle and the four approved policy YAMLs are byte-for-byte
unchanged from the approved baseline. All phase runners passed: 142 Phase 1,
19 Phase 2, 17 Phase 3, 1 Phase 4; combined 179/179 and 22/22 extra regressions.
Frontend: 21 tests passed; TypeScript checks and production build passed.
YAML/TOML parsing, repository skill validation and `git diff --check` passed.

The complete local CI-equivalent command passed: **712 backend tests passed,
4 skipped** (three explicit PostgreSQL tests plus the opt-in live test). PostgreSQL
18.4 was then exercised separately: **3/3 passed**, including four-process actual
execute admission with exactly one provider dispatch. SQLite passed the same
four-process execute check, repeated allocation contention, exact-decimal budgets,
and quiescent backup/restore. Default tests remain network/credential guarded.

Both wheel and sdist build successfully with pinned Hatchling, locked Python and
frontend dependencies and deterministic build timestamp. The wheel contains
compiled dashboard assets and Alembic revisions. It was installed outside the
checkout and its packaged migrations passed downgrade/base → upgrade smoke.
Fresh editable Python installation is also tested without any dashboard directory;
a build hook reserves generated assets for standard release wheels. This closes
the missing-frontend-assets failure exposed by the first clean CI checkout.
Artifacts live in `dist/`; `SHA256SUMS` records final local digests. Docker is not
installed locally. The [clean-checkout CI run](https://github.com/R1skyBiz/openai-model-router/actions/runs/34132794017) passed all gates on
`94b6b77e8f94aba324850d41287828ba90ef761f`, including the full verification
suite, PostgreSQL 16 integration/migrations and the authenticated container build.
No wheel, source distribution or image was uploaded or publicly published.

The local verification command also includes configuration/skill/secret checks,
immutable policy/oracle diff, backend tests, each phase runner, load harness,
frontend tests/typecheck/build, package build and installed-wheel smoke. Direct
repository skill validation reported valid. A separate scan of tracked and new
files found no candidate API credentials or private keys. No public release is
created. See [deployment](deployment.md)
for build, local demo, migrations, activation, startup and rollback commands, and
[integration](integration.md) for the application/operator/policy-engineer contract.

Two final local builds produced byte-identical wheel and source distributions.
The local PostgreSQL 18.4 test server was stopped after successful verification.
The final live pass resolved the account/model/pricing/canary release blocker.
The next milestone is first-application integration and production telemetry,
beginning with LEO.

## Final regression rerun

After the paid checks, the complete `scripts/verify_release.py` command passed
again: **712 backend tests passed, 4 deliberately skipped**, **21 frontend tests**,
TypeScript/build, all Phase 1–4 runners, **179/179 combined** and **22/22 regressions**,
positive/negative grader fixtures, configuration/skill validation, migration checks,
and package/clean-install smoke. The three PostgreSQL tests passed separately
against a new isolated local database. Historical routing policy and independent
oracle remained byte-for-byte unchanged. Final source/link/secret checks and
`git diff --check` cover this evidence-only update.
