# Independent routing evaluation contract

This pre-Phase-1 contract contains **179 authored cases**, including 56 normal
routing cases and 19 classification seeds. It defines acceptable behavior
before a router existed. The independent offline grader evaluates supplied
observations; it does not route requests, call providers, classify text, run
validators or execute recovery. No API key or network is required.

The approved architecture is pinned at `ddbad40`. See
[ADR 0009](../docs/decisions/0009-pre-phase-1-evaluation-contract.md) for the phase
boundary and [coverage and audit](coverage.md) for the reviewed distribution.
The four approved policy YAML files and authored expectations remain unchanged.
Phase 1 now supplies the separate [adapter](phase1_adapter.py) and
[runner](run_phase1.py): `uv run python evals/run_phase1.py`. It runs all 142
cases with supplied classification and no recovery script, and reports its 37
out-of-scope cases. Phase 2 handles 19 of those separately; 18 require Phase 3.
The original grader and its fixtures remain independent.

## Phase 2 classification

The separate Phase 2 runner executes all 19 classification seeds through a
classifier and projects its actual output into the unchanged independent grader:

```bash
uv run --offline python evals/run_phase2.py --report evals/results/phase2-report.json \
  --results evals/results/phase2-observations.jsonl
uv run --offline python evals/run_local.py --results evals/results/phase2-observations.jsonl --allow-subset
```

Default runs use versioned task-input-keyed scripts from `phase2_data/` through
MockClassifier's strict schema/normalizer. Those scripts contain no expected
envelopes or case IDs, and never read expectations. Poisoned-envelope tests
verify that changing the oracle does not change classifier output. Passing is
deterministic schema/adapter conformance, **not live model accuracy**. Reports
include family-envelope, component-envelope, flag and confidence/provenance
conformance passes; family/score distributions; and all eight authored
multi-family allowances. Phase 1 retains its separate 142-case runner; all 18
recovery scenarios remain Phase 3-only.

For an intentionally paid classifier eval, first verify current account access
and standard text/cache prices and prepare a separate copy of
`config/live-eval.yaml` with those attestations, today's verification date,
`enabled: true`, and a positive finite `max_total_cost_usd`. Supply an API key
through the environment; never put it in YAML. Then explicitly run:

```bash
RUN_LIVE_OPENAI_TESTS=1 OPENAI_LIVE_EVAL_CONFIG=/path/to/reviewed-live-eval.yaml \
  uv run python evals/run_phase2.py --live --report evals/results/phase2-live-report.json
```

The live path uses the separately versioned `phase2_data/live-classifier.yaml`
and its frozen prompt copy. It checks the full 19-call conservative cost allocation
and every prompt/schema input allowance before creating the provider. These
text byte bounds plus configured framing margin are conservative eval allowances,
not an exact tokenizer or production budget admission. It makes one call per
seed with no retry. The report retains model/effort, prompt/schema/config versions,
per-call response/status/usage, and usage-derived costs. Incomplete cost evidence
stays partial with a null total. Default checked-in settings block paid execution;
no account probe is performed to bypass an unknown prerequisite.

## Run

From the repository root, with Python 3.12+ and uv:

```bash
uv sync --extra dev
uv run python evals/run_local.py --coverage
uv run python evals/run_local.py --results evals/fixtures/passing.jsonl --allow-subset
uv run python evals/run_local.py --results evals/fixtures/invalid.jsonl --allow-subset
uv run --extra dev pytest
```

The negative-fixture command **must exit 1**, rejecting every observation. The
positive-fixture command must exit 0. Invalid schemas, missing/unknown/duplicate
IDs, duplicate JSON keys, nonfinite JSON numbers, and changed contract pins exit
2. Without `--results`, the command validates all case rows and corpus references;
it does not claim routing quality. Blank lines and an empty regression file are
permitted, but an empty observation submission is not a pass.

For a future complete router run, omit `--allow-subset`. Every case ID must occur
exactly once. Phase-specific integrations may explicitly use a subset until their
adapters support classification/recovery. Reports must identify that subset.
`--allow-subset` is used for grader fixtures and phase-specific observations.

