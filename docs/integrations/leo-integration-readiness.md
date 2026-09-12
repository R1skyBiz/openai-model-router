# LEO integration readiness

## Inspection before implementation

Baseline: local commit `ff4dc2d`. Inspection found one urllib example
(`examples/http_client.py`), but no reusable Python HTTP client. The existing
`Request`, `Classification`, `RouteDecision`, `RoutingPreview`, and `TaskResult`
contracts own routing and execution data. `service/app.py` supplies request
wrappers. Authentication is opaque bearer authentication with server-owned
application identity and operation scopes in `service/auth.py`.

Existing endpoints:

| Endpoint | Existing behavior |
| --- | --- |
| POST /v1/route | Free deterministic preview using supplied classification; no provider calls |
| POST /v1/classify-route | Explicitly activated, potentially paid classifier-only preview; no task generation |
| POST /v1/execute | Bounded execution, recovery, validation, durable idempotency and accounting |
| GET /v1/tasks/{task_id} | Content-free task lookup; timeline query supplies correlated telemetry |
| GET /v1/previews/{preview_id} | Separate classifier-preview evidence |
| GET /health/live | Public process liveness |
| GET /health/ready, /health/components | Authenticated readiness and cached dependency evidence |

Concrete gaps: no shared async connection lifecycle, transport error taxonomy,
strict response decoding, explicit connect/whole-operation timeouts, bounded safe
HTTP retry policy, consuming-app configuration, or runnable FastAPI integration.
Legacy and release health responses have different shapes and do not uniformly
identify mock/shadow/live composition. Request input is intentionally excluded
from ordinary model serialization and must be restored only at the HTTP boundary.
Structured output needs a transport representation because the core result uses
an internal Pydantic model.

The current API does not accept arbitrary metadata, tool allowlists/tool calls,
or per-request shadow execution configuration. Tool authority, classifiers,
validators and shadow evaluation are server-owned. `requirements` expresses
required capabilities; it is not tool authorization. Context is token accounting;
relevant textual context must be included in `input`. Correlation uses `task_id`
and `trace_id`, plus server decision/attempt/evaluation identifiers. These gaps
must stay explicit rather than being silently discarded or assigned invented
semantics. No routing policy, threshold, corpus, or canary changes are needed.

## Implemented architecture and contract

`model_router.client.RouterClient` is an asynchronous, pooled HTTP adapter.
It uses HTTPX at the transport boundary and reuses the core request, routing,
preview and execution evidence models. Shared envelopes live in
`model_router.http_contracts`; the service still exports the old envelope names.
`ExecutionResult` extends `TaskResult` only for dictionary-shaped HTTP structured
output and convenience properties `selected_route` and `latency_ms`.

A new health-scoped `GET /health/integration` reports composition facts:
`mode` (`mock`, `shadow`, `live`, `route_only`, or `unknown`),
`execution_enabled`, `live_execution_enabled`, `paid_classifier_enabled`, and
`shadow_enabled`. These facts are separate from readiness. Existing health,
routing and execution schemas remain unchanged. The execution endpoint accepts
an optional `X-Model-Router-Expected-Mode` header and rejects mismatched new-client
requests before dispatch. Existing callers without that header retain their
existing behavior. Neither the client nor this endpoint activates a release.

| Client operation | Result / behavior |
| --- | --- |
| `route_preview(request, classification)` | `RouteDecision`; supplied classification, free, no task execution |
| `classify_route(request, idempotency_key=...)` | `RoutingPreview`; explicit potentially paid classification; never generation |
| `execute(request, idempotency_key=..., classification=...)` | `ExecutionResult`; explicit bounded execution |
| `get_task(task_id)` | Retained execution evidence without output |
| `get_preview(preview_id)` | Separately retained classifier-preview evidence |
| `liveness()` | Typed process liveness; no readiness inference |
| `readiness()` | Typed readiness, including valid HTTP 503 not-ready results |
| `integration_status()` | Actual service composition facts |
| `component_health()` | Legacy observations or release readiness projection |
| `database_availability()` / `provider_family_health(alias)` | `HEALTHY`, `DEGRADED`, `UNHEALTHY`, or `UNKNOWN` |

Provider health uses the configured model-family alias. Missing/stale observations
are unknown. Release health lists healthy components but lacks individual provider
expiry; the client conservatively returns unknown provider health for that shape.
These helpers do not make provider probes. Liveness, readiness, enabled operations,
and client intent are separate facts.

Route results expose model alias/provider ID, reasoning effort, rationale codes,
effective limits, cost estimate, validation version, evaluator references,
readiness blockers, policy/catalog versions, task/trace/decision IDs and synthetic
provenance. There is no single universal evaluator version: use the route's
validation version and evaluator references, then execution evaluator attempts'
rubric versions where present. Preview is a proposal, not a reservation or a
promise that execution will choose the same route; execution reevaluates current
health and constraints.

