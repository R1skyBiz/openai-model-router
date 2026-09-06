# ADR 0003: Escalation policy

Status: Accepted

## Context

A failure can reflect inadequate quality, broken infrastructure, a tool problem, invalid
output or exhausted budget. Increasing model tier is not a universal repair.

## Decision

Keep the full normalized failure taxonomy in
[routing-policy-v1.md](../routing-policy-v1.md). Confirmed quality failure may increase
reasoning, revalidate a new attempt, then increase model tier and revalidate.
Infrastructure uses retry/backoff/health-aware fallback without automatic intelligence
escalation. Tools use recovery/alternate strategy/recoverable failure. Diagnose
validation, malformed-output and unknown failures before claiming a reasoning failure.

## Consequences

All recovery is bounded by attempt/time/cost budgets, capabilities and approval
constraints. Track intelligence escalation separately from infrastructure retries and
tool recovery. Tool timeouts cannot trigger Luna→Astra merely because execution failed.
Future evidence can justify a new policy skipping intermediate quality steps.

## Unresolved implementation details

Finite retry/backoff limits, quality diagnosis thresholds and alternative tool
strategies are Phase 3 configuration/eval work; no unlimited or invented defaults are
accepted.