The Python entry point is
`grade(case, observation, catalog, policy_version, vocabulary) -> list[str]`.
An empty violation list is a pass. `Case` and `Observation` are eval-only Pydantic
types in [schema.py](schema.py); adapters must project future runtime contracts
into these types rather than importing eval types into the routing core.

## Independence and envelopes

Expectations are stored in JSONL, never calculated from the router or configured
band/floor/candidate tables. The grader imports no router, provider, HTTP or
database package. Catalog facts check support and physical limits; a frozen
vocabulary checks enum names and component bounds. Neither generates a route.

Most cases accept several model/effort pairs. A formatting case can admit Luna
or Terra while forbidding Sol and Astra. Adjacent boundary cases can share an
envelope: they test independently justified invariants, not YAML candidate rows.
Narrow pairs are appropriate when constraints or scripted sequencing demand them.
Envelopes do not test every cold-start ordering detail; Phase 1 still needs
configuration and algorithm conformance tests.

Hard capabilities, physical context/output limits, supplied tier/cost bounds and
authored hard-floor expectations must hold. Preferred floors can relax only when
no preferred candidate is feasible; those cases require `FLOOR_RELAXED`, the rule
ID, and blocking constraint evidence. Higher consequence strengthens validation
and approval separately from generation. Low confidence does not justify Astra.

There are **27 explicitly authored passing observations** and **19 deliberately
corrupted observations**. They test the grader; they are not router outputs.
The negative Astra/none observation proves rejection of an unsupported effort.
Historical [regressions.jsonl](cases/regressions.jsonl) remains reserved for actual
bugs; adversarial policy cases are not labeled historical regressions.

## Routing validity and execution readiness

`routing_result: valid` describes the initial decision; `execution_readiness:
blocked` means that decision cannot currently dispatch. Examples include missing
V1/V2 bindings, a missing V3 validator, approval requirements, unknown required
prices, or uncertain account access. Unknown all-in charges produce `partial` or
`unavailable` cost with a null total, never a zero total.

Impossible capabilities or conflicting hard bounds produce `rejected`, no model,
and a typed failure. All permitted models being unhealthy requires a recoverable
rejection. Those cases allow `PROVIDER_FAILURE` or `UNKNOWN_FAILURE` pending the
precise adapter mapping, with explicit health evidence. They do not permit an
unhealthy route or confuse unavailability with poor reasoning.

Recovery observations retain the **initial** routing result and readiness and
carry a separate ordered trace. A final budget failure after escalation is in
that trace, not a retroactive rejection of the initial valid route. Rationale
codes in this projection are the union of relevant decision/trace codes.

## Files and synthetic inputs

| File | Purpose |
| --- | --- |
| `cases/*.jsonl` | Behavioral cases by category; recovery uses escalation.jsonl. |
| `fixtures/manifest.json` | schema_version, architecture_commit, policy_version, catalog_version, pricing_snapshot and sha256 map of approved config paths to content hashes. |
| `fixtures/vocabulary.json` | families, components (names to maxima), flags and rationale_codes; no selection tables. |
| `fixtures/environment.json` | Synthetic baseline; no live account/readiness claim. |
| `fixtures/passing.jsonl`, `fixtures/invalid.jsonl` | Known positive/negative observations. |
| `schema/case-v1.json`, `schema/observation-v1.json` | Exported JSON Schema. Strict Pydantic validation and cross-record audit are authoritative. |

The baseline is `offline-v1`. Case overrides recursively merge object keys;
scalars, lists and null replace baseline values. This is fixture composition,
not budget overlay merging. Trusted application overlays use the documented
budget semantics separately. IDs are opaque; all behavior is in overlay data,
including a renamed-identity comparison.

The baseline declares a fixed UTC clock, fresh healthy models and **synthetically
verified** access, a finite $10 task/remaining budget, a 30-second deadline, bounded
recovery and mock V0. V1/V2/V3 bindings are unconfigured. These are test inputs,
not operational defaults or activation of the draft live configuration. Supplied
classification is free. Tool descriptors do not themselves incur a fee; an
invoked required tool with unknown charges needs the relevant pricing override.
No real tool is invoked.

