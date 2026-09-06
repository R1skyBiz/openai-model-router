# Configuration reference v1

Status: Normative document/schema contract; a typed loader is Phase 1 work.

## Ownership and versioning

| File | Owns |
| --- | --- |
| models.yaml | Registry identifiers, ordered tiers, reasoning support, capabilities, context limits, availability, and pricing snapshots. |
| routing-policy.yaml | Objective, taxonomy, component ranges, priors, floors/modifiers, selection/recovery rules, and rationale-code registry. |
| budgets.yaml | Default budget behavior and application overlay schema. |
| validation.yaml | V0–V3 profiles, evaluator bindings, consequence defaults, and sampled shadow settings. |

Paths above are relative to `config/`. Documents define semantics; YAML owns
numeric policy values and tunable defaults. Do not maintain a second policy
table in Python, dashboards, or eval graders. Evals may independently express
expected constraints to detect policy regressions.

Every file has integer `schema_version` and string `status`; each has `version`
except the registry's `catalog_version`. Current files are draft snapshots.
The routing policy references the other version identifiers. Activation records
include the effective overlay, content hashes, and immutable copies of all
referenced data. Activated versions cannot be overwritten, including registry
prices. Changing catalog data requires a new catalog snapshot and effective
bundle reference, not an algorithm change. Historical tasks retain old snapshots.
Registry pricing is the initial quote source. Actual invocation tariffs are
separate immutable pricing_versions: a task cannot freeze an external provider's
prices. Refresh pricing facts before paid work, recheck the task budget and
retain a revised quote when needed, without changing the pinned routing policy.

Architecture acceptance does not mean deployment values are calibrated. The
component thresholds for annotation/tool intensity, hard-versus-preferred floor
encoding, cold-start ordering, and consequence mappings are initial v1 policy
choices requiring eval coverage before activation. Null recovery/budget/evaluator
settings explicitly defer operational tuning; they do not authorize execution.

## Field types and validation

- All identifiers, enum values, dates and versions are strings. Scores, tier
  ranks, token counts, retry counts and durations are integers, never booleans.
- Currency amounts/rates/multipliers are nonnegative decimal strings; durations
  and total attempt limits must be positive when supplied. Recovery counters
  may be zero to disable that recovery path. A cost ceiling
  of zero permits no paid work. Use decimal arithmetic, not binary floats.
- Capabilities are true/false/null: supported/unsupported/unverified.
  Missing capability keys mean unverified. Context/output limits must be positive.
- Model aliases and tier ranks are unique. Every candidate/evaluator model must
  exist and every effort must be in that model's configured support list.
- Components have inclusive min/max bounds and sum to the declared total range.
  Complexity bands partition the full integer range without gaps or overlaps.
- A candidate has `model` and a nonempty ordered `efforts` list. Every rule
  has a unique `id`, a structured `match`, and registered rationale codes.
- Unknown fields, invalid enum values, duplicate YAML mapping keys, unresolved
  references, cyclic validation inheritance, and floor/ceiling contradictions
  are configuration errors, not silently ignored data.
- Sampling rate is a number in [0,1]; shadow enablement requires comparison
  bindings and separate finite budget limits. Disabled examples do not execute.
- A declared nullable field may remain unresolved in a draft/preview. Live
  activation must validate fields needed by enabled paths; irrelevant unknown
  tool pricing does not block a plain-text path with fully known charges.

## Model and pricing metadata

The initial aliases and reasoning support follow the approved ladder. On
2026-09-06, the registry's public text pricing, context limits, modalities and
listed features were checked against the official
[Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna),
[Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra),
[Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol), and
[Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) pages.
Each entry embeds its source; `documentation_verified` is not proof of access
for this account. No live probe was performed.

`pricing.version` identifies the exact quote used, with Standard text rates per
`unit_tokens`. Long-context `input_tokens_gt` is strictly greater than the
threshold and its multipliers apply to the full request. Cache-write base rate
is uncached input rate times its write multiplier; long-context cache modifiers
are additional factors on the applicable cache base rate. Unknown cache
composition for Luna/Terra/Sol remains null. Sol's promotional end date is a
minimum availability statement, not an invented future replacement price.

