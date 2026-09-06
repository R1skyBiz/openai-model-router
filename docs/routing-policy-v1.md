# Routing policy v1

Status: Accepted routing philosophy; initial policy data is draft and unactivated.

## Objective and dimensions

Optimize **Effective Cost per Successful Task** under quality, reliability,
capability, latency and budget constraints. Raw token price is secondary.
Cheap attempts can be expensive after retries; a difficult task need not use the
highest tier; high consequence need not use a stronger generator; a failed
request is not necessarily a reasoning failure.

The initial configured ladder is L0 Luna, L1 Terra, L2 Sol, L3 Astra.
Provider IDs, supported efforts and registry metadata live exclusively in
[models.yaml](../config/models.yaml). Reasoning effort is independent of model
tier, and unsupported combinations are rejected.

The authoritative taxonomy, component ranges, complexity priors, floors,
modifiers, selection and recovery values are in
[routing-policy.yaml](../config/routing-policy.yaml); their schema semantics are
in [configuration.md](configuration.md). A task subclass may specialize policy
and telemetry without expanding the v1 family taxonomy into micro-categories.

## Classification and complexity

Classification produces family/subclass, structured scope/capability signals,
confidence, and each complexity component. Store individual components and their
sum. The policy engine verifies ranges and calculates the total independently.
The classifier must not select the final model or reasoning effort.

Reasoning depth measures inferential depth; step dependency measures sequential
dependencies; context synthesis measures integration across material; technical
precision measures exactness requirements; ambiguity measures underspecification;
tool orchestration measures coordinated tool work; reliability requirement
measures repeatability. Consequence is a separate input used primarily for
validation/evidence/approvals. Low confidence is recorded explicitly, not
translated directly into an Astra assignment.

