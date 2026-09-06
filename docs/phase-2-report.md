# Phase 2 completion report

Phase 2 is complete: a constrained classifier, a single-invocation OpenAI
Responses adapter, scripted mocks, and independent conformance/evaluation tests
are implemented. The independent review has no remaining blocking or material
correctness findings. Phase 3 has not begun. Production execution and checked-in
live evaluation settings remain disabled; no paid canary or classifier eval ran.

Approved baselines:

- Architecture: `f3e8c70bdb10ef76ca81289cea5ebe26368f291d`.
- Independent oracle: `f42ecc9615de547528de7cbc00a2624649140f57`.
- Phase 1: `971f08386bf23ae9370bc51c1851a4162e9e86d7`.

## Multi-agent ownership and integration

The root read the authoritative contracts, inspected the approved runtime and
oracle, verified a clean checkout, checked current official Responses/SDK
semantics, and froze the [shared interfaces](phase-2-interfaces.md) before
parallel work. Workers and the independent reviewer used Sol with High reasoning.
The root retained its session model settings; no root model override was made.

| Workstream | Owned work | Worktree / branch |
| --- | --- | --- |
| A: classifier | Classifier, prompt, schema/config validation and tests | `/private/tmp/model-router-phase2-classifier`, `codex/phase2-classifier` |
| B: provider | OpenAIProvider, MockProvider and provider tests | `/private/tmp/model-router-phase2-provider`, `codex/phase2-provider` |
| C: conformance | Independent SDK/public-client fixtures and contract tests | `/private/tmp/model-router-phase2-conformance`, `codex/phase2-conformance` |
| D: eval integration | Classification projection, runner, scripts and eval tests | `/private/tmp/model-router-phase2-evals`, `codex/phase2-evals` |
| Independent review | Read-only adversarial review after integration | Root checkout; no implementation branch |
| Root | Core contracts, live guards, dependency, integration, review fixes and docs | Root checkout, `main` |

Workers did not commit. The root integrated owned files and resolved interface
refinements centrally; there were no Git merge conflicts. Worker editing tools
stalled during initial work and were restarted using shell writes; this affected
elapsed time, not ownership or verification. Worktrees remain available for audit.
The phase boundary is recorded in [ADR 0011](decisions/0011-phase-2-classifier-provider-boundary.md).

## Classifier

`OpenAIClassifier` and `MockClassifier` implement the core-owned Classifier port.
They return the unchanged Phase 1 Classification inside a result with classifier,
prompt, schema and configuration provenance, plus provider evidence when invoked.
The strict Pydantic wire schema derives families, seven bounded components and
boolean scope flags from the pinned configuration. Unknown fields, families,
flags, invalid confidence and out-of-range components are rejected. Subclass is
null because the approved policy has no subclass vocabulary.

The wire schema excludes model, tier, reasoning effort, validation level,
component total and provenance. The prompt describes task properties; it neither
solves the task nor embeds score-to-model bands. Trusted adapter code assigns
provenance. Phase 1 independently validates components and recomputes their total;
low confidence does not directly escalate the route. Invocation IDs are unique
across classifier instances, while mock classifications remain deterministic.

Default configuration is `classifier-v1.0.0`, prompt `task-properties-v1`, schema
`classifier-schema-v1`, with Luna/low and live use disabled. Prompt, schema,
configuration and bundle hashes accompany provenance; configuration bindings are
rechecked against forged copies. The paid eval uses a separately versioned config
and frozen prompt under `evals/phase2_data/`. Configuration loaders reject unknown
or duplicate fields and unsafe prompt references without echoing raw values.

All 19 authored seeds run through MockClassifier and the unchanged grader:

| Measure | Deterministic result |
| --- | --- |
| Total seeds | 19 |
| Overall envelope | 19/19 |
| Family envelope, including forbidden families | 19/19 |
| Seven component envelopes | 19/19 |
| Required flags | 19/19 |
| Confidence/provenance schema | 19/19 |
| Paid/live classifier evaluation | Not run |

Eight authored seeds allow multiple families: `classify_transform`,
`classify_extract`, `classify_engineering`, `classify_research`,
`classify_debugging`, `classify_architecture`, `classify_tool_workflow`, and
`classify_agentic`. These are authored allowances, not measured live uncertainty.
The scripts are keyed by task content and contain neither case IDs nor expected
envelopes. Poisoned-oracle tests establish that expectations do not drive output.
These passes demonstrate adapter/schema conformance, not live family accuracy
or calibrated component quality.

## Provider and accounting

The core-owned synchronous API is
`ModelProvider.execute(ProviderRequest) -> ProviderResult | ProviderFailure`.
Only `execution/openai_provider.py` imports the official OpenAI SDK. Dependency
`openai>=2.54,<3` is locked to 2.54.0. Current semantics were checked against the
[Responses API reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create),
[Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs),
and the installed SDK's public response types/accessors.

Text requests use `responses.create`; structured requests use
`responses.with_raw_response.parse(text_format=...)`. The SDK constructs the
strict API schema and validates generated content. Capturing the HTTP envelope
before SDK parsing preserves response IDs and incurred usage when parsing fails;
this does not parse freeform classifier JSON.

