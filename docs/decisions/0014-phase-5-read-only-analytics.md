# ADR 0014: Read-only analytics over retained execution evidence

Status: Accepted for explicitly authorized local Phase 5 implementation

## Decision

Centralize metric definitions in a framework-independent telemetry analytics
module. Read a consistent SQLite snapshot of retained task payloads and outbox
events through a separate query adapter. Keep FastAPI handlers and the React
dashboard free of KPI formulas. Preserve the existing execution/storage contracts
and immutable policy/catalog/pricing evidence; no schema migration is necessary.
SQLite reads explicitly begin a transaction before reading task/outbox tables.
Equal-timestamp timeline events retain the outbox's insertion order using SQLite
rowid; the current event contract has no portable sequence. A future database
adapter must provide equivalent ordering rather than sort random event UUIDs.

Task metrics use half-open UTC admission cohorts and terminal denominators;
spend uses charge occurrence times. Unknown costs retain known subtotals, and
zero-denominator KPIs remain null. Initial-route efficacy attributes downstream
cost to the route that began the task. Model-spend views use the invoked model.
Shadow accounting remains separate. Rubric-incompatible scores are not pooled.
The frozen API and display contracts are in [Phase 5 interfaces](../phase-5-interfaces.md).

Use a separately generated, integrity-marked synthetic database for local UI
development. Every sample task has synthetic identity, policy and route evidence.
Opening the demo validates its manifest and every task; generation refuses to
overwrite existing data. The demo server binds localhost and exposes read-only
telemetry only. Synthetic costs are fabricated observed amounts, not tariffs or
claims about model performance. Two synthetic policies support descriptive
comparison without activating or altering routing policy.

## Limits

Snapshot aggregation is an intentionally bounded local architecture, not a
production analytics warehouse. Retained health observations do not establish
current operational readiness; stale/unknown states stay visible and reads do
not probe. Production execution, deployment authentication, distributed budgets,
distributed health, adaptive routing and automatic policy activation remain
outside Phase 5. No public hosting or Phase 6 work is authorized by this ADR.
