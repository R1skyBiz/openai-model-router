# Paid classification and routing preview

`POST /v1/classify-route` accepts a raw task, invokes the admitted live classifier
once, and returns a deterministic routing decision or rejection. LEO can record
what the router would choose while continuing its existing application behavior.
This repository change does not integrate LEO or enable adaptive routing.

| Surface | Input | Provider work | Scope |
| --- | --- | --- | --- |
| `/v1/route` | Request + supplied Classification | None | `route` |
| `/v1/classify-route` | Request + required idempotency key | One classifier only | `classify_route` |
| `/v1/execute` | Existing bounded execution body | Admitted task execution | `execute` |

The `route` scope never authorizes paid classification. Authentication precedes
paid-preview readiness and admission. Application identity comes from the bearer
credential; omit `request.application_id`. Caller environment objects and unknown
body fields are rejected. Task/trace IDs and normal Request facts are accepted.

## Request and retained result

```json
{
  "request": {
    "task_id": "leo-shadow-001",
    "trace_id": "leo-trace-001",
    "input": "Summarize the task supplied by the application.",
    "requirements": ["text_input", "text_output"],
    "consequence": "low",
    "context": {"input_tokens": 100, "expected_output_tokens": 256}
  },
  "idempotency_key": "leo-shadow-001"
}
```

The response includes `purpose=classify_route_preview`, server preview ID,
application and task/trace IDs, status, classification (including prompt/schema
provenance), classifier version/configuration hash, classifier invocation evidence,
usage, reservation, actual cost/completeness/settlement, and release/policy/catalog/
pricing versions, exact release SHA, activation ID, and account-evidence ID.
`route` contains the existing RouteDecision or RouteRejection.
For a decision, model, effort, validation requirements and rationale codes are in
that object. Its `executable` field is the canonical router's readiness evidence;
this endpoint always stops without generation, validation execution or tools.

A completed preview returns HTTP 200, including a deterministic route rejection.
HTTP 422 with retained preview evidence means admission or classification failed.
HTTP 409 with retained evidence means work is in progress or needs reconciliation.
An idempotency payload/key/task conflict returns a sanitized 409 error. HTTP 413 rejects a body larger than the server input allowance before JSON decoding;
HTTP 429 means the finite retained-preview record allocation is exhausted. HTTP 503
means readiness or storage is unavailable; retry only the identical scoped key.
`GET /v1/previews/{preview_id}` uses `classify_route` scope and returns only the
caller's retained preview, or 404. It performs no classifier work.

Use one stable key (1–256 characters, nonblank) for each logical preview. Identical
retries return retained evidence without another paid call, including after restart.
Correlation IDs are excluded from the payload hash; duplicates return the original
IDs. Changed request facts or raw input conflict. Keys and task IDs are scoped by
application. Never switch keys to recover uncertain paid work. A started intent or
accounted result interrupted by a crash requires operator reconciliation against
provider and budget evidence; this release has no automatic replay or reconciliation
command. Unknown cost is null and holds its full reservation, never zero.

## Accounting and privacy

Admission uses a server-owned conservative input allowance, classifier output cap,
finite application/task allocation and finite timeout. Client token/cache estimates
cannot lower the classifier reservation. Stricter client task cost/deadline limits
are honored. Usage is priced with exact decimal arithmetic against the pinned
catalog and persisted before settlement, once per invocation. The returned model ID
and service tier must match the pinned standard tariff; missing or mismatched
evidence retains usage with unknown cost and holds funds. Unknown usage stops
the preview; no route is returned until cost is complete.

Preview records live in `routing_previews`, and spend in budget reservations with
allocation suffix `:classify-route`. Inspect the scoped preview GET for exact usage
and cost; operators can query these tables for aggregate preview spend. Previews
never enter production task/attempt/outbox tables or dashboard KPI denominators,
including success rate, first-pass success, effective cost per successful production
task and generation escalation. Policy/catalog/pricing snapshots are retained.

Raw input and provider text/structured output are excluded from ordinary DB
serialization, journal, logs, outbox, telemetry and dashboard. Safe normalized
classification and route evidence are retained. Do not put task content or secrets
inside caller-supplied task/trace IDs; those correlation IDs are retained.

## Operator composition and local development

[The LEO example](../config/releases/leo-shadow-v1.yaml) authorizes only
`classify_route` and health. It supplies a $0.05 total preview allocation and $0.01
per-preview ceiling, a 100-record retained preview allocation, concurrency 2, and
disables generation execute. All retained states count toward the record cap; rejected
requests cannot create unlimited free records. No automatic destructive pruning or
quota reset occurs. Its zero
hashes/private paths deliberately cannot activate. It is an example of the
composition shape, not current account-access evidence.

Starting from an operator-owned verified release with an active classifier, create
a new immutable composition (never modify historical releases):

```sh
uv run python scripts/compose_leo_preview.py \
  /absolute/path/to/verified-release.yaml \
  .release/leo-shadow-v1/release.yaml
```

This reads existing evidence and writes a new composition. It makes no paid calls,
does not refresh stale evidence, and does not activate. If the pinned evidence is
expired, obtain fresh operator-approved evidence separately and create a new version.

Provision a dedicated random LEO bearer token of at least 32 bytes using the
operator's secret manager; do not commit it or paste it into task messages. Supply
it as `LEO_ROUTER_TOKEN`, and set this nonsecret environment mapping:

```sh
export LEO_ROUTER_APPLICATION_CREDENTIALS_JSON='{"leo":{"token_env":"LEO_ROUTER_TOKEN","scopes":["classify_route","health"]}}'
```

Use the existing release CLI `migrate`, `preflight`, `activate`, and `serve` with the
new composition, a dedicated database URL and journal path. Migration 0004 is
required. Set `RUN_LIVE_OPENAI_TESTS=1` only when the operator deliberately enables
live runtime; the provider key must match current pinned account evidence. Key
presence alone is insufficient. Health and activation explicitly report
`paid_classifier_enabled`; the legacy `live_execution_enabled` flag still describes
generation execution. Keep local development bound to loopback. Backup
before migration; rollback requires stopping the service and exporting retained
preview/accounting evidence before dropping the preview table.

Once activated, send the body above to the local server with
`Authorization: Bearer <dedicated LEO token>`. This request is paid. For development
without spending, run `uv run pytest tests/test_classify_route.py`; all classifier
transport there is stubbed, and the ordinary suite requires no OpenAI key.

The whole-body ingress read also has a finite timeout (`preview_body_timeout`,
HTTP 408); it releases the service concurrency slot without claiming paid work.
The returned-tier check follows the [official Responses API contract](https://developers.openai.com/api/reference/python/resources/responses/methods/create):
`default` requests standard processing, and the response reports the tier actually
used. Any tier outside the pinned standard tariff remains unpriced by this preview.
