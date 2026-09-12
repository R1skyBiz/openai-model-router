# LEO integration handoff

Baseline: `ff4dc2d`. Scope: application integration inside the Model Router
repository only. No LEO repository access or remote push.

## Reused

Core request/classification/route/preview/task contracts; bearer authentication
and application scopes; existing free and classifier-only preview endpoints;
bounded execution, durable idempotency, validation/recovery/accounting; existing
health snapshots and content-free task/preview lookup.

## Added

Async `RouterClient`, environment configuration, strict response/correlation
validation, safe error classes, explicit connect/whole-operation timeouts,
bounded safe retries, mock/live mode checks, authenticated composition reporting,
and a server check of the expected-mode execution header. Defaults remain
preview-only shadow behavior. Added a public generic FastAPI example and
placeholder configuration; updated the old urllib example to use the client.

## Files changed

- `src/model_router/client/{__init__,client,models}.py`: application client and wire projections.
- `src/model_router/http_contracts.py`: shared envelopes and integration status.
- `src/model_router/service/{app,auth}.py`: reuse envelopes, scoped status endpoint and dispatch guard.
- `examples/{http_client,fastapi_integration}.py`, `examples/.env.example`: consuming-app examples/configuration.
- `pyproject.toml`, `uv.lock`: HTTPX declared directly; locked dependency versions unchanged.
- `tests/test_integration_client.py`, `tests/test_integration_example.py`: 66 new offline cases.
- `tests/test_phase1_boundaries.py`: permits HTTPX only in the new client boundary.
- `tests/test_calibration_export_intake.py`: constructs the existing synthetic PEM marker from string fragments; same runtime fixture/assertion. This fixes a pre-existing release secret-scan false positive without excluding the test or weakening the scanner.
- `README.md`, this handoff, `docs/integrations/leo-integration-readiness.md`: integration documentation.

## Validation

- Targeted client/example/service/auth/preview/boundary suite: **134 passed**.
- Packaging and affected synthetic intake regression checks: **87 passed**.
- Final complete Python regression suite: **1008 passed, 5 skipped** (66 new cases).
  Skips: one explicit live-provider check and four opt-in PostgreSQL checks.
  Six existing dependency deprecation warnings remain.
- Offline wheel build, installed-wheel client import/HTTP smoke outside the
  checkout, locked dependency check and whitespace check: **passed**.
- Protected configuration/corpus diff and preserved-report hashes: **unchanged**.

The initial full run exposed packaging subprocess cache configuration and a
pre-existing synthetic PEM source-scan false positive. Packaging was rerun with
an explicit populated cache/uv path, without network access or packaging changes.
The final full run passed with provider credentials/live opt-ins and the
PostgreSQL test URL removed from the environment.

Reproduce the full suite with a populated offline uv cache:

```sh
env -u OPENAI_API_KEY -u RUN_LIVE_OPENAI_TESTS -u RUN_LIVE_CALIBRATION \
  -u POSTGRES_TEST_DATABASE_URL UV_CACHE_DIR=/path/to/populated/cache \
  MODEL_ROUTER_UV=/path/to/uv /path/to/uv run --offline --extra dev pytest
```

Tests cover previews, execution, authentication, malformed responses, budgets,
transport/whole-operation timeouts, cancellation, safe retry limits, exact
idempotency preservation, provider failures, validation/recovery metadata,
health interpretation, mode distinction, credential redaction, trace propagation,
concurrent previews/execution, structured output and legacy schema compatibility.
Live-client behavior is exercised against mocked HTTP only.

## Compatibility and remaining blockers

The baseline OpenAPI comparison proves all existing path/schema definitions are
unchanged; only `/health/integration` and its response schema are added. Old
request-envelope imports continue to work. New-client execution requires the new
server health endpoint and dispatch guard. No policy, thresholds, model catalog,
calibration corpus/statuses or canary configuration changed. The two pre-existing
untracked reports remain untracked and preserved.

No live readiness or model-quality claim is made. Request-owned tool allowlists,
arbitrary metadata, shadow-evaluation configuration, route reservation/binding,
remote cancellation and durable raw-output lookup remain unsupported. Such
fields fail rather than being silently ignored. Existing release health may lack
fresh provider-family evidence, which the client reports as unknown. Deployment,
application permissions and any later live activation still need operator review.

## First task in LEO

Add a backend RouterClient lifespan adapter behind a preview-only flag, defaulting
off/shadow. In LEO's own in-process tests, map one existing task to `Request` plus
reviewed application-supplied `Classification`, display the proposal and persist
opaque task/trace IDs. Keep execution disabled until user authorization, budget
policy, tool ownership, result retention and the reviewed router deployment are
agreed. Do not add a direct-provider fallback.
