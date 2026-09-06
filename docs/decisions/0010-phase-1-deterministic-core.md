# ADR 0010: Phase 1 deterministic routing and preview evidence

Status: Accepted for Phase 1 implementation

## Context

The architecture at `f3e8c70` and independent evaluation contract at `f42ecc9`
precede runtime implementation. Phase 1 is now explicitly authorized. It supplies
typed routing and configuration, with no provider, classifier, execution,
recovery, persistence, transport, or health-probe implementation.

The approved configuration defines constrained fallback by tier rank but does
not specify traversal direction or fallback effort construction. The independent
`boundary_89` envelope requires the nearest lower tier with compatible high
effort when the top prior is excluded by a ceiling. Health envelopes permit
neighboring tiers when an ordinary prior is unavailable. Neither requires a
change to a policy value, model table, or authored envelope.

## Decision

Use `route(request, classification, environment_snapshot, policy_bundle)` as the
canonical embedded API. All inputs are typed immutable records. Load and validate
the complete referenced YAML bundle before routing. The engine recomputes the
complexity total and owns the final model/effort choice. Configured candidate
ordering is the cold-start prior; no success probabilities are invented.

For constrained fallback, traverse non-prior models by distance from the nearest
prior tier, breaking ties by lower configured tier rank. Intersect the prior's
ordered effort sequence with each fallback model's support; when no prior effort
is supported, use the configured floor effort preference. This resolves the
unspecified traversal detail using the independently authored behavior. Actual
floor additions use the configured floor effort preference, leaving existing
prior efforts intact. All capabilities and hard bounds still apply.

Without a configured operational confidence cutoff, record any non-certainty
under the existing uncertainty rationale with the original confidence and an
explicit null threshold. This annotation never changes candidate construction,
generation tier, effort, or validation.

Complete health unavailability maps to retryable `PROVIDER_FAILURE`, with
`no_healthy_permitted_path` constraint evidence. This chooses one of the accepted
eval envelope alternatives without implying a quality failure.

Separate structurally valid previews from execution prerequisites. Missing
evaluator/domain bindings, unknown required charges, insufficient remaining
evaluator funds, known deadline shortfalls, approval gaps, and uncertain access
remain visible blockers. Mandatory validation is never removed to make a path
affordable. Hard model/context/capability constraints and generation-budget
impossibility return structured rejections.

When another candidate can certify its required charges, remaining funding, and
account access, prefer that feasible path before returning a blocked preview.
Preserve a preview when none can certify these facts. Candidate exclusions and
preferred-floor waivers retain the actual price/access/funding blockers. Shared
approval or missing evaluator prerequisites do not change generation tier.

Synthetic environment facts can supply the finite mock deployment limits and
bindings required by the offline corpus. These facts never activate the draft
production policy. Trusted application overlays belong to the environment;
caller application IDs alone do not select authorization. Caller limits only
tighten trusted limits. Every quote retains snapshot identifiers and every
decision includes a deterministic content-derived identifier and effective
configuration hash.

Quote identifiers hash the actual catalog rates and required additional charges;
they do not trust an arbitrary environment pricing label. Each cost also records
the model's pricing version and normalized token assumptions. Domain-validator
charges have their own fact and never reuse evaluator fees. Output explicitly
labels synthetic environment evidence.

Cache evidence supports an expected discounted quote but never guarantees a
future hit. Admission checks both that quote and a cache-miss quote against
task and remaining-budget limits, retaining the latter in rationale evidence.
Required-charge funding evidence identifies the first charge crossing the
remaining balance in generation, evaluator, domain-validator, tool order.

Static active-live configuration requires finite task limits, bounded recovery,
known base rates for enabled eligible models, and active referenced snapshots.
This validation is not an activation service. Phase 1 rejects non-null domain
validator references until a later registry can resolve them; synthetic mock
bindings can exercise readiness without implementing a validator. Side-effecting
requests remain blocked until execution authorization exists in a later phase.

## Consequences and remaining phase gates

All configured model/provider IDs, prices, effort support, numerical policy
values, and capabilities stay in YAML. The authored oracle remains byte-identical
to `f42ecc9`. The adapter derives observations from runtime evidence and lists
every unsupported classification/recovery case with its reason.

The adapter's content-exclusion facts describe its actual allowlisted projection;
they do not prove a future telemetry transport redacts arbitrary secrets. Real
execution readiness, tariffs, account verification, reservations, latency
prediction, calibrated confidence handling, evaluator implementation, and durable
telemetry retain their later-phase gates. No Phase 2 work is authorized here.
