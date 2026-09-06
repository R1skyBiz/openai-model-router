# ADR 0002: Model ladder

Status: Accepted

## Context

Intelligence tier, reasoning effort and execution economics are separate dimensions. The
highest complexity score must not hard-wire the most expensive model.

## Decision

Use the initial L0 Luna → L1 Terra → L2 Sol → L3 Astra ladder. Registry IDs, reasoning
support, capabilities, context limits, availability and versioned prices live in
[models.yaml](../../config/models.yaml), not core code. Model and reasoning effort are
independent. Complexity bands are configurable routing priors;
family/capability/context/budget/health constraints influence the final choice.

## Consequences

The classifier supplies task facts, never the final model. Registry updates are
independent of routing algorithms and retain historical versions. Unsupported
model/effort pairs are invalid. Public metadata verification is separate from account
access.

## Unresolved implementation details

Account access and unverified pricing/capabilities need verification for each enabled
path. Relative route efficacy and policy calibration are not settled by this ladder.
