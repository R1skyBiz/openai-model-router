# Phase 1 completion report

Phase 1 implements deterministic embedded routing. Phase 2 has not begun.
The approved policy YAML and authored evaluation oracle are unchanged from
`f42ecc9615de547528de7cbc00a2624649140f57`; the architecture baseline is
`f3e8c70bdb10ef76ca81289cea5ebe26368f291d`.

## Implementation and ownership

The root froze shared contracts, integrated reviewed files, implemented the
canonical selector/validation/readiness and eval projection, resolved review
findings, and owns the final commit and push. Four Sol High subagents were used:

| Agent | Responsibility | Workspace / branch |
| --- | --- | --- |
| config | Strict schemas, YAML loader, reference validation; later config review fixes | `/private/tmp/model-router-phase1-config`, `codex/phase1-config`; assigned review fixes in root |
| feasibility | Capabilities/context, trusted limits, Decimal cost and budget evidence | `/private/tmp/model-router-phase1-feasibility`, `codex/phase1-feasibility` |
| candidates | Matching, floors/modifiers, ordered candidate construction; reused for eval harness tests | `/private/tmp/model-router-phase1-candidates`, `codex/phase1-candidates`; harness in root |
| independent_review | Read-only adversarial audit of the integrated tree | Root checkout, no implementation ownership |

Root integration uses `main`. Workers did not commit or independently change
shared contracts, policy YAML, accepted baseline ADRs, or expectations. Reviewed
owned files were copied into the root; there were no Git merge conflicts.
Integration corrected typed-loader optional defaults in matching and local
source-path handling for the offline CLI/subprocess tests.

Files added:

- `src/model_router/core/{__init__,contracts,configuration}.py`
- `src/model_router/policy/{__init__,loader,capabilities,budgets,costs,modifiers,validation}.py`
- `evals/phase1_adapter.py`, `evals/run_phase1.py`
- `tests/test_phase1_{contracts,config,candidates,feasibility,routing,boundaries,eval_adapter,review_config}.py`
- `docs/phase-1-interfaces.md`, this report, and ADR 0010.

Files updated: `src/model_router/router.py`, `README.md`,
`docs/{architecture,configuration,implementation-spec-v1,integration}.md`, and
`evals/README.md`. The independent grader, interchange schemas, cases, positive
and negative observations, contract manifest, and all four configuration files
remain byte-identical to the approved baseline.

The API is
`route(request, classification, environment_snapshot, policy_bundle) -> RouteDecision | RouteRejection`.
Contracts are frozen Pydantic records with strict integer/boolean/money inputs;
configuration is recursively frozen and content hashed. The loader rejects
unknown fields, duplicate keys, incompatible efforts, unresolved references,
invalid component/band definitions, inconsistent bounds, and validation cycles
or understated inherited levels. Enabled evaluator definitions require an
explicit score scale. Loading is not policy activation.

Selection recomputes all seven components, filters capabilities/context and hard
bounds, applies configured rules/floors, considers synthetic health and required
charges, and selects deterministically from jointly feasible candidates.
Model tier and effort remain independent. Preferred waivers expose rule IDs and
blocking constraints. Certified price/funding/access alternatives precede a
blocked preview; shared approval/validator gaps do not increase generation tier.
The nearest-prior fallback clarification is recorded in [ADR 0010](decisions/0010-phase-1-deterministic-core.md).

Costs use isolated Decimal arithmetic, evidenced cache buckets, strict long-context
thresholds, and required evaluator/domain/tool charges. Hard-budget admission
also checks the cache-miss outcome; cache evidence never guarantees a future hit.
Incomplete quotes have a
null total and explicit unknown components. Quote identifiers hash the actual
rates/fees and retain model pricing versions and token assumptions. Decisions
include configuration/environment provenance, synthetic status, readiness
blockers, and deterministic correlation IDs. Raw request content is excluded
from normal serialization; no execution or transport is implemented.

## Evaluation and tests

| Check | Result |
| --- | --- |
| Total independent corpus | 179 |
| Phase-1-applicable | 142 |
| Passed / failed | 142 / 0 |
| Explicit future-phase skips | 37 |
| Applicable must-not-use-Astra cases | 113 / 113 passed |
| All corpus cases explicitly forbidding Astra | 131; the other 18 require recovery execution |
| Requested score-boundary cases | 17 / 17 passed |
| Pytest suite | 343 passed, including all original 85 tests |
| Authored positive grader fixtures | 27 / 27 accepted |
| Intentionally invalid grader fixtures | 19 / 19 rejected (CLI exit 1 as expected) |
| Configuration tests | Strict loading, registry/effort references, cycles, bounds, nullable charges, active static prerequisites |
| Dependency tests | Static import direction plus fresh-process forbidden-import and network-call guards |
| Oracle integrity | Byte comparison against approved Git baseline |
| `git diff --check` | Clean at final verification |