Preflight checks pins, configured alias/provider identity, capability, effort,
output bounds and representable timeout. A dispatched request makes one call,
with SDK retries disabled, explicit model/effort, truncation disabled, storage
disabled, standard service tier and bounded output/time. No retries, escalation,
streaming, tools or task lifecycle are implemented. Input context overflow is
left to API rejection with truncation disabled, rather than silent shortening.

Normalized evidence retains correlation and configuration IDs, returned model,
response ID/status, timing, refusal/incomplete state and usage when available.
Missing usage remains null. Cache reads and writes remain distinct, disjoint
subsets of input; reasoning remains a subset of output and is never charged twice.
Invalid/inconsistent usage is diagnosed instead of treated as a zero-cost success.
The eval cost helper retains partial evidence and null totals when charges are
unknown. Its conservative text/input allowance is an eval guard, not exact
production tokenization or a budget reservation system.

Failure mapping distinguishes timeout, rate limit, provider outage/connection
failure, malformed output, evidenced capability failure and unknown failure.
Generic client errors are not automatically capability failures. Safe HTTP status,
request ID and bounded numeric Retry-After metadata survive where available;
arbitrary messages, response bodies and headers do not. Poor answer quality is
not a provider failure. Completed output does not establish task success.

MockProvider scripts results, malformed structured content, incomplete outputs,
usage variants, timeout, rate limit and provider failures, including callable
outcomes. It records sanitized requests and fails explicitly on script exhaustion.
Raw input/output is excluded from normal record serialization and repr. SDK/HTTP
logs during invocation are filtered, including first-use SDK debug configuration;
SDK types, credentials and raw exception messages do not enter normalized records.

## Live gates and limits

Default tests remove credentials/live opt-in and block socket access. Independent
conformance includes the real SDK with an in-memory HTTP MockTransport. Live
checks require explicit `RUN_LIVE_OPENAI_TESTS=1`, an environment key, enabled
external settings, current account/pricing attestations and a positive finite
cost cap. The [README](../README.md) and [eval guide](../evals/README.md) provide
exact commands for the one-call provider canary and 19-call classifier eval.
No live account access or tariffs were verified in this phase, and neither paid
path was run. Checked-in settings therefore block them. Production budgets are
unchanged and disabled. Injected SDK clients are trusted composition boundaries;
the low-level provider is not production admission or authorization.

## Regression and final verification

| Check | Result |
| --- | --- |
| Full pytest | 431 passed, 1 explicitly live test skipped |
| Original Phase 1 suite | All 343 tests remain passing |
| Phase 1 routing eval | 142/142 passed |
| Phase 2 classification eval | 19/19 passed |
| Combined executable corpus | 161/179; 18 recovery cases remain Phase 3 |
| Original positive grader fixtures | 27/27 accepted |
| Original intentionally invalid fixtures | 19/19 rejected; expected exit 1 |
| TOML/YAML and typed configuration validation | Passed |
| Repository model-router skill validation | Passed |
| Dependency boundaries and default network guards | Passed in full suite |
| Phase 1 runtime integrity | All original source files byte-identical to Phase 1 |
| Policy/oracle integrity | Four approved YAMLs, cases, grader, schemas and fixtures unchanged |
| `git diff --check` | Clean |

The unchanged Phase 1 runner still reports 37 cases outside its route-only scope;
the separate Phase 2 runner now covers the 19 classification cases among them.
No recovery trace is executed merely because a provider adapter exists.
Generated reports/observations under `evals/results/` are ignored build evidence.
Reproduce with `uv run --offline pytest`, both phase runners, and the grader
fixture commands in the eval guide. SDK dependencies were installed during setup;
verification itself requires neither network nor an API key.

## Independent review and resolution

The independent Sol High reviewer audited the integrated runtime, public SDK
conformance, eval independence, policy integrity and privacy. Root fixes and
regressions resolved the following findings:

- Overbroad capability classification for generic HTTP client errors.
- A Python-side model-prefix registry and insufficient embedded-key filtering.
- Oversized Retry-After values escaping normalization.
- Malformed structured envelopes losing response IDs and incurred usage.
- Unrepresentable timeouts escaping before dispatch.
- First-use SDK debug logging leaking prompts through a newly installed handler.
- Missing external live settings override, detailed eval dimensions and per-call
  evidence, and incomplete paid-eval instructions.

The final review found no blocking or material correctness issue and independently
confirmed 427 passing tests before the final four coverage additions, one live skip,
both phase eval results, positive and
negative grader results, and unchanged Phase 1 runtime/config/oracle. Root also
added malformed usage-shape and cross-instance invocation-ID regressions. Final
diff inspection added explicit SDK timeout/connection/outage and scripted mock
outcome tests; the full suite then passed 431 tests with one live skip.

Residual limits are deliberate: live classifier quality, account access and
current prices are unmeasured; SDK conformance is bounded to the locked version;
privacy tests cover the adapter boundary, not arbitrary future logging handlers
or telemetry transports. Production cost admission, durable eventual telemetry,
recovery, tools, validation execution, persistence, HTTP execution, health probes,
shadow execution and dashboard work remain later-phase responsibilities.

## Git delivery

This report is included in the single integrated Phase 2 commit. The delivery
response records its SHA, push result and verified working-tree status, avoiding
a self-referential hash in the tracked report. Commit and push occur only after
independent review, complete diff inspection and final verification.
