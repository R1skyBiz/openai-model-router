# ADR 0003: Escalation policy

Status: Proposed

## Context

A route may need a stronger model, more reasoning, or human review after a
classification, execution, or validation result.

## Decision

Represent escalation triggers and allowed targets as policy configuration.
Detailed triggers and limits remain a Phase 1 decision.

## Consequences

Escalation must be bounded, observable, and protected from retry loops.
