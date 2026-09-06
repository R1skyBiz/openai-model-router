# ADR 0005: Validation policy

Status: Accepted

## Context

Consequence may require stronger evidence or independent checking rather than a stronger
generation model. Universal semantic evaluation would impose unnecessary cost and
latency.

## Decision

Use configured V0 deterministic checks, V1 lightweight semantic evaluation, V2 strong
independent evaluation and V3 application/domain validation. Evaluation does not run on
every task by default. Consequence can increase validation, evidence, approval gates and
execution restrictions without automatically increasing generation tier. Required checks
cannot be skipped for budget reasons.

## Consequences

[validation.yaml](../../config/validation.yaml) owns profile/default/sampling values.
Required unconfigured validators block execution. Evaluator errors are not generation
quality failures. Configure sampled shadow comparison in both cheaper and stronger
directions; only production output reaches callers and shadow tool side effects are
prohibited.

## Unresolved implementation details

Evaluator models, rubric versions, pass thresholds, domain bindings and shadow
budget/sampling rollout require Phase 4 configuration/evals. V3 composition is
domain-specific; this ADR does not accept an unconfigured evaluator as usable.
