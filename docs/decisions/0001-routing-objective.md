# ADR 0001: Routing objective

Status: Accepted

## Context

A low token price can produce costly retries, weak results and validation work.
Complexity and consequence alone do not determine the cheapest successful route.

## Decision

Optimize **Effective Cost per Successful Task** while satisfying quality, reliability,
capability, latency and budget constraints. Raw token cost is secondary. Include
unsuccessful work, recovery, classification, tools and required evaluation in production
task economics. Use transparent configured priors until calibrated route-success
evidence exists.

## Consequences

Backend metrics use the task-level definitions in [telemetry.md](../telemetry.md).
Compare versions on consistent cohorts and acceptable routing envelopes. Never claim a
cold-start prior is a measured success probability.

## Unresolved implementation details

Calibrated probability/cost estimators, uncertainty methods, quality thresholds and
latency targets remain unresolved. They must be configured and evaluated before use.
