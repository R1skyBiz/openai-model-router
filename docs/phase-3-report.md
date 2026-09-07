# Phase 3 execution and escalation report

The authorized offline Phase 3 scope is implemented. The shared execute engine
supports bounded generation, V0 validation, distinct recovery, durable task/attempt
history, SQLite transactional outbox, idempotency and HTTP adapters. Production
execution remains disabled. Phase 4 has not begun.

The corpus result is **178/178 applicable cases out of 179 authored cases**:
142 routing, 19 classification and 17 real recovery scenarios. The remaining
`evaluator_infrastructure` scenario requires V1 evaluator execution and retry,
which the task explicitly prohibits in Phase 3. Its real execution path is instead
verified blocked before generation. It is an explicit deferral, not a passing
recovery trace or a claim of 179/179 completion.

## Multi-agent integration

The root read AGENTS.md, authoritative architecture/policy/configuration documents,
Accepted ADRs, Phase 1/2 reports and interfaces, implementation contracts and all
18 recovery scenarios before delegation. The initial working tree was clean.
The root froze [Phase 3 interfaces](phase-3-interfaces.md) and
[ADR 0012](decisions/0012-phase-3-execution-persistence.md) before implementation.

| Agent | Responsibility | Model | Workspace |
| --- | --- | --- | --- |
| Root | Lifecycle, shared contracts, orchestration, V0, integration, review fixes, docs and commit | Existing Astra session settings | Main checkout, `main` |
| recovery | Recovery engine; reused for Phase 3 eval projection/runner | Sol High | Shared main checkout |
| admission | Admission, budget ledger, safety, clock; reused for HTTP adapters | Sol High | Shared main checkout |
| storage | SQLAlchemy/Alembic, transactional outbox, journal, evidence/version persistence | Sol High | Shared main checkout |
| independent_review | Separate read-only adversarial review after integration | Sol High | Shared main checkout |

Three worker slots ran concurrently; the independent reviewer started after slots
became available. Workers owned disjoint files and made no commits. No worker
branches or worktrees were created and no Git merge conflicts occurred. Root
resolved shared interface refinements, including the configuration snapshot shape,
centrally. No worker changed the approved policy or oracle.

## Execution and admission

The synchronous embedded API is
`execute(request, dependencies, *, supplied_classification=None) -> TaskResult`.
It is exported from `model_router.execution`. Dependencies explicitly provide the
bundle, environment, MockProvider, optional MockClassifier, repository, budget
authority, clock, finite limits, trusted controls, V0 registry and optional tools.
The existing Phase 2 provider remains one invocation per execute call.

States are created, classified, routed, admitted, running, validating, recovering,
succeeded, failed, blocked and cancelled. Invalid lifecycle transitions fail.
Task/trace IDs remain stable, invocation IDs are unique, initial and recovery
routes are retained, and finalized attempts cannot be overwritten. Dispatch
intent is persisted before invocation; failures and previous spend survive later
success. A pending started record after interruption requires reconciliation,
never automatic replay.

Every generation/tool/check path verifies authorization, applicable action limits,
time and funding before dispatch. Deadlines and trusted environment prerequisites
are checked again after durable intent writes and before individual validation
hooks. Health can change through injected snapshots; application identity,
overlays and execution prerequisites cannot drift under an existing claim.
Recovery targets pass the same router's full feasibility checks through its
optional recovery candidate input. Default route behavior remains unchanged.

Finite synthetic limits bound generation attempts, quality escalation,
infrastructure retries, tool recovery, elapsed time, backoff and task cost.
Caller limits only tighten trusted limits. Null execution limits block. Expected
cache discounts never reduce hard admission below the cache-miss quote. Unknown
cost is not zero: missing actual usage leaves total cost null, retains the known
subtotal and holds the reservation. Exact Decimal accounting sums incurred model,
tool and validation work without erasing failed attempts or small charges.

MemoryBudgetAuthority provides deterministic thread-safe local reserve/settle
semantics; action reservations are idempotent. Provider usage is persisted before
ledger settlement. Ledger errors stop new work while retaining incurred evidence.
Production reservation concurrency is explicitly deferred.

Only MockProvider and MockClassifier execute through the Phase 3 orchestrator.
A supplied classification or deterministic MockClassifier does not incur a model
charge. A live classifier cannot enter through an unadmitted Classifier call;
paid classifier admission remains blocked. The approved low-level Phase 2 OpenAI
adapter and its explicitly opted-in canary remain unchanged. No paid call ran.

V0 validates provider completion, supplied structured schemas, expected fields and
explicit deterministic hooks. Required unavailable hooks block. Quality requires
a failed deterministic check with appropriate source and evidence; validator
infrastructure errors never establish weak generation. Each hook's cost overrun
stops later hooks. Required V1/V2/V3 is never silently replaced by V0.

TaskResult contains normalized status, routes, attempts, validations, tool events,
recovery actions, pinned limits and cost completeness. Raw input/output and tool
arguments are excluded from normal serialization and persistence. Successful
output is returned only in memory/the immediate HTTP response. Duplicate or
restart retrieval cannot recover deliberately unretained content.

## Recovery and evaluation