Baseline fields are `schema_version`, `id`, `synthetic`, `clock`, `catalog`
(repository-relative metadata path), `pricing_snapshot`, `health`, `budget`,
`validation`, `recovery`, `tool_charges`, and `telemetry`. Their nested fields are:

| Section | Fields and semantics |
| --- | --- |
| health | snapshot_id, observed_at, valid_until; models maps aliases to state, account_access, usable. on_event can map aliases to scripted future states. |
| budget | remaining_usd, task_cost_ceiling_usd, task_deadline_ms, live_execution_enabled; remaining_after_initial_usd can specify recovery funds. |
| validation | V0–V3 map to configured_mock/unconfigured. required_evaluator_cost_usd supplies synthetic evaluator cost; requested_profile strengthens validation. |
| pricing | Optional required_tool_charge_usd; null means unknown. |
| latency | Optional minimum_next_action_ms and source; a synthetic bound, not calibrated prediction. |
| telemetry | raw_prompt_storage, raw_response_storage, durable_retention booleans. |
| recovery | max_total_generation_attempts, max_quality_escalations, max_infrastructure_retries, max_tool_recoveries, max_elapsed_ms, initial_backoff_ms, max_backoff_ms. |

Money is represented by nonnegative decimal strings; durations are milliseconds.
Fixtures are inputs for future adapters, not an implemented snapshot loader or
execution service.

## Version 1 case fields

Every record is one JSON object on one line. Unknown typed fields are rejected.
Optional defaults below apply when omitted. Null differs from missing evidence.
The runner audits references, bounded components, duplicate inputs and feasible
envelopes in addition to the strict Pydantic schema.

| Field | Meaning / default |
| --- | --- |
| schema_version | Required integer 1; booleans are not versions. |
| id | Required unique, stable, nonempty identifier. |
| category | Required routing, classification, constraint, recovery, health, budget, context_cache, validation, overlay, or anti_overrouting. |
| description | Required human-readable behavioral scenario. |
| basis | Required contract reference and/or independent reason. |
| tags | Required coverage-label list, possibly empty. boundary marks controlled score perturbations. |
| request | Required normalized task input below. |
| classification | Required supplied facts for routing; null for classification seeds. |
| environment | Required synthetic input selection below. |
| scenario | Optional scripted recovery input; otherwise null. |
| expected | Required independently authored envelope below. |

### Request and classification

| Field | Meaning / default |
| --- | --- |
| request.input | Required synthetic task text; never a telemetry field. |
| request.consequence | low/moderate/high/critical; low is the default for explicit offline fixtures, not live ingress. |
| request.requirements | Capability keys, default text_input and text_output; unknown keys deliberately test rejection. |
| request.context.input_tokens | Nonnegative total input, default 1000. |
| request.context.expected_output_tokens | Nonnegative output allowance including billed reasoning, default 1000. Never add reasoning twice. |
| request.context.cached_input_tokens, cache_write_tokens | Disjoint input buckets, default 0; sum cannot exceed input. |
| request.context.cache_evidence | Default false; without evidence claimed cached input is charged uncached. |
| request.constraints | Caller Limits object, default empty. |
| request.application_id | Optional opaque application key, default null. |
| request.approval_evidence | Approval supplied, default false. |
| request.side_effecting_tool, idempotency_evidence | Side-effect and safe-replay facts, both default false. |
| classification.task_family | Required configured family. |
| classification.components | Required full map of seven bounded integer components. Names/maxima are in vocabulary.json; total is their sum. |
| classification.confidence | Required number in [0,1]. |
| classification.flags | Configured boolean scope flags, default empty. Missing flags do not match. |
| classification.provenance | Nonempty source/version, default eval-author-v1. |

Limits have the same shape in caller constraints and trusted overlays:
`model_tier_floor`/`model_tier_ceiling` are nonnegative numeric tier ranks;
`task_cost_ceiling_usd` is a nonnegative decimal string; `task_deadline_ms` is a
positive integer; `live_execution_enabled` is boolean. Every field defaults to
null (inherit). Contradictory limits are valid *case inputs* for rejection tests,
not accepted production configuration. Caller limits only tighten trusted limits.

### Environment and scenario