The [canonical pipeline](architecture.md#canonical-routing-pipeline) is the one
ordering used by both library and HTTP routing. Numeric priors are intentionally
maintained once in YAML. They propose low-tier/low-effort routes at low scores,
Terra/Sol alternatives in the middle, and an Astra candidate at the top;
constraints and measured economics can change the final selection.

## Floors, modifiers and economics

Substantive coding has a hard Terra floor. Repository-wide debugging,
refactoring and architecture generally prefer at least Sol. Multivariable
engineering diagnostics, calculations and root-cause work prefer Terra/Sol,
with the initial complex-engineering threshold configured as a Sol preference.

Consequential multi-system agentic work has a Terra hard floor. Long-horizon
autonomous work generally prefers Sol; exceptional end-to-end work adds an Astra
candidate. Tool intensity may raise execution tier even with modest reasoning
depth. “Generally” means an explicit preferred floor, not an undocumented
exception; [configuration.md](configuration.md) defines when it can be waived.

Context window, expected output/reasoning allowance, cache evidence, cache-write
charges, long-context multipliers and retrieval opportunities influence economics.
Retrieval requires an explicit application strategy and its own cost accounting;
routing alone never fetches content or silently truncates input.

Hard capabilities, task floors, mandatory validation, application ceilings,
budget limits and permitted tool actions must all hold. Conflicting hard
constraints produce a structured rejection. A budget ceiling is not permission
to deliver an incapable route. A healthy alternative may continue under degraded
system state; health filtering never bypasses application restrictions.

The initial cost estimator uses versioned prices and documented assumptions.
A calibrated expected-success estimator is deferred. Until calibrated, configured
candidate order is the transparent cold-start prior. Required unknown costs
remain unknown and block live budget certification; they never become zero.

## Failure taxonomy and recovery

| Normalized failure type | Meaning and response |
| --- | --- |
| QUALITY_FAILURE | Confirmed inadequate task result; eligible for bounded intelligence escalation. |
| VALIDATION_FAILURE | A required check did not pass or could not complete; diagnose the cause before escalation. |
| TOOL_FAILURE | External tool/action failed; recover the tool or strategy. |
| TIMEOUT | Model/provider deadline exceeded; infrastructure recovery. Tool-origin timeouts remain TOOL_FAILURE with cause=timeout. |
| RATE_LIMIT | Provider quota/rate throttling; bounded backoff and health-aware recovery. |
| PROVIDER_FAILURE | Provider connectivity/service error; infrastructure recovery. |
| MALFORMED_OUTPUT | Invalid required output shape; diagnose format/schema cause before escalation. |
| BUDGET_FAILURE | Authorized cost/time/attempt budget cannot fund the next step; stop. |
| CAPABILITY_FAILURE | No permitted path meets a required capability; stop. |
| UNKNOWN_FAILURE | Cause unresolved; retain diagnostic uncertainty, no automatic tier promotion. |

Record failure stage, source, cause code and original normalized type. A failed
evaluator invocation is an evaluator infrastructure/tool problem, not evidence
that the generation model is weak. A deterministic test failure may establish a
quality issue after diagnosis; malformed output may be recoverable formatting.
Record any diagnostic reclassification and evidence rather than overwriting the
original observation.

Confirmed quality failure may take:
current model → more reasoning → revalidate → higher tier → revalidate.
For example, Terra/medium → Terra/high → Sol/medium. Revalidation means checking
the newly generated attempt before another escalation, not repeatedly checking
unchanged output. If no supported higher effort exists, consider a bounded tier
change. A new tier selects its own supported effort. Telemetry/evals may justify
skipping steps in a future manually activated policy version.

Infrastructure recovery takes retry → backoff → health-aware fallback. It never
automatically increases intelligence tier. Tool recovery takes retry/recover
tool → alternate tool/strategy → recoverable failure. A tool timeout must never
cause Luna → Astra merely because the request failed.

All recovery is bounded by configured attempt counters, deadline and remaining
task budget. Do not retry side effects without idempotency or verified safe
reconciliation. Stop for required approval, exhausted limits or no safe route.
[Health](health-audit.md) owns circuit behavior; [telemetry](telemetry.md) keeps
intelligence escalation and infrastructure retries separate.

## Validation and shadow comparison

[validation.yaml](../config/validation.yaml) owns V0–V3 profiles and consequence
defaults. V0 uses applicable deterministic checks (schemas, expected fields,
calculations/invariants, compilation, unit tests, and tool/API success).
V1 is lightweight semantic evaluation, V2 strong independent evaluation, and
V3 application/domain validation. Mandatory checks are never skipped to fit a
budget. Semantic evaluation does not run on every task by default.

Higher consequence often strengthens validation, evidence, approvals or
execution restrictions instead of the generation tier. This does not weaken
separate task-family/capability requirements.

Sampled shadow comparisons are a future extension point, disabled by default.
Configuration includes both stronger and cheaper alternatives: Terra/medium
against Sol/medium and Sol/high against Terra/medium. Only production output
reaches the caller. Shadow attempts/evaluations have distinct role identifiers,
spend and sampling provenance. They cannot replay side effects or consume
production retry allocations. Phase 4 may implement bounded, read-only shadow
comparison after explicit sampling, privacy and budget configuration.

## Evals and activation

Routing evals normally specify an acceptable envelope: allowed model/effort
pairs, forbidden tiers, mandatory rationale/validation and cost constraints.
For example, deterministic simple math may allow Luna or Terra while forbidding
Sol and Astra. Hard constraints use deterministic graders.

Before production v1, at least 100 cases must represent every family, threshold
boundaries, budgets, tool/provider failures, long context, escalation, and
must-not-use-Astra cases. Compare policy versions on the same cohort and report
uncertainty, success and cost together. Runtime policy never rewrites itself.
The [dedicated pre-Phase-1 eval corpus](../evals/README.md) now supplies independent
envelopes and deterministic grading of hypothetical observations. It does not
implement or demonstrate a working router.