- Quality: Terra/medium → Terra/high → Sol/medium, with new generation and validation
  at each step. Configured candidate efforts and supported model efforts govern
  proposals; the router rechecks all constraints.
- Infrastructure: retryable failures use bounded backoff/Retry-After or evidenced
  safe same/lower-tier fallback. Non-retryable failures do not get same-route
  retries. No infrastructure path automatically raises model tier.
- Tools: explicit deterministic execution, safe retry, declared authorized
  alternate, or reconciliation stop. Side-effecting alternates require
  reconciliation; an original tool's key does not authorize a different tool.
- Diagnostics: malformed, validation and unknown failures retain observation and
  diagnostic evidence. They cannot automatically promote intelligence.
- Terminal bounds: cost/deadline/attempt limits, unavailable capabilities,
  authorization gaps and unsafe replay produce structured terminal results.

All 17 applicable recovery scenarios run through real execute(), MockProvider,
V0 hooks/MockToolExecutor, synthetic health/budget/clock and SQLite persistence.
The adapter never reads expected envelopes. For the authored outage-fallback and
alternate-tool scripts, the runner executes follow-on work as well, retains its
full history and projects the authored horizon into the strict unchanged grader.
Facts expose both horizon and total action count; tests assert actual dispatches.

## Persistence and service

Migration `0001_phase3_storage` creates tasks, routing_decisions, attempts,
tool_events, evaluations, policy_versions, model_catalog_versions, pricing_versions
and outbox. SQLite is local; portable scalar/JSON records leave PostgreSQL
migration as later deployment work. No analytics/dashboard schema was added.

Task state, child evidence and outbox events commit together with optimistic
revision checks. Policy/catalog/pricing snapshots are immutable. Scoped hashed
idempotency keys claim a request atomically; identical retries return existing
metadata, while conflicts return an explicit error. Cross-scope task-ID collisions
are refused. Task identity, limits and tool replay evidence remain immutable.

If primary completion persistence fails, an fsynced local journal retains safe
evidence for idempotent reconciliation. Shared path locks prevent same-process
journal races; cross-process coordination remains a production gate. If neither
retention path works, execution raises a sanitized storage error and admits no
new work. The previously durable started evidence remains available. Outbox
acknowledgement is idempotent. Tool and evaluation events contain explicit entity
IDs and parent attempt correlation. Transport delivery is deferred.

`service.create_app(dependencies)` provides:

| Endpoint | Behavior |
| --- | --- |
| POST /v1/route | Supplied classification; shared route-only engine; no classifier, generation, tools, retries or evaluators |
| POST /v1/execute | Shared embedded execute engine with trusted server controls |
| GET /v1/tasks/{task_id} | Application-scoped stored metadata; no raw output |

HTTP/embedded parity, sanitized validation/errors, 404/409/422/503 handling,
route-only nonexecution and refusal of caller-supplied authorization are tested.
Deployment authentication remains a production prerequisite.

## Verification and review

Verification uses Python 3.12 and uv offline, with default socket guards and
credentials removed. No dependency or policy update was required.

| Check | Result |
| --- | --- |
| Full pytest | 515 passed; 1 intentional live-provider skip; 2 dependency deprecation warnings |
| Phase 1 routing runner | 142/142 |
| Phase 2 classification runner | 19/19 |
| Phase 3 recovery runner | 17/17 applicable; 1 explicit Phase 4 deferral |
| Combined executable corpus | 178/178 applicable; 178/179 authored |
| Deferred evaluator gate | Blocked; zero generation attempts |
| Positive independent fixtures | 27/27 accepted |
| Negative independent fixtures | 19/19 rejected; expected exit 1 |
| Approved YAML/oracle integrity | Byte-identical; regression test passes |
| YAML/TOML and typed configuration | Passed |
| Empty database migration / metadata parity | Passed |
| Restart, journal, immutable evidence, idempotency | Passed |
| Dependency direction and offline network guards | Passed |
| Repository skill validation | Passed |
| Diff whitespace check | Passed |

The independent reviewer found material gaps beyond the passing corpus. Root
fixed them with focused regressions: failed/conflicting version pins leaving
stale created claims; non-retryable infrastructure retries; validator errors
claiming quality; later hooks running after cost overruns; application/readiness
snapshot drift; post-intent dispatch freshness; missing tool/evaluation event
correlation; extreme finite Decimal accounting; budget-settlement evidence loss;
mutable tool replay admission evidence; aggregate cost regression; and preservation
of earlier validation costs when trusted prerequisites change between hooks.
The independent Sol High reviewer reports **no material blockers in the authorized
offline Phase 3 scope** after rechecking all fixes and independently rerunning the
515-test suite and Phase 1/2/3 runners. Approved configuration, authored cases,
fixtures, schema, grader and Phase 1/2 eval adapters have no diff.

Residual production gates are deliberate: live invocation admission and current
external tariff refresh, authentication, cross-process reservations/journal
coordination, metadata retention policy, automatic recovery of interrupted work,
and deployment packaging. Active health, semantic/domain validators, shadows,
dashboards, adaptive routing and cross-provider work remain unimplemented.

## Git delivery

One integrated root commit contains the implementation and this report. Its SHA,
origin/main push status and final working-tree cleanliness are reported in the
completion response after review and final checks. Phase 4 is not authorized by
this delivery.
