# ADR 0008: Policy governance and autonomous behavior

Status: Accepted

## Context

Routing may improve with observed efficacy, but automatic policy mutation makes cost,
reliability and historical comparisons hard to govern.

## Decision

Every decision references an immutable policy version and retained effective
configuration. Activated versions are never edited in place. Changes require a new
version, eval coverage and explicit human-controlled activation. V1 does not
autonomously rewrite routing policy, use reinforcement learning, self-modify without
restriction or run unbounded agents.

## Consequences

Shadow evaluation and telemetry inform proposed changes; they do not activate them.
Pin policy/overlay versions per task across recovery; separately record current
health and execution-time tariff facts. New policy activations affect new tasks;
rollback selects an existing retained version. Application overlays are versioned
configuration, not core application branches.

## Unresolved implementation details

Activation storage/API, operator authorization and rollout procedures remain Phase 6
hardening details. Acceptance of bounded agentic routing does not imply an implemented
autonomous workflow executor.