Boundary values: 19/20/21, 39/40/41, 59/60/61, 74/75/76, 87/88/89, 99/100.
Tests run offline without `OPENAI_API_KEY`. The adapter is tested with a poisoned
expected envelope and altered runtime evidence, and the original grader grades
the actual observations. No expectation was changed to accommodate routing.

Reproduce with `uv run --offline pytest` and
`uv run --offline python evals/run_phase1.py`. Optional report/observation paths
are documented in the README; generated files under `evals/results/` are ignored.
The current machine's existing uv/runtime/cache were reused, with no dependency
downloads. Source checkout paths are explicit in subprocess/CLI verification.

## Exact skipped cases

Every case with supplied classification and no recovery scenario was attempted.
No additional case was skipped.

| Case ID | Reason |
| --- | --- |
| `classify_transform` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_extract` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_conversation` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_writing` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_knowledge` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_analysis` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_math` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_engineering` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_research` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_coding` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_debugging` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_architecture` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_planning` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_data_analysis` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_tool_workflow` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_agentic` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_cross_repo_refactor` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_long_horizon_program` | Phase 2: no supplied classification; requires a classifier adapter. |
| `classify_multi_system_change` | Phase 2: no supplied classification; requires a classifier adapter. |
| `quality_effort_success` | Phase 3: requires execution of a scripted recovery trace. |
| `quality_tier_success` | Phase 3: requires execution of a scripted recovery trace. |
| `quality_exhaustion` | Phase 3: requires execution of a scripted recovery trace. |
| `quality_insufficient_budget` | Phase 3: requires execution of a scripted recovery trace. |
| `provider_timeout` | Phase 3: requires execution of a scripted recovery trace. |
| `provider_rate_limit` | Phase 3: requires execution of a scripted recovery trace. |
| `provider_outage_fallback` | Phase 3: requires execution of a scripted recovery trace. |
| `provider_no_safe_fallback` | Phase 3: requires execution of a scripted recovery trace. |
| `tool_timeout` | Phase 3: requires execution of a scripted recovery trace. |
| `tool_api_error` | Phase 3: requires execution of a scripted recovery trace. |
| `alternate_tool` | Phase 3: requires execution of a scripted recovery trace. |
| `unsafe_tool_replay` | Phase 3: requires execution of a scripted recovery trace. |
| `malformed_diagnose` | Phase 3: requires execution of a scripted recovery trace. |
| `validation_diagnose` | Phase 3: requires execution of a scripted recovery trace. |
| `unknown_diagnose` | Phase 3: requires execution of a scripted recovery trace. |
| `terminal_budget` | Phase 3: requires execution of a scripted recovery trace. |
| `terminal_capability` | Phase 3: requires execution of a scripted recovery trace. |
| `evaluator_infrastructure` | Phase 3: requires execution of a scripted recovery trace. |

## Independent review and resolution

The independent reviewer reported issues beyond the passing corpus. The root
fixed them and added targeted regressions:

- Prefer a verified primary candidate over an account-unknown preview.
- Prefer a fully priced feasible alternative over unknown long-context pricing.
- Validate the complete runtime rationale registry and derived effort support.
- Bind quote provenance to actual rates and fees, not environment labels.
- Enforce declared required cost buckets and static active-live prerequisites.
- Reject unresolved domain-validator references and keep domain fees separate.
- Block side-effect execution until authorization/orchestration exists.
- Keep fallback/baseline rationale faithful to the selected candidate source.
- Preserve known funding shortfalls even when another charge is unknown.
- Reject validation inheritance that understates the required level.
- Enforce false-only evaluator infrastructure/always-evaluate policy boundaries.
- Attribute funding shortfalls to the required charge that crosses the balance.
- Preserve degraded-health rationale for a selected fallback.
- Use read-only mappings that cannot be mutated through dict base methods.
- Check cache-miss costs for hard-budget admission while retaining expected quotes.

Root integration also isolated Decimal precision/rounding/traps and retained
all required profiles when validation is strengthened. The final independent
Sol High recheck found no remaining Phase 1 blocking or material correctness
findings. It independently confirmed 343 passing tests, 142 passing applicable
evals, unchanged approved YAML/oracle, non-circular grading, clean diff checks,
and the dependency boundaries.

Remaining boundaries are intentional: no calibrated success model, classifier,
provider calls, retries/tools/validator execution, active health probes, database,
HTTP endpoint, telemetry transport, shadow execution, or dashboard. Synthetic
readiness is not production activation or permission to dispatch. Domain binding
registry and real execution/authorization remain future-phase work. Projection
privacy tests prove allowlisted field/content exclusion, not a future transport's
ability to redact arbitrary secrets in arbitrary metadata.

## Git delivery

The final implementation commit contains this report. Its SHA, push result, and
verified working-tree status are reported in the delivery response, avoiding a
self-referential commit hash in the tracked document. Worker branches/worktrees
remain available for audit; the integrated commit is made only after independent
review and final offline verification.
