# ADR 0011: Phase 2 classifier and single-invocation provider

Status: Accepted for the explicitly authorized Phase 2 implementation

## Context

Phase 1 (`971f083`) is approved. It consumes a supplied Classification and returns
a deterministic route or rejection. The independent oracle (`f42ecc9`) includes
19 classification seeds and 18 recovery scenarios with separate phase gates.
Adding an OpenAI adapter does not authorize the execution lifecycle in Phase 3.

## Decision

Keep all existing routing/configuration algorithms and activated-policy semantics
unchanged. New SDK-free records and synchronous ports live in core-owned modules;
the executable OpenAI adapter alone imports the SDK. No streaming, tools, retries,
escalation, persistence, telemetry transport or HTTP execution endpoints are added.
The provider owns at most one Responses invocation and explicitly disables SDK
retries and truncation. Required request output/time bounds are finite.

The classifier consumes a task and returns the existing Phase 1 Classification
inside a result carrying versions and provider accounting. Its strict wire schema
is derived from the pinned factual vocabulary, not model tiers or selection
rules. It contains family, all seven components, confidence, boolean scope flags,
and null subclass. The policy has no subclass vocabulary; inventing one would
change the approved Phase 1 contract. Model, effort, validation, provenance and
component total are not model-authored output fields. The adapter assigns
provenance from classifier configuration, prompt/schema versions and hashes.
The policy still independently validates the components and recomputes the sum.

The separately versioned draft `classifier.yaml` selects the classifier's own
Luna/low invocation and finite output/time bounds. That configured invocation is
not a recommendation for the task's generation route. Existing four YAML policy
documents remain byte-identical to the approved oracle. No production execution
is enabled. Classifier prompt changes require a new version; hashes detect
different content bearing the same human-readable version.

Use the official Python SDK (verified 2.54.0) and Responses Structured Outputs.
The public raw-response parsing wrapper preserves the provider envelope before
the SDK validates generated structured content. This is necessary because a
Pydantic parse failure otherwise loses the response ID and paid usage. The API's
strict structured text format remains active; the classifier never parses
freeform JSON. Failures and incomplete responses retain all available accounting.

Normalize input, cache-read, cache-write, output, reasoning and total independently.
Missing fields are null, not zero. Cache buckets are disjoint subsets of input;
reasoning is a subset of output. Inconsistent counts are malformed provider
evidence, never a quality finding. Completed provider output is not proof of task
success. Incomplete and refusal states are explicit and cannot become a valid
classification. Retry-relevant error metadata uses an allowlist; raw messages,
HTTP bodies, arbitrary headers and credentials never enter normalized records.
Output content stays available in memory and excluded from normal serialization
and repr. This does not implement a future telemetry transport or debug capture.

Deterministic mock and SDK conformance evals are reported separately from live
model accuracy. The 19 seeds exercise a classifier path; 18 recovery scenarios
retain their Phase 3 gate. Existing independent grader fixtures stay untouched.
Optional paid checks require explicit opt-in and bounded, reviewed configuration;
ordinary tests block network access and remove credentials. No live call is
required to complete this phase while all live deployment paths remain disabled.

## Remaining gates

Account access and current tariffs must be verified for any enabled paid path.
Production admission/reservations, durable eventual telemetry, recovery and
execution authorization remain Phase 3 work. A low-level provider port does not
constitute a production execute API or permission to act on a route preview.
Classifier accuracy/calibration is unmeasured until an intentionally paid eval;
passing scripted conformance fixtures is not evidence of model quality.
