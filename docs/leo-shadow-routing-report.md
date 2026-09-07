# LEO shadow routing support verification

Implemented against clean live-verified baseline
`9ab3635fc9a622a3d25f5ebb83d39f1bd46c39b6`.

The authenticated `POST /v1/classify-route` surface performs one admitted classifier
invocation, exact accounting, and deterministic routing. It has a separate
`classify_route` scope and dedicated preview evidence table. The LEO example grants
only that scope and health, with a $0.05 allocation, $0.01 per-preview ceiling,
100 retained records and concurrency 2. The example deliberately contains unresolved
private references; loading an example is not live activation.

The [integration guide](classify-route.md) documents request/response, authentication,
idempotency, cost and usage completeness, privacy, scoped retrieval, operator
composition and local development. [ADR 0016](decisions/0016-paid-classification-preview.md)
records the durable paid-preview boundary and conservative crash recovery.

## Verification

| Gate | Result |
| --- | --- |
| Full offline backend suite | 753 passed; 5 deliberate skips |
| Focused preview coverage | 41 passed, including transport, crash, auth, pricing and KPI regressions |
| PostgreSQL suite, isolated local database | 4/4 passed; includes preview claims, tenant isolation, held reservations, migration/restart and existing execution concurrency |
| Frontend tests | 21/21 passed |
| Frontend TypeScript and production build | Passed |
| Authored corpus | 179/179 passed |
| Phase 4 regressions | 22/22 passed |
| Approved policy and independent oracle | Byte-for-byte unchanged against baseline |
| Historical route-only manifest | Byte-for-byte unchanged; canonical hash preserved |
| Existing private live manifest and activation receipt | Independent reviewer verified hash, canonical manifest and old-receipt compatibility |
| Migration / rollback / installed wheel | Passed, including packaged preview table and modules |
| Wheel, source distribution, clean editable setup | Passed |
| Load harness | Existing release targets passed; historical manifest uses its own pinned-schema database |
| Auth/privacy/source secret checks | Passed |
| `git diff --check` | Passed |

The five default-suite skips are four explicitly opted-in PostgreSQL tests (run
separately above) and the live provider test. No paid call ran for this feature.
The full release command is `scripts/verify_release.py --offline
--skip-frontend-install --uv <uv-path>`. The existing locked frontend dependencies
were reused. Final artifacts were rebuilt after the last source changes.

## Independent review

An independent `gpt-5.6-sol` High review examined the integration and re-reviewed
all fixes. It found no remaining material security or reliability issues.
Resolved findings include finite preview-record allocation and bounded body input,
pre-dispatch stale-policy rejection, returned-model/service-tier tariff binding,
explicit paid-classifier activation/provenance evidence, and finite ingress time
with disconnect/error cleanup. Focused tests cover each correction.

Previews create no production task, attempt or outbox rows. Tests compare production
summary, spend, efficacy and routing results before/after previews and verify one
classifier invocation, no generation/tools/evaluators/shadows/recovery, scoped
retrieval, exact once-only cost retention, and no replay after an uncertain started
call. Unknown tariff or usage holds funds and stops safely. Started or accounted
work interrupted by a crash remains for operator reconciliation; no automatic paid
replay or destructive retention is added.

`POST /v1/route` remains non-paid and requires supplied Classification;
`POST /v1/execute` retains its execution contract. No approved routing policy,
independent oracle, adaptive routing/V2, or LEO repository changes are included.
The baseline's historical live verification is preserved; this feature is verified
offline and still requires current operator evidence and explicit activation before
paid use.
