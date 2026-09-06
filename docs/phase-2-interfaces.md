# Phase 2 frozen integration interfaces

Root owns the new `core/provider_contracts.py` and `core/classifier_contracts.py`.
All Phase 1 runtime files, four approved YAML files, existing ADRs and authored
oracle files remain unchanged. The Phase 1 import-boundary test will be narrowed
to permit SDK imports only in `execution/openai_provider.py`. No routing semantic
change is approved. Subclass remains null: the approved policy has no subclass
vocabulary, and Phase 1 intentionally rejects any non-null subclass.

## Provider

`ModelProvider.execute(ProviderRequest) -> ProviderResult | ProviderFailure` is
synchronous, non-streaming, one invocation. Contracts are in core; re-export the
port and records from `execution/provider.py`, which also owns `MockProvider`.
`OpenAIProvider(bundle, *, client=None)` lives in `execution/openai_provider.py`.
An injected client implements the official client's public interface. Construct
the real client lazily; always disable SDK retries using `with_options(max_retries=0)`
and honor the request timeout. No automatic retries, retrieval, tools, streaming,
background jobs, lifecycle or routing is introduced.

Validate alias, provider ID, bundle policy/catalog versions, enabled metadata,
text/structured capability, effort, representable timeout and output bounds
against configured output/context limits before dispatch. Exact input tokenization
is not implemented here; API context rejection is preserved with truncation disabled.
No network occurs on import or construction. Real client use requires explicit
opt-in `RUN_LIVE_OPENAI_TESTS=1`; production execution stays disabled. The port is
a low-level building block, not budget admission or a production execute service.
Live eval commands separately gate credentials, finite cost and verified metadata.

Text uses `responses.create`; structured output uses `responses.with_raw_response.parse` with
`text_format=request.output_type` (Pydantic, never an SDK type). Explicit model,
`reasoning={"effort": ...}`, `truncation="disabled"`, `store=False`, output bound,
and timeout are required. Default service tier should be explicit when using
standard catalog prices. Keep all SDK imports in this adapter. Incomplete output
is a result with preserved status/reason, not completed success; the classifier
rejects it. Refusals retain only a boolean, never raw refusal text in metadata.
The raw-response wrapper retains the HTTP envelope before SDK `.parse()` runs:
Pydantic parse errors otherwise discard already-incurred usage and response ID.
Reading that provider envelope is not parsing freeform classifier output. The
SDK still constructs strict Structured Outputs and validates the generated text.

Normalize all token buckets without inventing missing zeros. Cache reads and
writes are disjoint input buckets; reasoning is contained in output. Response
ID/status and returned model survive successful, incomplete and malformed output
where available. Errors are returned records, not raw exceptions: safe cause
codes, validated numeric HTTP/retry-after metadata and sanitized request ID.
No error bodies, arbitrary messages, URLs, headers, SDK objects, or credentials
enter records. Content fields are excluded from repr and normal serialization.

`MockProvider(outcomes)` consumes scripted ProviderResult/ProviderFailure or
callables accepting ProviderRequest. It records sanitized requests/call count
and fails explicitly on script exhaustion; no network and no fabricated success.

## Classifier

`OpenAIClassifier(provider, bundle, config)` and `MockClassifier(outputs, bundle,
config)` implement `classify(Request) -> ClassificationResult | ClassificationFailure`.
The wrapper retains usage on failed validation as well as success, and returns
the unchanged Phase 1 Classification at `.classification`. Export these adapters,
`load_classifier_config(path, bundle)` and `build_output_type(bundle)` from
`classification/__init__.py`. Config loader reads root's `config/classifier.yaml`;
classifier worker owns `config/prompts/task-properties-v1.txt` and may validate
config through its own local type. Config/prompt/schema hashes bind provenance.

Build a strict Pydantic wire schema from configured family/component/flag
vocabulary. All seven components and supported boolean flags are required;
null-only subclass, confidence [0,1], no model/tier/effort/validation/total fields.
Trusted adapter assigns provenance/version; the model cannot author it. The
prompt contains task taxonomy and factual definitions, never routing floors,
model recommendations, or score-to-model bands. Unknown fields, family, flags,
out-of-range scores or malformed structured output return safe diagnostics.
No importing policy candidate selection in classifier; validate vocabulary/ranges
locally and leave sum recomputation and routing to Phase 1.

MockClassifier uses the identical schema/normalization path over scripted mappings
or Pydantic output objects, never expectations. Its outputs are keyed by task
content or scripted order; it must not read eval envelopes. Script exhaustion is
diagnosable. Failed schema validation never echoes raw values in exceptions.

## Work ownership and verification

A owns classification package, prompt file and `tests/test_phase2_classifier.py`.
B owns execution package and `tests/test_phase2_provider.py`.
C owns `tests/test_phase2_conformance.py` and `tests/phase2_fixtures/` only.
D owns `evals/phase2_adapter.py`, `evals/run_phase2.py`, `evals/phase2_data/` and
`tests/test_phase2_evals.py`. D runs after a slot opens; root handles remaining
integration/offline/live guards, docs, dependencies and final verification.
No new fixtures go in the baseline-pinned `evals/fixtures/` directory.

SDK verification on 2026-09-06: installed official openai 2.54.0 exposes
`ResponseUsage.input_tokens_details.cache_write_tokens` and `.cached_tokens`,
`output_tokens_details.reasoning_tokens`, input/output/total. Public
`Responses.parse(text_format=...)` and `OpenAI.with_options(max_retries=0)` were
inspected. Official sources:
[Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[SDK guide](https://developers.openai.com/api/docs/libraries).

Default verification is offline; the optional live canary is explicitly gated
and was not run. Mock results measure
schema/adapter conformance, not model accuracy. All 19 authored classification
seeds get an eval path, while 18 recovery scenarios remain Phase 3-only.
