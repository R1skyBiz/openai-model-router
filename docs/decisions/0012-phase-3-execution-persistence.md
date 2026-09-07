# ADR 0012: Bounded execution and local transactional evidence

Status: Accepted for explicitly authorized Phase 3 implementation

Phase 3 resolves the execution/storage boundary without enabling production.
Use synchronous injected orchestration, immutable evidence records and explicit
finite synthetic limits. The existing provider continues to make one invocation.
V0 is the only implemented validation level; required V1/V2/V3 remains blocked.

Use SQLAlchemy 2 with SQLite for local execution and Alembic migrations. Store
portable JSON, string identifiers, UTC timestamps and decimal-string money;
PostgreSQL deployment and concurrent production budget reservations remain later
hardening. Within one database transaction, compare task revision and persist
state, decisions, attempts, tools, evaluations and outbox events. Claim scoped
hashed idempotency keys atomically. Retain metadata until explicit deployment
retention is defined; raw prompts, outputs, tool arguments and secrets are excluded.

Persist intent before dispatch. A crash with a started attempt is an uncertain
outcome and must not trigger automatic replay. If completion persistence fails,
retain a durable local journal for later reconciliation; journal failure is an
explicit storage-unavailable error with prior started evidence retained. Outbox
acknowledgement is idempotent; transport delivery is deferred.

No distributed atomicity with providers is claimed. Production remains disabled
until pricing/access, operational limits, authentication and production reservation
concurrency are explicitly resolved. No Phase 4 health/evaluator/shadow work begins.