| Field | Meaning / default |
| --- | --- |
| environment.snapshot | offline-v1 by default; must resolve to the baseline. |
| environment.health_scenario, budget_scenario | Coverage labels, healthy/ample by default. Labels never drive behavior. |
| environment.overrides | Recursive synthetic health/budget/validation/pricing/latency/telemetry patch, default empty; no executable expressions. |
| environment.application_overlay | Nullable trusted Limits object. |
| environment.application_overlay_version | Required immutable reference when an overlay exists; otherwise null. |
| scenario.initial_route | Required {model, effort} pair for the script. |
| scenario.events | Required ordered injected event labels. |
| scenario.limits | Explicit synthetic counters, durations and/or decimal budget strings; never production defaults. |

### Expected envelope

| Field | Meaning / default |
| --- | --- |
| routing_result | Required valid/rejected/not_applicable. Classification seeds use not_applicable. |
| acceptable_model_efforts | Allowed {model, effort} pairs; nonempty for valid routes, empty otherwise. Their aliases form the acceptable-model set, avoiding duplicate model lists. |
| forbidden_models | Explicit forbidden aliases, default empty. |
| minimum_tier, maximum_tier | Optional inclusive rank bounds, default null. |
| validation_profile | Required V0–V3 for valid routes, null otherwise. |
| required_rationale_codes, forbidden_rationale_codes | Required-subset/disjointness checks, default empty lists. |
| expected_failure | Exact normalized failure or null, default null. |
| acceptable_failure_types | Alternative normalized failures for unresolved mappings, default empty; mutually exclusive with an exact failure. |
| execution_readiness | Required ready/blocked/not_applicable; rejection is always blocked. |
| cost_status | Required known/partial/unavailable for valid routes; null otherwise. |
| expected_recovery | Ordered expected trace, default empty. Must accompany a scenario. |
| checks | Independent evidence/cost/hard-constraint assertions, default empty. |
| acceptable_task_families, forbidden_task_families | Classification-family envelopes; accepted families are required for seeds. |
| flags | Required classification flag values; omitted flags are unconstrained. |
| component_envelopes | Inclusive [min,max] for all seven classification components. Approximate author judgments, not measured classifier outputs. |

A recovery step has `failure` (normalized type or null), `action` (nonempty label),
`route` (pair or null), `validated` (whether the preceding attempt's acceptance
check completed), and optional `original_failure` (default null). Completed
validation can fail; `stop_success` means it passed. The action's route is the
next route, or the completed route for success. Original failures survive
reclassification/budget transitions. Missing, extra, reordered or changed steps
fail. Exact sequences intentionally test ordering without implementing recovery.

Actions currently cover increase_effort, increase_tier, stop_success,
stop_attempts, stop_budget, retry_backoff, health_aware_fallback,
recoverable_failure, retry_tool, alternate_tool, stop_reconcile, diagnose, stop,
and retry_evaluator. Scenarios use explicit finite recovery limits.

Each check has `path` (dot-separated observation object keys), `op`, `value`
(JSON), and `why` (independent reason). `eq` requires matching type and value;
`contains`/`excludes` require a list containing/not containing the exact item;
`between` takes inclusive two-element decimal-compatible bounds. Missing paths
always fail, including missing null/false expectations. Decimal comparisons
reject booleans/nonfinite values and never round an unknown charge to 0.

## Observation fields and evidence

| Field | Meaning / default |
| --- | --- |
| schema_version, case_id | Required version 1 and evaluated case ID. |
| policy_version | Required pinned version; latest is not accepted. |
| routing_result, execution_readiness | Required separate initial statuses. |
| selected_model_alias, model_tier, reasoning_effort | Nullable alias/rank/effort; valid routes need all three. Catalog facts independently verify identity and support. |
| validation_level | Nullable V0–V3; valid routes require a profile. |
| rationale_codes | Default empty; valid routes require nonempty registered codes. Includes recovery rationale in scenario projections. |
| failure_type | Initial rejection failure or null. |
| estimated_cost | Null for non-routes; otherwise status, amount and currency (USD default). Known requires a decimal amount; partial/unavailable requires null. Quotes include the required path; unknown evaluator/tool charges preclude a known total. Partial subtotals belong in additional facts. |
| classification | Same shape as case classification. Routing observations preserve supplied facts; classification seeds contain hypothetical classifier output. |
| recovery | Ordered steps with the trace shape above, default empty. |
| facts | Extensible JSON evidence map, default empty. Only explicitly asserted facts affect grading. |