Tool fees, nonstandard service tiers, account availability, image tokenization
and any unlisted model/tool capability need verification when used.
`additional_tool_prices: null` is not “tools are free.”
Unsupported modalities must be filtered. Hosted tool support must be added to
the registry with evidence before that execution path is enabled.

Usage normalization must separate uncached, cache-read and cache-write input
buckets without double counting; output usage includes billed reasoning once.
The provider adapter must verify SDK-specific accounting in Phase 2.
Never assume an expected cache hit is guaranteed for a hard cost ceiling.

## Matching and selection semantics

A rule matches when all supplied predicates match: `families` is membership;
`flags_all` requires every listed boolean flag; `complexity_min` is inclusive;
`component_min` requires each named component at or above its threshold.
Missing flags do not match. The flags describe substantive implementation,
repository-wide scope, multivariable work, consequential multi-system action,
long horizon, and exceptional end-to-end work; classifier/caller provenance
must accompany them. Classifiers cannot smuggle a model choice through flags.

All matching hard floors combine by maximum tier rank. Preferred floors also
combine by maximum rank, but may be waived only if no feasible candidate meets
them after capabilities, context, budgets, validation and health are considered.
Such a waiver records `FLOOR_RELAXED`, rule IDs and the blocking constraints.
Hard floors, capability requirements and mandatory validation never relax.

Candidate construction starts with the matching complexity band, adds explicit
modifier candidates, then adds models at/above an applicable floor when needed.
Existing candidate effort lists remain intact; new candidates use supported
efforts in `floor_candidate_effort_preference` order. Prefer candidates meeting
all preferred floors; explore eligible non-prior models by configured tier rank
when constrained selection otherwise has no candidate. Preserve candidate order
while deduplicating model/effort pairs. Mark non-prior selection with
`CONSTRAINED_FALLBACK`. Baseline complexity alone never forbids a cheaper
constraint-compatible route.

With no calibrated success model, choose the first jointly feasible candidate
and effort using configured order; do not invent probability estimates.
With an explicitly versioned calibration, rank feasible paths by expected total
cost divided by success probability, then the configured tie-break fields.
Zero predicted success is ineligible. Calibration includes recovery/evaluation
cost, uncertainty and provenance; its estimator is a later implementation
decision. The cold-start policy is a transparent prior for the mission, not a
claim to have already optimized observed cost per success.

## Budget overlay semantics

Resolve defaults, then a trusted application overlay, then caller constraints
that may only tighten the result. Application overlays use the documented
allowlist; application identity is a lookup key, never a core code branch.
Tier floors combine by maximum; ceilings by minimum. Finite cost/deadline/spend
limits combine by minimum. Null in an overlay inherits; it never removes an
inherited bound. Requests cannot enable disabled live execution.

Null default task cost/deadline means no configured value, not zero; live
execution still requires a finite task cost ceiling and bounded recovery/deadline
configuration. Null period limit disables that optional aggregate cap. A period
limit requires an explicit period and UTC boundaries.
All paid classification, generation, retries, tools and required evaluation share
the production task budget. Shadow costs use a separately bounded allocation.
Check remaining budget before each action, reserve costs to avoid concurrency
overspend, and stop when exhausted. Output/retry caps must bound exposure;
estimate uncertainty is not permission to exceed a hard limit.

Broader application policy customization is a new versioned effective policy
bundle using the same policy schema, not arbitrary executable overlay code.
Do not loosen required capability, privacy, or authorization constraints.

## Validation and recovery settings

V0 checks run only when applicable. V1/V2 evaluator model/effort, rubric version,
score scale and pass threshold must be configured before required evaluation can
execute. V2 uses an independent call without the generator's self-assessment;
a different model may be configured but is not implied by the label alone.
V3 requires an application/domain validator and may also require V1 or V2.
It is domain specialization, not a guarantee that every V1/V2 check is inherited.

Consequence mappings are initial defaults; overlays can strengthen validation,
evidence, approval and execution restrictions. Generation tier is unchanged by
consequence alone. Required but unconfigured validators/evaluators block
execution; they are not silently replaced by V0.

Recovery counters/backoff parameters currently null must be set and evaluated
in Phase 3. Infrastructure fallback can only use a safe same/lower tier route
meeting all hard constraints; otherwise return a recoverable failure. A separate
new quality/capability finding may cause reclassification, never a timeout alone.
