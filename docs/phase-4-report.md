# Phase 4 validation, health and evaluation report

Phase 4 implements the offline trust and verification layer: independent V1/V2
semantic evaluation, V3 domain bindings, evaluator-only recovery, scoped health
snapshots/circuits, health HTTP endpoints, and bounded shadow comparisons.
Production execution remains disabled. Phase 5 has not begun.

The unchanged independent corpus is executable and passing **179/179**:
142 Phase 1 routes, 19 Phase 2 classifications, 17 Phase 3 recovery cases and
the remaining Phase 4 evaluator-infrastructure case. An additional declarative
suite covers the 22 requested Phase 4 regression scenarios separately.

Approved baselines are architecture `ddbad40`, oracle `282e81d`, Phase 1 `758d5eb`,
Phase 2 `8678dec`, and Phase 3 `f60bdac`. The four approved YAML policy files and
independent cases, grader, schema, vocabulary and fixtures remain byte-identical.

## Multi-agent integration

The root read AGENTS.md, authoritative documents, Accepted ADRs, all prior phase
reports, validation configuration, health architecture, lifecycle/storage and the
remaining authored evaluator case before delegation. The initial `main` working
tree was clean. [Frozen interfaces](phase-4-interfaces.md) preceded worker edits.
[ADR 0013](decisions/0013-phase-4-verification-health-shadow.md) records the durable
phase boundary and isolated accounting/evidence decisions.

| Agent | Model | Owned work |
| --- | --- | --- |
| Root architect/integrator | Existing Astra session settings | Core contracts, operational config, orchestration, accounting, storage migration, integration, review fixes, docs and final commit |
| `validators` (A, then D) | Sol High | Semantic/domain adapters and tests; Phase 4 adapter, combined runner and separate 22-case regressions |
| `health` (B, then E) | Sol High | Scoped health/circuits/probes; narrow HTTP health endpoints and tests |
| `shadow` (C) | Sol High | Bounded shadow execution/validation, isolated allocations and tests |
| `independent_review` | Sol High | Read-only adversarial review of integrated work, findings and final verification |

Three worker slots ran concurrently and were reused for later workstreams. All
worked in the shared main checkout with non-overlapping ownership; no worker
branches/worktrees or commits were created. There were no Git merge conflicts.
The root resolved shared contract and serialization issues centrally. One shadow
file replacement briefly interrupted imports during implementation; the restored
module and its final integration were reverified.

## Validation and evaluator recovery

`ValidationService` uses the existing single-invocation ModelProvider boundary.
`phase4-offline-v1` supplies synthetic model/effort bindings, rubric versions,
score scales/thresholds, input/output/time bounds and finite evaluator retries.
It does not activate or modify the approved routing policy. Config loading checks
model/effort, capabilities, context/output bounds, duplicate keys and finite values.
Only synthetic MockProvider execution is admitted through the orchestrator.

V0 remains the default and checks provider completion, required schema/fields and
registered deterministic checks. V1 invokes a lightweight evaluator; V2 invokes a
separate independent evaluator with task and candidate content, without accepting
a generator self-grade. The evaluator produces only a structured score. It never
selects the generation model. A successful score below its versioned threshold
can establish QUALITY_FAILURE; timeout/outage/malformed/refused/invalid evaluator
responses remain evaluator errors, never generation quality evidence.

V3 requires an explicit application domain registry binding; MockDomainValidator
provides deterministic offline validation. Missing required semantic/domain/V0
bindings block before generation. Required validation does not downgrade for
cost or availability, and high-consequence simple work retains its generation
tier while requiring V2 and approval evidence.

Evaluator attempts retain unique invocation IDs, parent generation ID, model,
effort, policy/catalog/pricing and rubric/configuration provenance, usage and
validation evidence. Started intent precedes dispatch; usage is retained before
budget settlement. Retries consume only the evaluator's configured allowance,
remaining production cost and deadline. They do not regenerate the candidate or
consume generation infrastructure/quality counters. The authored evaluator case
records one Terra/medium generation, evaluator TIMEOUT, `retry_evaluator`, and a
successful final evaluator result, preserving both evaluator attempts.

Production generation and validation subtotals are separate. The task total
includes each evaluator charge once; evaluation records reference their charging
attempt with zero duplicated fee. Missing usage remains unknown, with reservations
held. Evaluator timeouts never extend the task deadline. Domain exceptions also
retain unknown incurred-cost status rather than fabricating zero.

## Health and HTTP readiness

HealthService uses an injected clock and explicitly configured failure windows,
thresholds, cooldown, half-open probe allowance, recovery threshold and freshness.
Snapshots are immutable and identified by content, with component/model/capability,
state, source observation/expiry, sanitized failure count and circuit evidence.
Reads never refresh source observations. Missing, stale or future evidence is
explicitly unavailable; disabled optional components are not fabricated successes.

Provider/evaluator circuits count only normalized infrastructure failures. Tool
failure affects the tool path. Quality and task budget failures neither open nor
refresh provider circuits. Closed DEGRADED paths may remain usable; open and
half-open paths are excluded from ordinary traffic. Cooldown admits only bounded
recovery probes; successful admitted probes close circuits and failures reopen them.
Required infrastructure failures need an explicit safe alternate to remain ready.

