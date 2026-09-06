# ADR 0002: Model ladder

Status: Proposed

## Context

Routes need an ordered set of eligible models and reasoning levels.

## Decision

Define the ladder in `config/models.yaml` and routing policy configuration.
Do not embed provider model IDs, prices, or reasoning levels in routing code.

## Consequences

Configuration validation must reject unsupported or incomplete ladder entries.
