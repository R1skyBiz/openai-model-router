# Live verification evidence — 2026-09-07

Status: **LIVE-VERIFIED v0.1.0-rc1**. Evidence reconciliation completed at
2026-09-07T21:30:28Z against release baseline
`27c295092cf8feca56093cf8d6fcc0b1fbd6a60b`.
No package, GitHub release, container, or public service was published.

## Credential and spend authorization

The operator approved secure creation of a new dedicated **Model Router** key
and explicitly approved a **$1.00 USD aggregate live-verification cap**.
The key is stored in the ignored project `.env.local`; no key or credential
fingerprint is included in this document, committed evidence, or normal telemetry.
The exact injected credential matched the SHA-256 binding in the private account
evidence and passed release preflight. Rotation invalidates that evidence.

**Actual total: $0.0018026 USD**, derived from complete normalized usage for
**10 completed Responses calls**. No cost was treated as zero because it was unknown.
The release used a $0.50 durable allocation, a separate $0.01 classifier ceiling,
and three $0.03 explicit-effort ceilings: combined ceilings **$0.60**, below approval.
The pipeline task ceiling was $0.15. All SDK and operational retries, quality
escalations, tools and shadow execution were disabled.

The existing `release.live.run_canaries` path ran four model canaries and one
classifier→router→provider→V0→persistence task. Its tier-constrained Terra/Sol/Astra
cases selected `medium` through the unchanged router. Those results are retained;
three additional calls through the existing `tests/live/test_openai_canary.py`
verified the requested Terra `none`, Sol `none`, and Astra `low` combinations.
Luna `none` passed in the initial runner. These were deliberate additional checks,
not automatic retries or policy changes.

The separate single `OpenAIClassifier` check used the existing live-eval input,
price and opt-in guards. It followed the release runner, which keeps its four
provider cases and end-to-end case together. No full live evaluation corpus ran.

## Account and model verification

Unrestricted model retrieval at 2026-09-07T19:49:41Z succeeded for all four exact
provider IDs. The first sandboxed retrieval could not establish access; its false
results were not treated as account denials. Fresh account retrieval preceded
activation and the release runner. Metadata visibility and paid execution are
recorded separately.

| Alias | Exact provider ID | Required effort actually exercised | Paid result |
| --- | --- | --- | --- |
| Luna | gpt-5.6-luna | none | completed |
| Terra | gpt-5.6-terra | none | completed |
| Sol | gpt-5.6-sol | none | completed |
| Astra | gpt-6-astra | low | completed |

Both classifier calls used configured Luna `low`. Terra, Sol and Astra also
completed at `medium`. Other documented reasoning efforts were not individually
exercised; public support is not presented as live coverage.

## Per-call accounting

All generation inputs were tiny text requests. Release generations were capped
at 64 output tokens; explicit-effort checks at 16; structured classification at
1,024, including any reasoning tokens. Actual classifier outputs were 113 and 115
tokens. All calls used explicit effort, standard service tier, `store=false`,
disabled truncation, no streaming or hosted tools, and bounded timeouts.

| Call | Effort | Input / output tokens | Actual USD | Provider latency ms | Status |
| --- | --- | --- | --- | --- | --- |
| luna-generation | none | 10 / 5 | 0.000008 | 2478.32 | completed |
| terra-generation | medium | 10 / 5 | 0.00008 | 1333.42 | completed |
| sol-generation | medium | 10 / 5 | 0.00014 | 2651.91 | completed |
| astra-generation | medium | 10 / 5 | 0.00035 | 1635.94 | completed |
| end-to-end-classification | low | 923 / 113 | 0.0003202 | 2455.85 | completed |
| end-to-end-generation | none | 10 / 5 | 0.000008 | 1047.98 | completed |
| standalone-classifier | low | 942 / 115 | 0.0003264 | 1914.58 | completed |
| explicit-terra | none | 10 / 5 | 0.00008 | 2655.01 | completed |
| explicit-sol | none | 10 / 5 | 0.00014 | 1270.44 | completed |
| explicit-astra | low | 10 / 5 | 0.00035 | 2019.20 | completed |

Every call reported zero cached-input, cache-write and reasoning tokens.
The [machine-readable evidence](evidence/live-verification-2026-09-07.json)
retains task/trace/invocation correlation IDs, unique provider response IDs,
normalized usage, cost, latency and policy/catalog references. The current
normalized contract does not retain the provider HTTP `x-request-id`; invocation
IDs provide local request correlation. Raw prompt and output content is omitted.

## Classifier and unchanged routing

The standalone live classifier passed strict Structured Outputs validation:
`transform`, confidence **0.99**, complexity **9**, and all six policy flags false.
Its seven components were reasoning depth 1, step dependency 1, context synthesis 1,
technical precision 2, ambiguity 1, tool orchestration 1, and reliability requirement 2.
Versioned classifier, prompt, schema, configuration and bundle provenance were retained.
The wire schema permits only task properties; it cannot emit a generation model,
tier, reasoning effort or validation selection.

The unchanged Phase 1 engine routed that classification to **Luna / none / V0**,
with `BASELINE_PRIOR` and `LOW_CLASSIFIER_CONFIDENCE` recorded. The latter follows
the existing unresolved confidence-threshold convention; no threshold was tuned.

