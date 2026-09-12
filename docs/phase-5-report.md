# Phase 5 — Telemetry analytics and dashboard

Implemented against the approved Phase 4 baseline
`3534dca65542b56e94a5273837e78cb5288deaa8`. Production execution remains disabled.
Phase 6, adaptive routing, autonomous policy changes, and public deployment have
not begun. Verification date: September 7, 2026 UTC.

## Ownership and integration

Root acted as architect/integrator, froze [interfaces](phase-5-interfaces.md) and
TypeScript wire contracts before delegation, and owned demo generation,
integration, documentation, final fixes, verification, and delivery. Sol High
workers owned analytics (A), telemetry API/storage projections (B), and the
complete React dashboard (C). The three available worker slots consolidated the
requested six workstreams; root handled demo/developer experience. A separate
Sol High reviewer audited the integrated backend and visual/interaction design.
The requested root allocation was Astra High; worker and reviewer model overrides
were explicitly Sol High. Shared-checkout ownership stayed disjoint; there were
no merge conflicts or worker commits. Root incorporated review fixes in the
single integrated delivery commit.

[ADR 0014](decisions/0014-phase-5-read-only-analytics.md) records the durable
read-model boundary, UTC semantics, retained event ordering, and isolated demo
composition. No persistence schema change was required.

## Analytics

The framework-independent `telemetry/analytics.py` owns all KPI formulas.
The React app formats and visualizes its responses. [Metric definitions](phase-5-metrics.md)
specify denominators, cost authorities, missing evidence, filters, quantiles,
projection, and rubric compatibility.

- Task cohorts use admission time in the UTC half-open window `[start, end)`;
  spend uses charge occurrence time. The default is the preceding 30 days.
- Success, first-pass, intelligence escalation, and tool recovery use terminal
  task denominators. Cancelled tasks are terminal; blocked tasks are separately
  reported within pending. Infrastructure retry uses invoked provider attempts.
- Effective cost per successful task is total persisted production spend for
  terminal tasks in the cohort, including failed work, divided by successful
  tasks. Cost per task uses the same numerator and terminal-task denominator.
- Historical actual fees and task totals are retained. Decimal aggregation and
  decimal-string API amounts avoid repricing and binary floating-point money.
  Partial totals retain known subtotals; empty/undefined values remain null.
- Shadow cost and quality are separate. Evaluator model fees are counted once;
  unplaceable fee timestamps are explicitly unallocated.
- Initial model/effort cohorts own downstream outcome and task cost; spend
  groups use the model/effort actually invoked. Date, application, family, policy,
  purpose, contribution, and validation views expose the supporting breakdowns.
- Today/MTD use UTC calendar windows. Monthly projection is elapsed-time linear
  MTD run rate, with partial/unavailable states preserved. Latency uses nearest-
  rank P50/P95 over retained admission-to-terminal-update durations.
- Quality is grouped by rubric, check, scale, and role with task-scoped target
  deduplication. Mixed groups are not comparable. Policy cohorts show cost,
  outcomes, latency, escalation, and comparable quality evidence; fewer than 30
  terminal tasks is a display warning, with no significance or policy-change claim.

## API and persistence

Typed Pydantic/OpenAPI responses and matching TypeScript contracts cover:

```text
GET /v1/telemetry/summary
GET /v1/telemetry/spend
GET /v1/telemetry/routing
GET /v1/telemetry/efficacy
GET /v1/telemetry/health
GET /v1/telemetry/models
GET /v1/telemetry/task-families
GET /v1/telemetry/policies
GET /v1/tasks
GET /v1/tasks/{task_id}?view=timeline
```

HTTP handlers delegate to query/analytics services. A storage adapter explicitly
begins a SQLite read transaction before reading tasks and complete outbox
history. The list is newest-first, with stable task-ID ties, default 25/max 100
rows and offset pagination. Timelines use default 100/max 500 events and preserve
persisted append order for equal timestamps. The original default task metadata
endpoint remains compatible.

All requested filters are supported. Aware times normalize to UTC; invalid,
naive, or reversed windows return sanitized 422 responses. Production telemetry
requires trusted application scope, excludes synthetic evidence, and fails closed
when no scope exists. Only explicitly synthetic composition permits cross-app
inspection. Missing/unsupported storage is a safe 503; unavailable tasks are 404.

Timeline start/completion events have distinct titles. Cost, usage, latency,
validation, failure, recovery, policy/pricing, and retained health metadata are
progressively inspectable through allowlisted projections. Completion facts and
fees appear on their owning completion event rather than being repeated on
starts or evaluator references. Raw prompts/outputs and arbitrary metadata are
not exposed by these telemetry views.

Health reads retained observations without probes. It shows component states,
circuits, freshness, failure/timeout/rate-limit counts, latency, and outbox state.
Future observations are unknown, expired observations stale, and shared snapshots
produce one degraded interval per evidence identity. These intervals are retained
observations, not continuous outage measurements. Production readiness stays false.

## Dashboard and previews

React/TypeScript/Vite provides Overview, Spend, Routing, Efficacy, Health, and
Tasks. Recharts supplies restrained line/bar/distribution views. The project
uses system typography, neutral surfaces, subtle separators and shadows,
consistent spacing, and separately tuned light/dark tokens. System appearance is
the default; explicit choices persist locally. The overview emphasizes economics
and outcome evidence; the task explorer exposes a paginated execution timeline.

