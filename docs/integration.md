# Integration contract — v0.1 candidate

The candidate adds explicit activation and application authentication. The shipped
`route-only-v1` composition enables authenticated route/read/health only. Live
classification and generation require a separate validated release, fresh account
and pricing evidence, activation receipt, and `RUN_LIVE_OPENAI_TESTS=1`.
**RC blocked on live verification.** See [readiness](production-readiness.md) and
[deployment](deployment.md) before operating a service.

## Application developer

### Embedded Python

`model_router.router.route(request, classification, environment, bundle)` is the
same deterministic function used by HTTP. It performs no provider calls. Load a
bundle with `model_router.policy.loader.load_bundle`; use the frozen `Request`,
`Classification`, and `EnvironmentSnapshot` records from `model_router.core`.
The [README example](../README.md#embedded-routing) illustrates these inputs.

`model_router.execution.execute(request, dependencies, supplied_classification=...)`
uses explicit `ExecutionDependencies` for provider, repository, budget, clock,
limits, validation and trusted environment. [The offline composition](../tests/phase3_support.py)
is runnable without credentials. A raw `create_app(dependencies)` is an embedded
adapter, not an authenticated deployment. Use the release CLI for deployment.

### HTTP

Supply `Authorization: Bearer <application token>`. Tokens are injected through
operator environment references, hashed with SHA-256 in memory, and compared in
constant time. Use independently generated tokens with at least 32 bytes. The
server derives application identity and rejects any caller `application_id`.
Application IDs in filters never grant cross-application visibility. Credentials
are resolved at startup; restart the service to rotate or revoke application tokens.

| Endpoint | Scope and behavior |
|---|---|
| `POST /v1/route` | `route`; body `{request, classification}`; preview only, no reservation or provider work |
| `POST /v1/execute` | `execute`; body `{request, classification?, idempotency_key?}`; finite synchronous execution |
| `GET /v1/tasks/{task_id}` | `read`; scoped metadata, no retained output |
| `GET /v1/telemetry/*` | `read`; scoped backend aggregates and paginated tasks |
| `GET /health/live` | Public process liveness only |
| `GET /health/ready`, `/health/components` | `health`; sanitized enabled-operation readiness; never launches paid probes |
| `/docs`, `/openapi.json` | `health`; authenticated API documentation |

The [sample client](../examples/http_client.py) performs a route preview with an
injected token. It never executes a paid task. Route-only requires supplied
classification; the route endpoint does not invoke the live classifier. Execute
may omit classification when an activated admitted classifier is available.
Classification supplies task facts; the independent policy engine selects the route.

HTTP 401/403 means missing/invalid credentials or scope. Invalid input is 422,
missing or inaccessible tasks are 404, conflicting idempotency is 409, and
unavailable dependencies/concurrency admission are 503. A 200 execute response
can contain a failed or blocked task; inspect its `status` and normalized failure.
No async job or streaming contract is offered in this candidate.

Idempotency keys are scoped by trusted application identity and normalized request
digest. Reuse the exact task/trace IDs and payload on retry. A duplicate returns
the retained status without dispatching again. Raw output is deliberately absent
after restart/replay; keep successful immediate output in your application if needed.
Never change keys simply because an invocation became uncertain.

### Costs and validation

`total_cost_usd=null` means incomplete cost evidence, never zero. `known_cost_usd`
is a lower bound. Unknown paid costs retain their full reservation and stop
further live paid work. Generation and classification are persisted separately;
shadow/evaluator accounting retains the Phase 5 definitions. Historical quotes and
actual costs are immutable. Cache discounts never reduce hard live admission.

The live release path supports standard text and deterministic V0 validation only.
V1/V2 semantic evaluators, V3 domain validation, tools, other modalities and shadows
remain available only in explicitly injected offline/test compositions; the release
loader rejects enabling them. V0 checks structural acceptance, not broad semantic
correctness. Higher-consequence requests needing stronger validation fail closed.

## Operator

Follow [deployment](deployment.md) for installation, migrations, preflight,
activation, startup and rollback. `OPENAI_API_KEY` alone enables nothing. Keep
SQLite and journals on durable local storage. PostgreSQL is the transactional
backend for shared application allocations; journal coordination requires a common
local filesystem, so multi-host journal deployments are outside this candidate.

Activation pins the manifest and referenced content hashes. Startup validates the
complete receipt and reruns readiness. Changing files invalidates a running live
composition at its next action boundary. Create a new version and a new receipt;
do not edit activated inputs. Application allocation IDs persist across restarts
and release versions: a new deployment must not silently reset spend authority.

Retention day values document minimum operator retention; automatic destructive
pruning is disabled. Preserve task, allocation, reservation, policy/pricing and
idempotency evidence together in backups. Do not restore an old budget ledger and
resume paid work without reconciling spend since the backup. Uncertain started
attempts are never replayed automatically. Outbox delivery is at least once;
consumers deduplicate immutable event IDs. An external transport/dispatcher is not
shipped; operators use repository claim/ack APIs if exporting events.

The dashboard is read-only and displays retained evidence, not proof of current
provider readiness. The bundled local demo remains loopback-only and synthetic.
The candidate has no browser token-login flow: authenticated dashboard hosting
requires an operator-controlled same-origin credential boundary; do not embed
application credentials into JavaScript assets.

## Policy engineer

Configuration owns model IDs, prices, reasoning support, capabilities, availability
and all routing values. The approved four `config/*.yaml` documents remain draft
and unchanged. A production composition must reference new active versions with
finite limits; never relabel or mutate historical snapshots in place.

For a policy change: copy/version the affected bundle, record the decision in an
ADR, validate references and operational limits, run all independent evals and
regressions, inspect cost/quality envelopes, review the diff, and explicitly
activate the new release. Failed evals are evidence to fix policy or implementation,
not permission to weaken the oracle. See [configuration](configuration.md),
[routing policy](routing-policy-v1.md), and [implementation phases](implementation-spec-v1.md).

To add a future OpenAI model, verify current official model ID, effort and modality
support, context/output limits, price dimensions and account access. Add a new
versioned catalog and acceptable routing envelopes. Run the complete compatibility
suite before an explicitly capped canary. No canary or telemetry observation
modifies policy automatically. Adaptive and cross-provider routing are not included.