Current fact assertions cover `complexity_score`, `required_capabilities`,
`violated_constraints`, `retryable`, `floor_waiver_rules`,
`floor_waiver_constraints`, `blockers`, `unknown_charges`, `cache_read_tokens`,
`approval_required`, `execution_restrictions`, `telemetry_fields`,
`secret_redacted`, `effective_limits` (Limits keys), `backoff_ms`, and
`failure_source`. Lists use membership checks; booleans/counts/limits use typed
equality or explicit numeric bounds.

Future adapters must derive facts from real decision/constraint/trace evidence.
A fabricated secret_redacted flag cannot prove transport privacy. This is not the
full architectural RouteDecision serialization; event delivery, actual usage,
transport parity and full identifier correlation need later integration tests.

## Adding or changing cases

1. Write a distinct task, classification facts (or seed envelope), explicit inputs
   and an independent contract-based reason. Use a stable ID.
2. Prefer several feasible pairs. Reserve exact pairs for genuine constraints or
   sequence assertions. Never copy a router output into expected data.
3. Require rejection/blocked-readiness evidence where appropriate. Validators
   cannot disappear to fit a budget. Do not assert unresolved latency, classifier
   thresholds or operational retry defaults.
4. Add grader tests for new assertion/failure modes. Keep observations separate
   from cases, and actual regressions separate from adversarial policy examples.
5. Validate cases, positive/negative observations, pytest, coverage and full diff.
   Review duplicates, contradictions, waivers, plausible scores and family/model
   balance. Run `uv run python evals/run_local.py --coverage` to refresh counts.
6. When types change, regenerate JSON Schema using `Case.model_json_schema()` and
   `Observation.model_json_schema()`. For a policy change, retain history, review
   envelopes and explicitly repin a new manifest; never rewrite expectations
   automatically from policy values.

## Phase 3 real recovery execution

```bash
uv run --offline python evals/run_phase3.py --report evals/results/phase3-report.json \
  --results evals/results/phase3-observations.jsonl
uv run --offline python evals/run_local.py --results evals/results/phase3-observations.jsonl --allow-subset
```

This combined runner grades 142 route cases, 19 classification seeds and 17
recovery scenarios: **178/178 applicable, out of 179 authored cases**. Recovery
uses real execute(), MockProvider, deterministic validation/tools, injected health,
budget and clock, and SQLite persistence. Expectations are never read by the
adapter. The unchanged grader consumes resulting observations.

`evaluator_infrastructure` remains explicitly deferred: its V1 evaluator timeout
and retry require Phase 4 evaluator execution. A separate real execute() gate
check verifies that it blocks with zero generation calls. It is never reported
as a passing recovery trace. This honors the prohibition on Phase 4 work.

The authored outage-fallback and alternate-tool scenarios stop at the recovery
choice. The runner also executes the selected follow-on mock action to completion,
retains its full task history, and projects the authored event horizon for the
strict trace grader. Facts expose both that horizon and total recorded actions;
tests verify the actual fallback model and alternate tool dispatches. The corpus,
expected traces, schemas, fixtures and independent grader remain unchanged.

## Phase 4 completion and combined corpus

Phase 3's historical runner retains its explicit evaluator deferral. The new
Phase 4 adapter executes that same authored `evaluator_infrastructure` scenario
through real generation, two independently persisted evaluator invocations and
bounded evaluator-only recovery. Its projections are graded by the unchanged
oracle; all 179 authored cases are now executable through the combined runner.

```bash
uv run --offline python evals/run_phase4.py
uv run --offline python evals/run_phase4.py --combined --report evals/results/phase4-combined.json --results evals/results/phase4-combined.jsonl
uv run --offline python evals/run_local.py --results evals/results/phase4-combined.jsonl
uv run --offline python evals/run_phase4.py --regressions
```

Additional Phase 4 regressions are separate from the 179 authored oracle cases.
They cover semantic/domain acceptance, evaluator outage, health/circuit freshness
and bounded shadow isolation. Default runs remain offline and require no API key.