Routing consumes the same captured snapshot that persistence retains. Projection
preserves existing model restrictions and applies only stricter health exclusions.
Its freshness bounds use globally required dependencies and usable generation
scopes; stale unrelated evaluator/tool/model evidence remains in the full snapshot
without blocking an otherwise safe generation path. The original router rechecks
all capability, tier, context, budget and authorization constraints on recovery.

`/health/live` is process-only. `/health/ready` returns 200/503 from shared operation
readiness; `/health/components` returns sanitized observations. Each response uses
one captured snapshot and launches no provider probe. Missing health composition
reports execution readiness unavailable. SyntheticHealthSource explicitly seeds
offline observations. The optional probe port requires enablement, authorization,
a positive finite aggregate cap, per-probe upper bounds, finite inspected input
count and adapter-enforced timeout; no live probe or paid canary was run.

## Shadow isolation

Shadow settings still come from validation.yaml and remain disabled in the checked-in
bundle. Tests use explicitly versioned synthetic bundles. Sampling is deterministic
by task ID/hash and seed; both configured stronger and cheaper comparisons are
covered. Privacy opt-in and separate finite task/experiment allocations are required.
Unknown prices, unavailable validation, unsafe routes and requested tools block
shadow dispatch. All tools are conservatively excluded from shadow, including
potentially side-effecting replay.

Shadow generation passes the canonical route constraints, reserves a cache-miss
bound, and executes at most once. Applicable V0 is mandatory; required V1/V2 uses
separate shadow evaluator attempts with no retries. Unsupported V3 shadow validation
blocks that optional experiment before dispatch. Checkpoint and post-outcome deadline/
freshness checks stop further work. Shadow generation and validation costs are
separate, never included in production task total or its retry counters.

Only production output reaches the caller. Shadow results retain pairing, sampling,
model/effort, usage/cost and compatible evaluation evidence for later comparison;
raw content is excluded. Provider usage is retained before shadow settlement.
If optional shadow persistence loses the primary database but the durable journal
works, further shadow calls stop and the production success plus ordered evidence
are journaled for reconciliation. Failure of both retention paths remains a global
storage error. Restart tests verify no blind replay of uncertain started work.

## Persistence and verification

Migration `0002_phase4_verification` adds task-correlated verification evidence for
evaluator attempts/results, domain results, health/circuit snapshots and shadow
pairing. It extends the existing SQLite transaction/outbox and journal semantics.
Finalized evidence, pinned configuration, prior collections and cost attribution
are immutable. Phase 3 migration/restart/journal/idempotency checks remain green.

| Check | Result |
| --- | --- |
| Full pytest | 614 passed; 1 intentional live-provider skip |
| Phase 1 runner | 142/142 |
| Phase 2 runner | 19/19 |
| Phase 3 runner | 17/17 recovery; historical combined 178/178 applicable |
| Phase 4 remaining authored case | 1/1 |
| Phase 4 combined runner | 179/179 |
| Frozen grader over complete emitted observations | 179/179 |
| Additional Phase 4 declarative regressions | 22/22 |
| Positive / negative grader fixtures | 27/27 accepted; 19/19 rejected, expected exit 1 |
| Empty database migrations, restart and evidence reconciliation | Passed |
| Default network guards and dependency boundaries | Passed |
| YAML/TOML and typed config validation | Passed |
| Repository skill validator | Passed |
| Approved policy/oracle byte integrity | Passed |
| Whitespace and full diff audit | Passed before commit |

Tests run offline without an API key. The live test remains intentionally skipped;
checked-in production, shadow and live-probe defaults remain disabled. The only
known warnings are the existing Starlette/httpx and AnyIO deprecations.

## Independent review and remaining limits

The independent reviewer identified material cases beyond the passing corpus.
Fixes preserve trusted model restrictions, prevent snapshot reads from extending
freshness, correlate decisions/responses with one retained snapshot, isolate
unrelated stale health scopes, and bound V0 shadow work at every check. Root review
also added mandatory shadow evaluation, cache-miss reservations, evaluator-model
availability, configuration immutability, cumulative shadow evidence accounting,
usage-before-settlement and production-success journal reconciliation regressions.
The independent Sol High reviewer reports **no material blockers after fixes**,
confirmed by a final exact-tree 614-test pass, all phase runners, combined corpus
and separate regressions.

Offline scores demonstrate execution semantics, not live evaluator quality or
calibrated thresholds. Production authorization, external tariff refresh,
cross-process durable budgets/health, domain-specific adapters, live quality
measurement and interrupted-work reconciliation remain release gates. Health
circuits and shadow allocation authorities are local; restart retains evidence
but does not automatically restore or replay paid work. No dashboard, adaptive
routing, cross-provider execution or Phase 5 work was added.

## Git delivery

The root makes one integrated commit after final review and pushes origin/main.
The completion response records its SHA, push result and working-tree status;
this tracked report avoids a self-referential commit hash.
