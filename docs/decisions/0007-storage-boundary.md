# ADR 0007: Storage boundary and durable telemetry

Status: Accepted

## Context

Execution telemetry must survive transient writer failures and preserve historical
pricing without coupling routing to a database.

## Decision

Use SQLAlchemy/Alembic at the persistence boundary and the conceptual entities in
[telemetry.md](../telemetry.md). The core emits facts through interfaces, not ORM
objects. Activated policy/catalog/pricing snapshots are immutable. Require durable
pending-event retention and idempotent delivery before production; stop new paid work
when events cannot be durably retained.

## Consequences

Storage must support task/attempt correlation, event replay/deduplication and
attributable historical cost corrections. A chosen durable delivery mechanism and
migration recovery procedure need verification during Phase 3.

## Unresolved implementation details

The database engine, schema/index details, outbox versus alternative durable delivery
design, transaction boundaries, deployment topology and retention durations are NOT
decided here. Record their resolution before implementing persistence; Accepted applies
only to the boundary and durability requirement.
