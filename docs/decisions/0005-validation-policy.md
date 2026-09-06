# ADR 0005: Validation policy

Status: Proposed

## Context

Different request classes require different checks before a response can be
accepted.

## Decision

Select validation profiles through configuration and keep deterministic checks
available offline. Model-based validation will be an optional adapter.

## Consequences

Tests can cover route and validation policy without an OpenAI API key.