Execution results retain final status and failure, initial/subsequent routes,
generation/evaluator attempts, per-attempt usage/latency/validation, recovery
choices/counters, tool events, shadow evidence, exact decimal costs, known
subtotals and retained reservations. Unknown costs stay `None`. `latency_ms` is
the server task's created-to-updated interval; it is not an HTTP latency metric.
Output is excluded from ordinary model dumps and repr; access `result.output` or
`result.structured_output` explicitly for an authorized user. Idempotent replays
and task lookups can succeed without returning output because raw output is not
retained. Consumers must persist needed results in their own approved store.

## Sequence of operations

1. Create one client per FastAPI lifespan using application-scoped configuration.
2. Check readiness and service composition; display unknown/not-ready honestly.
3. Build a `Request` with stable opaque task/trace IDs, input and context estimates,
   required capabilities, a decimal budget ceiling and a deadline.
4. Supply a reviewed application classification to `route_preview` and display
   the model, effort, estimate, constraints and validation requirements.
5. On an explicit execution action, reuse the request and supply a stable
   idempotency key to `execute`. The client checks composition and sends the
   expected-mode header; the server checks it at dispatch.
6. Inspect task status, failure, validations, recovery and accounting. HTTP 200
   means the router returned a task; it does not mean the task succeeded.
7. Record opaque identifiers in the application's logs/job record. Reconcile
   uncertain completion through `get_task` and the router timeline before any
   deliberate resubmission.

The default client mode is `shadow`: application preview only, with execution
and paid classification prohibited locally. This is distinct from server-owned
shadow evaluation, which may run additional attempts under server authorization.
`mock` permits execution only against a mock composition with no server shadow
or paid-preview composition enabled. `live` permits explicitly requested live
execution only when the service reports live execution enabled. Merely selecting
`live` cannot authorize the server. Paid classifier previews additionally require
`MODEL_ROUTER_ALLOW_PAID_CLASSIFIER=true` and the `classify_route` credential scope.
Mock or preview-only applications must never opt into that flag.

## Configuration and example application

Install the router distribution at the reviewed commit/version in the consuming
application's environment. HTTPX is now a direct, locked dependency; the client
imports no provider SDK and makes no direct provider calls. The distribution
currently includes the wider router dependencies; a standalone SDK wheel is not
part of this change.

Use [`examples/.env.example`](../../examples/.env.example) as the consuming-app
configuration reference. No dotenv loader is implicit: the process launcher or
secret manager supplies these values.

| Variable | Default / meaning |
| --- | --- |
| `MODEL_ROUTER_URL` | `http://127.0.0.1:8000`; remote origins require HTTPS |
| `MODEL_ROUTER_APP_TOKEN` | Required opaque application bearer token, supplied by operator |
| `MODEL_ROUTER_MODE` | `shadow`; alternatives `mock`, `live` |
| `MODEL_ROUTER_CONNECT_TIMEOUT_S` | `2`; explicit connection timeout |
| `MODEL_ROUTER_REQUEST_TIMEOUT_S` | `30`; per HTTP operation wall-clock limit including reads/retries/backoff |
| `MODEL_ROUTER_DEFAULT_BUDGET_USD` | `0.01`; default and maximum client task ceiling |
| `MODEL_ROUTER_SAFE_RETRIES` | `1`; maximum additional safe attempts, bounded to 0–3 |
| `MODEL_ROUTER_ALLOW_PAID_CLASSIFIER` | `false`; separate classifier-preview opt-in in live client mode |

The client fills absent budget/deadline limits and tightens supplied ones to its
configured limits. It preserves every other constraint and capability. Set a
larger configured ceiling deliberately if the application needs larger tasks.
Request deadlines are milliseconds; HTTP timeouts are seconds. Readiness/mode
checks are separate HTTP operations and are not included in the server's task
deadline. HTTP timeout/cancellation does not cancel a possibly running server task.
Use stable configuration for a logical job: changing constraints while retaining
the same idempotency key correctly produces a conflict.

Minimal application code:

```python
from model_router.client import RouterClient, ClientConfig, Request, Classification

async def proposed_route(request: Request, classification: Classification):
    async with RouterClient(ClientConfig.from_env()) as client:
        readiness = await client.readiness()
        if not readiness.ready:
            return {"ready": False}
        proposal = await client.route_preview(request, classification)
        return proposal.model_dump(mode="json")

# In a separate explicitly requested action, using mock or authorized live mode:
# result = await client.execute(request, classification=classification,
#                               idempotency_key=stored_job_key)
# Inspect result.status and result.failure before using result.output.
```

The complete [`examples/fastapi_integration.py`](../../examples/fastapi_integration.py)
uses one client per application lifespan and provides `/router/readiness`,
`/preview`, and `/execute`. Its execution body requires `confirm_execution: true`,
an idempotency key and a request (whose constraints carry the budget ceiling).
It demonstrates success, quality/validation failure, budget rejection, timeout,
provider unavailability and identifier logging. Run with
`uvicorn examples.fastapi_integration:app --port 8001` after supplying the example
environment and composing a separate mock router. Importing the module starts
neither a server nor a provider call. The consuming application must provide its
own end-user authentication and authorization; confirmation is not authorization.

## Error-handling matrix