The end-to-end task is `canary-65d07de1176f41f78870e01aadaac26d` (same trace ID).
Live Luna classification produced `conversation`, complexity 7, confidence 1.0,
seven component scores of 1 and all flags false. The router independently chose
**gpt-5.6-luna / none / V0**, rationale `BASELINE_PRIOR`. Provider completion and
applicable deterministic V0 `provider_success` validation passed. Final status:
**succeeded**, total **$0.0003282**, task latency **4,060.757 ms**.
No model was forced for the end-to-end task.

The route preview retains `period_budget_unverified`; the execution layer
explicitly discharges that placeholder using the scoped durable budget authority.
A valid preview alone is not paid-execution admission.

## Persistence, telemetry and dashboard

The isolated live database contains **5 successful tasks**, **6 provider
invocations**, **37 outbox events**, and **11 settled reservations** (six paid
invocations plus five zero-cost V0 validations). No unknown reservation remains.
The telemetry pipeline subtotal is **$0.0009062**. Standalone live-eval evidence
adds **$0.0008964**, reconciling exactly to **$0.0018026**. Standalone checks do not
create dashboard tasks; their costs must not be mistaken for missing pipeline spend.

The typed telemetry surface and local rendered dashboard were inspected. The
end-to-end nine-step timeline shows classification, route, generation, validation
and success, with correct model/effort, latency, cost and policy references.
All task evidence is `synthetic=false`; no synthetic demo rows were inserted.
There were no shadow invocations or charges. Raw prompt/output fields were absent
from normalized task serialization and the displayed timeline. Secret exclusion
and credential binding were verified without printing either credential value or fingerprint.

The read-only dashboard correctly reports current health as **UNKNOWN**: retained
successful canaries do not establish ongoing production readiness. It rounds small
costs for display; exact amounts remain available in normalized evidence.

## Immutable activation evidence

The shipped route-only manifest and the four approved policy files remain
byte-for-byte unchanged. Local immutable canary snapshots are retained under
`.release/final-live-20260907/`, alongside private credential-bound account evidence,
activation receipt, SQLite database, per-call reports and regression logs.

The candidate uses `router-live-canary-20260907-v1`,
`models-live-canary-20260907-v1`, `budgets-live-canary-20260907-v1`,
`validation-live-canary-20260907-v1`, and `classifier-live-canary-20260907-v1`.
Per-model prices are `<alias>-standard-2026-09-07-canary-v1`.
Account/pricing evidence is `account-pricing-20260907-canary-v1`.
The explicit-effort live tests reference the original `router-v1.0.0` /
`models-v1.0.0` snapshots with identical reviewed standard prices.

New local versions change activation metadata and supply the finite operator
budgets/recovery bounds required for live admission. Route-selection rules,
complexity bands, model preferences, validation semantics and historical prices
were not changed. Candidate preflight passed every check before activation.
No existing activated snapshot was overwritten. Expired health evidence is not
refreshed automatically and does not leave a paid service enabled.

## Public facts reviewed

Official model pages were retrieved on 2026-09-07. Standard short-context input / cache-read / output USD per million tokens agree with the immutable 2026-09-06 catalog:

| Alias | Provider ID | Input / cache read / output | Official source |
| --- | --- | --- | --- |
| Luna | gpt-5.6-luna | 0.20 / 0.02 / 1.20 | [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) |
| Terra | gpt-5.6-terra | 2.00 / 0.20 / 12.00 | [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) |
| Sol | gpt-5.6-sol | 4.00 / 0.40 / 20.00 | [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol) |
| Astra | gpt-6-astra | 10.00 / 1.00 / 50.00 | [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) |

Cache-write charge is 1.25× uncached input. Luna/Terra/Sol support none/low/medium/high/xhigh/max; Astra supports low/medium/high/xhigh/max. The deliberately small live path excludes long context and hosted tools. Sol's promotional availability statement is not a future replacement tariff. No existing snapshot was changed.

The [Responses create reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create) was retrieved; the adapter uses explicit bounded output/time, standard service tier, `store=false`, disabled truncation and SDK retries disabled. Output cap includes reasoning. The [model retrieval reference](https://developers.openai.com/api/reference/python/resources/models/methods/retrieve) was retrieved for account preflight tooling. Public documentation and model-list/retrieve access do not prove a successful paid Responses invocation.


## Final regression and limits

The complete `scripts/verify_release.py` offline gate passed: **712 backend tests**
(4 deliberate skips), **21 frontend tests**, frontend typecheck/build, Phase 1
142/142, Phase 2 19/19, Phase 3 178 applicable cases, Phase 4 1/1, combined **179/179**,
and Phase 4 **22/22** regressions. Positive/negative grader fixtures, configuration,
skill/link/secret validation, SQLite migration checks, package builds and clean
installed-wheel/editable smoke passed. The three skipped PostgreSQL tests then
passed separately against an isolated local PostgreSQL database. The live test
remains opt-in and skipped in offline CI. `git diff --check` passed.

This verifies tiny standard-text Responses execution, structured classification,
V0 and local persistence/telemetry. It does not certify long context, all reasoning
efforts, hosted tools, V1/V2/V3 evaluators, sustained reliability, production scale
or first-application integration. Public tariff limits in the historical catalog
remain explicit. No LEO integration or V2 work began. The next milestone is
first-application integration and production telemetry, beginning with LEO.
