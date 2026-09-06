# Coverage and corpus audit

Reviewed 2026-09-06 against architecture f3e8c70. This is an offline contract audit, not a router benchmark.

Total: **179 cases**. **131 explicitly forbid Astra**. Historical regressions remain empty.

## Category

| Value | Count |
| --- | ---: |
| anti_overrouting | 12 |
| budget | 10 |
| classification | 19 |
| constraint | 31 |
| context_cache | 9 |
| health | 8 |
| overlay | 8 |
| recovery | 18 |
| routing | 56 |
| validation | 8 |

## Primary task family

| Value | Count |
| --- | ---: |
| agentic | 12 |
| analysis | 46 |
| architecture | 5 |
| coding | 8 |
| conversation | 6 |
| data_analysis | 5 |
| debugging | 6 |
| engineering | 9 |
| extract | 20 |
| knowledge | 5 |
| math | 7 |
| planning | 7 |
| research | 5 |
| tool_workflow | 16 |
| transform | 16 |
| writing | 6 |

## Supplied task family (routing/scenarios only)

| Value | Count |
| --- | ---: |
| agentic | 10 |
| analysis | 45 |
| architecture | 4 |
| coding | 6 |
| conversation | 5 |
| data_analysis | 4 |
| debugging | 5 |
| engineering | 8 |
| extract | 19 |
| knowledge | 4 |
| math | 6 |
| planning | 6 |
| research | 4 |
| tool_workflow | 14 |
| transform | 15 |
| writing | 5 |

## Complexity band

| Value | Count |
| --- | ---: |
| 00–19 | 41 |
| 20–39 | 29 |
| 40–59 | 60 |
| 60–79 | 16 |
| 80–100 | 14 |
| classification seed | 19 |

## Model envelope

| Value | Count |
| --- | ---: |
| astra | 1 |
| astra/sol | 14 |
| luna | 8 |
| luna/sol | 1 |
| luna/terra | 54 |
| no route | 33 |
| sol | 7 |
| sol/terra | 25 |
| terra | 36 |

## Validation profile

| Value | Count |
| --- | ---: |
| V0 | 135 |
| V1 | 5 |
| V2 | 4 |
| V3 | 2 |
| not applicable | 33 |

## Initial failure envelope

| Value | Count |
| --- | ---: |
| BUDGET_FAILURE | 5 |
| CAPABILITY_FAILURE | 7 |
| PROVIDER_FAILURE/UNKNOWN_FAILURE | 2 |
| none | 165 |

## Recovery step failure

| Value | Count |
| --- | ---: |
| BUDGET_FAILURE | 3 |
| CAPABILITY_FAILURE | 1 |
| MALFORMED_OUTPUT | 1 |
| PROVIDER_FAILURE | 2 |
| QUALITY_FAILURE | 5 |
| RATE_LIMIT | 1 |
| TIMEOUT | 2 |
| TOOL_FAILURE | 4 |
| UNKNOWN_FAILURE | 1 |
| VALIDATION_FAILURE | 1 |
| success | 5 |

## Health scenario

| Value | Count |
| --- | ---: |
| account_unknown | 1 |
| all_unavailable | 1 |
| alternate_healthy | 1 |
| health_ceiling_conflict | 1 |
| healthy | 171 |
| preferred_degraded | 1 |
| preferred_healthy | 1 |
| preferred_unhealthy | 1 |
| stale_snapshot | 1 |

## Budget scenario

| Value | Count |
| --- | ---: |
| ample | 160 |
| caller_cannot_loosen | 1 |
| caller_tightens | 1 |
| cannot_enable_live | 1 |
| conflicting_bounds | 1 |
| cost_ceiling | 1 |
| cost_sensitive | 1 |
| deadline_limit | 1 |
| engineering_minimum | 1 |
| escalation_unfunded | 1 |
| evaluator_unfunded | 1 |
| incapable_under_budget | 1 |
| null_inherits | 1 |
| premium_ceiling | 1 |
| remaining_exhausted | 1 |
| renamed_identity | 1 |
| tier_ceiling | 1 |
| tier_floor | 1 |
| unknown_required_price | 1 |
| zero_cost_ceiling | 1 |

## Boundary coverage

19, 20, 21, 39, 40, 41, 59, 60, 61, 74, 75, 76, 87, 88, 89, 99, 100.

