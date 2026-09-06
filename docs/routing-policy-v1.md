# Routing Policy v1

Status: Draft

## Purpose

Describe how request signals will map to a model, reasoning level, budget,
validation profile, and escalation path.

## Policy principles

- Policy is evaluated independently of the service framework.
- Route selection is deterministic for the same normalized inputs and config.
- Configuration names provider-specific values; Python code consumes typed
  configuration rather than embedding model or price tables.
- Validation and escalation are explicit parts of a route decision.

## TODO

- Define request classes and classification signals.
- Define the model ladder and eligibility constraints.
- Define budget enforcement and fallback ordering.
- Define validation failures and escalation triggers.
