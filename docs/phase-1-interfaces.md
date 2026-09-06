# Phase 1 integration interfaces

The root owns `core/contracts.py`, `router.py`, validation selection and final
selection semantics. Frozen Pydantic records reject unknown fields; model data
and numeric policy ranges remain in configuration. Worker modules must not import
eval schemas. The adapter converts eval input facts into these runtime values.

- Configuration worker owns `core/configuration.py`, `policy/loader.py` and
  `tests/test_phase1_config.py`. `load_bundle(path) -> PolicyBundle` validates the
  entire bundle. `PolicyBundle` exposes immutable mapping properties `policy`,
  `catalog`, `budgets`, `validation`, plus `content_hash`. Mapping values use
  tuples for lists and Decimal for money; no mutable children. It may expose a
  `bundle_from_documents(policy, catalog, budgets, validation)` test constructor.
- Feasibility worker owns `policy/capabilities.py`, `policy/budgets.py`,
  `policy/costs.py`, and `tests/test_phase1_feasibility.py`. Signatures:
  `check_capabilities(request, model) -> Feasibility` includes context;
  `resolve_limits(request, environment, bundle) -> Limits`;
  `estimate_cost(request, model, environment, validation, *, currency) -> CostEstimate`;
  `check_budget(cost, limits, environment) -> Feasibility`.
  Model is the immutable catalog model mapping; validation is
  `ValidationRequirements`. Expected exclusions are structured violation strings.
- Candidate worker owns `policy/modifiers.py` and
  `tests/test_phase1_candidates.py`. `build_candidates(classification, bundle,
  limits) -> CandidatePlan` verifies policy vocabulary and component ranges,
  matches floors/modifiers, and emits ordered deduplicated model/effort pairs.
  Include fallback pairs after the prior/modifier/floor candidates, preserving
  source evidence; the root selects fallback only when necessary.
- Root owns validation/readiness/health assembly, floor waivers, final ranking,
  deterministic correlation, eval projection and harness (a later worker may
  receive a disjoint adapter assignment). No worker changes approved config,
  existing ADRs, eval expectations, or shared runtime records.

Synthetic environment budget facts supply the fixture deployment defaults;
production snapshots cannot enable disabled live execution. Application and
caller bounds tighten these defaults. Remaining-budget/evaluator shortfalls and
known deadline shortfalls remain readiness evidence where a structural preview
is valid, following the independent pre-Phase-1 contract. No code dispatches.

Health exhaustion maps to retryable PROVIDER_FAILURE with
`no_healthy_permitted_path` evidence. No generation quality inference is made.
No confidence cutoff or success probabilities are invented.

Final integration refinements preserve the same ownership: cost estimates carry
actual model pricing versions, token assumptions, and content-derived quote IDs;
the environment's pricing label is supplementary provenance. Decisions expose
environment identity and whether their readiness evidence is synthetic.
Candidate-specific price/funding/access blockers participate in feasibility
before cold-start ordering; shared validator/approval gaps do not raise tier.
Domain-validator fees require a separate explicit fact from evaluator fees.
Evidenced cache reads retain their expected quote; hard-budget admission also
checks a cache-miss quote, exposed in `rationale_details.cache_miss_budget_estimates`.
