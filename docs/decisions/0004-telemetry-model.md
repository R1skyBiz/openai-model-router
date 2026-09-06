# ADR 0004: Telemetry model

Status: Accepted

## Context

Generic success/failure and one row per model call cannot explain task outcomes,
recovery costs, or policy performance.

## Decision

Separate tasks, routing_decisions, attempts, tool_events, evaluations, health_checks,
policy_versions, model_catalog_versions and pricing_versions. Every task has
task_id/trace_id. Every execution eventually emits correlated telemetry. Attempts retain
their execution-time pricing snapshot; never reprice historical work with current rates.
Raw prompt/response capture defaults off and secrets never enter telemetry.

## Consequences

[telemetry.md](../telemetry.md) defines grains, usage/cost fields, normalized failures,
privacy and backend-owned KPIs. Shadow/classifier/evaluator costs remain attributable
without inflating production success. Durable event retention and idempotent delivery
are required before production.

## Unresolved implementation details

Storage engine, durable transaction/replay implementation and retention durations are
unresolved; [ADR 0007](0007-storage-boundary.md) records that boundary without accepting
a database-engine choice.