All requested score boundaries are explicit supplied-component cases. Reporting bins above are uniform descriptive bins, deliberately separate from routing priors. The 99/100 cases are labeled synthetic saturation stress inputs; they are not assertions that ordinary prompts deserve maximal component scores. The 89 case forbids Astra through a hard tier ceiling; the 100 case rejects unsupported audio.

Primary-family counts use supplied families for routing and the first acceptable family for classification seeds. Alternative acceptable seed families are reported by the CLI separately and are not double-counted here. Every family has at least three normal routing cases, with multiple model envelopes. Analysis is overrepresented in the total because budget/overlay/recovery cases reuse a neutral comparison task to isolate their variable.

## Audit findings

- No duplicate IDs or exact behavioral inputs; task input, classification, environment, and scenario jointly define the duplicate signature. Adjacent boundaries and overlay identity variants are intentional controlled comparisons, not independent natural-language diversity claims.
- No allowed/forbidden overlaps, impossible tier envelopes, unsupported expected pairs, invalid component ranges, unknown references, or incapable/context-infeasible valid-route envelopes remain. The audit corrected an omitted feasible Sol effort and removed unhealthy preview candidates.
- Expected outcomes are authored in JSONL. No router exists, no policy selection logic is imported, and no band-to-answer table is used by the grader. Numeric cache quote fixtures are independently worked arithmetic with pinned metadata, not expected-route generation.
- Cache checks cover 271999, 272000 and 272001 input tokens. For Luna with 1000 output tokens the independent quotes are $0.0555998, $0.0556, and $0.1106004. The strict-greater-than modifier applies to the full request. At 100000 input and 90000 evidenced cached tokens, the quote is $0.005; without evidence it is $0.0212. Unknown long-context cache-write composition remains partial.
- Astra appears in 15 valid model envelopes (one Astra-only exceptional candidate); 131 cases explicitly forbid it. Simple high-consequence extraction, arithmetic and transformation strengthen V2/V3 and approval without a generation-tier jump.
- Soft-floor waivers require FLOOR_RELAXED, rule IDs and the ceiling that excludes every preferred candidate. Substantive coding and consequential workflow floors are never waived. Repository-wide coding/debugging/architecture and long-horizon agentic preference coverage includes both application and legitimate relaxation.
- Scores describe task facts, not consequences. High precision and ambiguity have dedicated cases. The deterministic high-score example is explicitly constrained. Low-confidence behavior is asserted without inventing an operational confidence threshold.
- Valid/blocked decisions retain their required validation profile. Missing required evaluation produces unknown all-in charges. Synthetic configured evaluator and insufficient-evaluator-budget scenarios remain distinct.
- Recovery traces cover all ten normalized failure types, effort-then-tier ordering, success, exhaustion, insufficient funds, retry/backoff, safe fallback, tool alternatives, unsafe replay refusal, diagnosis and terminal stop. They grade supplied traces; no recovery runs.
- Health has fresh, degraded, unhealthy, alternate, all-unavailable, unknown-account, stale and hard-ceiling scenarios. Unavailability requires a recoverable rejection. Its exact normalized mapping is deliberately an envelope pending the adapter decision.
- No fake historical bugs, real credentials, provider calls, runtime changes, live verification, policy activation or changes to approved configuration were introduced.

## Validation evidence

All 179 case records pass strict schema and cross-record audits. The grader accepts 27 authored positive observations and rejects all 19 intentionally invalid observations. The pytest suite additionally checks adversarial mutations, type failures, missing evidence, CLI exit codes, complete/subset behavior, catalog hard constraints, schema exports, corpus coverage and dependency independence.

YAML/TOML parsing, the repository skill validator and skill-link checks, and git diff whitespace checks accompany the final commit. This evidence does not claim that the future router passes the corpus.

## Open questions and limits

No new Phase 1 blocker was resolved by inventing defaults. Availability failure normalization accepts PROVIDER_FAILURE or UNKNOWN_FAILURE with explicit recoverable health evidence. Calibration, latency prediction, live model access, operational recovery limits, evaluator/domain bindings, and adapter-to-evidence mapping remain at their existing phase gates. Full RouteDecision correlation, provider usage, telemetry transport privacy and delivery require later adapter/integration tests.