Responsive navigation, labeled two-column mobile filters, adaptive KPI grids,
and keyboard-scrollable tables support narrower inspection. Skip navigation,
semantic controls, visible focus, text status labels, chart summaries/tooltips,
keyboard timeline disclosure, loading skeletons, error/retry states, and reduced
motion are included. Browser inspection covered desktop light/dark, tablet, and
390px mobile layouts; this is not a claim of a full WCAG audit.

Screenshots from the local synthetic dataset:

- [Overview, dark](previews/phase5-overview-dark.png)
- [Efficacy, light](previews/phase5-efficacy-light.png)
- [Task timeline, light](previews/phase5-task-light.png)
- [Mobile filters, dark](previews/phase5-filters-mobile.png)

## Synthetic demo and local startup

From the repository root:

```bash
uv sync --extra dev
uv run --offline python scripts/generate_sample_data.py
uv run --offline python scripts/serve_demo.py
```

In a second terminal:

```bash
cd dashboard
npm ci
npm run dev
```

Open http://127.0.0.1:5173 (API/OpenAPI docs at http://127.0.0.1:8000/docs).
The demo server binds localhost and has no execution endpoint. No API key or
provider call is needed. Generation creates an Alembic-migrated SQLite database
and SHA-256 integrity manifest under ignored `.demo/`. Every task, route, policy,
response, and preview clearly identifies synthetic evidence. The manifest and
record provenance are checked when opening it, and generation refuses overwrite.
Use `--output /path/to/new-demo` and `--data /path/to/new-demo` for another dataset.

The generated 180-task example spans 28 days, three applications, two synthetic
policies, Luna/Terra/Sol/Astra, multiple efforts, V1/V2 validation, successes,
failures, cancellations, pending tasks, quality escalation, infrastructure retry,
tool recovery, health degradation, and separate shadow comparisons. Fabricated
fees and scores are configured in `config/demo.yaml`; they make no claim about
live model prices or quality. Health freshness ages normally.

## Verification

| Check | Result |
| --- | --- |
| Full backend pytest | 658 passed, 1 skipped; 2 dependency deprecation warnings |
| Phase 5 backend coverage within that suite | 28 analytics, 13 API, 3 demo tests passed |
| Dashboard tests | 21 passed across 3 files |
| Dashboard TypeScript check | Passed |
| Dashboard production build | Passed |
| Phase 1 | 142/142 |
| Phase 2 mock classification | 19/19 |
| Phase 3 | 178/178 applicable; 17/17 Phase 3 recovery scenarios |
| Phase 4 remaining evaluator scenario | 1/1 |
| Combined authored corpus | 179/179; independent grader 179/179 |
| Additional Phase 4 regressions | 22/22 |
| Positive grader fixtures | 27/27 accepted |
| Negative grader fixtures | 19/19 rejected; expected exit 1 |
| Empty-database migrations and sample generation | Passed |
| Persisted cost reconciliation, API scope/privacy, snapshot ordering | Passed |
| Accessibility-focused keyboard/semantic/theme tests | Passed |
| Offline/network guards | Passed in full backend suite |
| YAML/TOML and typed policy bundles | Passed |
| Model-router skill validation | Passed |
| Approved policy/oracle integrity | Unchanged against approved independent contract |
| Full staged diff audit and `git diff --check` | Passed; only Phase 5 scope and intended artifacts |

Phase 3's historical runner defers the evaluator case by design; Phase 4 supplies
it, and the combined 179-case run has no deferral. The single pytest skip is the
explicitly opt-in live-provider test. The two warnings concern existing
FastAPI/Starlette test dependencies; no live call or production gate was enabled.

## Independent review and fixes

Review covered monetary/denominator correctness, timestamp and event order,
quality comparability, historical evidence, scoping/privacy, frontend truthfulness,
and visual hierarchy. Fixes included initial-route versus invoked-model filters;
first-pass handling of completion bookkeeping and retained retries; unknown tool
fees; task-scoped quality deduplication and final-error suppression; provider
failure retry fallback; shadow-attempt exclusion; and descending spend ranking.

API fixes covered duplicate timeline fees/final facts, equal-timestamp causal
order, missing production scope, future health evidence, safe inspectable health
metadata, distinct generation/evaluation/classification start/completion titles, and shared health-snapshot
interval deduplication. UI fixes covered legible secondary text, UTC date labels,
partial/unknown costs and empty trends, filter values/breakpoints/mobile labels,
explicit cohort denominators, honest health and ranking captions, and visible
policy rubric/scale evidence alongside sample-size warnings.

Final independent Sol High review: **PASS — no material blocker remains for Phase 5.**
The reviewer independently reran all 44 Phase 5 backend tests, all 21 dashboard
tests, typecheck, production build, and staged diff check. The final inspection
covered the refreshed light/dark/mobile/task previews and documented limits.

## Limits and delivery

Aggregation scans retained SQLite evidence per request. It is suitable for local
Phase 5 inspection, not a production analytics warehouse; no distributed cache,
authentication hardening, or deployment work was added. Outbox retention bounds
reconstructable history, and equal-time ordering currently relies on SQLite
rowid. Timestamp-less fees without a correlation stay unallocated. Task latency
uses the retained terminal update time. Subsequent same-tool/operation contribution
is an inference because the current tool record has no predecessor ID. Health
observations cannot certify current availability. Policy comparisons are
observational and may reflect different task mixes. Chart geometry uses finite
JavaScript numbers while displayed monetary values retain backend evidence.

The approved policy values, independent oracle, execution behavior, and live gates
remain unchanged. Delivery is one root commit on `main`, followed by push to
`origin/main`; the final task response records the resulting commit SHA, push
result, and working-tree status. The report is included in that same commit.
