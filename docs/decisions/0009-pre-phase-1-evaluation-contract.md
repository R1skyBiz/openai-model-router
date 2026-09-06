# ADR 0009: Independent pre-Phase-1 evaluation contract

Status: Accepted

## Context

The architecture at f3e8c70 is approved. The separately authorized evaluation
step must establish behavioral expectations before a routing implementation can
influence the oracle. Architecture acceptance did not authorize runtime work.

## Decision

Add a versioned JSONL corpus, strict eval-only interchange schemas, and an offline
grader under `evals/`. Expected model/effort envelopes, failures, validation,
readiness, evidence assertions and scripted recovery sequences are authored as
data. The grader compares supplied observations; it never selects a candidate,
classifies a prompt, executes recovery, or consults policy candidate/floor logic.

Pin the approved configuration with content hashes. Catalog facts may verify
model identity, effort support, capabilities and token limits. A separate frozen
vocabulary validates enum names and component ranges. Neither source generates
expected routes. Policy changes require human review of affected cases before
repinning; a passing hypothetical result is not evidence that a router exists.

Separate routing correctness from execution readiness. Unconfigured evaluators,
domain validators, unknown required charges, missing approvals and uncertain
access can block execution of a structurally valid route. An unhealthy candidate
is excluded; when no permitted healthy path exists, expect a recoverable rejection.

Synthetic health, budget, evaluator and recovery facts support offline scenarios.
Their finite amounts and timing limits are test inputs, not operational defaults
or activation of the draft configuration. Preserve an empty historical regression
file until an actual implementation regression is discovered.

## Consequences

Phase 1 will adapt its decisions/rejections to the documented observation
projection. Phase 2 classification seeds and Phase 3 recovery scripts remain
forward contracts, executable only as grading of supplied fixtures today.
Runtime contracts, routing logic, provider calls and execution remain unimplemented.

The corpus accepts legitimate alternatives rather than specifying every detail
of cold-start ordering. It supplements, rather than replaces, Phase 1 config,
pipeline and ordering tests. A projection assertion proves only the supplied
evidence: future adapter conformance tests must connect that evidence to actual
decisions and events. Privacy projections do not prove a transport is leak-free.

## Unresolved details

The architecture does not select an exact failure code for complete health
unavailability. Those cases accept PROVIDER_FAILURE or UNKNOWN_FAILURE, require
health-constraint evidence, and require recoverability; they exclude capability
and quality misclassification. Resolve the precise adapter mapping in its phase.

Cost calibration, confidence thresholds, latency estimators, operational retry
limits, real evaluator/domain bindings, and public/account metadata verification
retain their existing phase gates. No live probes or policy activation occur here.
