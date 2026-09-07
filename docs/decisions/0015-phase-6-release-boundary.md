# ADR 0015: Explicit release activation and transactional admission

Status: Accepted for explicitly authorized Phase 6 hardening

Use a separately versioned release composition, explicit fail-closed preflight and activation, application-scoped bearer credentials and SQLAlchemy transactional budget/task/outbox coordination. Preserve the immutable approved routing policy and independent eval contract. Production model calls remain unavailable without separately verified access/prices, finite admission and explicit live enablement. A key in the environment is never authorization.

SQLite supports bounded single-host operation using cross-process transactions and local fsynced journal locks. PostgreSQL uses transaction/row locks for shared budget and event coordination. No distributed provider atomicity is claimed: a started uncertain invocation is retained for operator reconciliation, never automatically replayed. Unknown cost holds its reservation. Outbox delivery is at least once with event-ID deduplication, not exactly once.

Retention preserves idempotency, budget and historical price evidence; no automatic destructive pruning or raw prompt/output capture. Release defaults disable shadow and paid health probes. Health state is process-scoped unless a durable source is explicitly bound; observations never certify unprobed model access.

The release criteria and initial gap matrix are frozen in `docs/phase-6-interfaces.md`. A prepared package is not an authorized public release. Missing live credentials/access yields the status “RC blocked on live verification.” Unrun PostgreSQL/container/visual checks remain explicit blockers, never inferred successes.