| Evidence | Client/application handling | Retry / reconciliation |
| --- | --- | --- |
| HTTP 401/403 | `AuthenticationFailure`; fixed safe message | Fix server-side credential/scope; no retry |
| HTTP routing rejection | `RouterFailure`, `failure_type` and local task/trace IDs | Keep constraints; show budget/capability/provider rejection |
| Router HTTP dependency failure | `RouterFailure`, fixed allowlisted code and HTTP status | Only safe operations may retry |
| DNS/connect/read/write failure | `TransportFailure` or `RouterTimeout` | Execution outcome may be unknown; reconcile by stable task ID |
| Whole-operation deadline | `RouterTimeout` | No automatic execution replay; remote work may continue |
| Wrong schema, correlation, content type, or redirect | `MalformedResponse` | Fail closed; no direct-provider fallback |
| Mode mismatch / shadow execution | `ClientPolicyError` or router HTTP 409 | Correct explicit configuration; never relax automatically |
| HTTP 200 with task failure | Inspect `result.failure` and all attempts/validations | Router owns bounded recovery; do not layer automatic task retries |
| Repeated quality failures exhaust attempts | Final `BUDGET_FAILURE/recovery_attempts_exhausted` plus retained `QUALITY_FAILURE` evidence | Example displays validation failure and preserves the terminal failure |
| Preview HTTP 409/422 with preview evidence | Typed `RoutingPreview` with `uncertain`/in-progress/`blocked` status | Never automatically restart; retain reservation/accounting evidence |
| Unknown/partial usage or cost | Preserve null and known subtotal/reservation | Do not report unknown as zero |

Automatic retries are restricted to GET and the free `/v1/route` operation, for
connect errors/connect timeouts/read timeouts or valid retryable HTTP
502/503/504 errors. The total operation timeout includes all attempts and
bounded backoff. Execution and classifier-preview POSTs never retry automatically,
even with an idempotency key. An explicit repeat preserves exactly the supplied
key and request. Keep task/trace IDs unchanged as well; the client rejects a
response correlated to a different job. No retries follow malformed responses,
redirects, authentication errors, rate limits, write errors or caller cancellation.

## Deployment and security boundaries

Use HTTPS and an operator-issued application-scoped bearer credential with only
needed scopes: `route`, `read`, `health`, plus `execute` only for authorized
execution, and `classify_route` only for authorized paid classifier previews.
Never send an `application_id` in the request; the server derives it from the
credential. URLs may not contain credentials, query strings or path prefixes.
The client disables ambient proxy configuration and redirects and leaves TLS
verification enabled. Injected transports are a test seam, not a production
retry bypass.

Keep credentials and router access in the application's backend. The consuming
application needs no OpenAI credential. Avoid raw request/response/header logs,
exception-local dumps, or exporting the client's private HTTP transport. The
client's exceptions contain fixed safe codes, HTTP status and local correlation
IDs, never arbitrary server messages or raw transport errors. Credential fields
are redacted in configuration repr and dumps. No automatic telemetry exporter,
body logging or provider fallback is installed.

Deploy this server change before permitting client execution. Older servers can
still serve free previews, but lack `/health/integration`, so execution fails
closed. A load-balanced deployment must carry the new expected-mode check on all
instances, use one consistent composition per application and share the existing
durable idempotency/budget store. Service-side release activation, account evidence,
finite limits, database migrations and retention remain operator requirements.
Use local in-process ASGI/mock fixtures in development; production live activation
requires its existing independent gates. Mock success is plumbing evidence only.

## Telemetry workflow

There is no additional client exporter configuration. The host application's
logging configuration controls `example.router`. Store task/trace IDs on the
application's job and log decision IDs for previews. Use `get_task(task_id)` for
execution evidence and authenticated `GET /v1/tasks/{task_id}?view=timeline` for
existing task/attempt/evaluation/tool correlation. Paid preview evidence uses
`preview_id` and `get_preview`, remains separate from production telemetry, and
does not establish production ECPS or success. Do not log raw inputs/outputs,
tokens, or idempotency keys. Keep business metadata in the consuming application's
approved job record keyed by opaque task/trace IDs.

## Remaining integration gaps and next LEO task

No per-request tool allowlist, arbitrary metadata, application-chosen classifier,
preview reservation/route binding, or caller-selected server shadow evaluation
has been added. Unsupported kwargs/fields are rejected. Tool authority and
side effects require a separate server-owned composition; capability requirements
cannot express a safe allowlist. Provider readiness is unknown where existing
health responses lack fresh per-family evidence. There is no cancellation
endpoint or durable output retrieval contract. Client errors are not automatic
resubmission instructions.

No live readiness, model quality, savings, or canary-readiness claim follows from
these offline tests. The calibration corpus, policy, thresholds and canary state
are outside this change.

**First task in the LEO repository:** add a backend-owned RouterClient lifespan
adapter and a preview-only feature flag defaulting off/shadow. Use an in-process
mock router in LEO tests to map one existing task into `Request` plus a reviewed
application-supplied `Classification`, display the proposal, and persist opaque
correlation IDs. Add no provider fallback. Keep execution disabled until LEO's
user authorization, tool allowlist ownership, budget policy, result retention and
operator-approved router deployment have been reviewed. This work has not accessed
or changed the LEO repository.
