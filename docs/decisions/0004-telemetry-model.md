# ADR 0004: Telemetry model

Status: Proposed

## Context

Routing quality and cost cannot be evaluated without consistent decision and
execution telemetry.

## Decision

Use structured events with correlation identifiers and explicit redaction.
The final schema and storage backend remain undecided.

## Consequences

Core decisions expose telemetry-ready facts without depending on a telemetry
vendor or transport.
