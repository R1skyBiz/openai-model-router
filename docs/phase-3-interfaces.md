# Phase 3 frozen integration contract

Root owns `core/execution_contracts.py`, lifecycle transitions, orchestration,
validation, final recovery arbitration and embedded `execute`. Workers must use
these types, request any interface refinements centrally, and never alter the
approved YAML or evaluation oracle. All work is offline; production stays blocked.

`execute(request: Request, dependencies: ExecutionDependencies, *,
supplied_classification: Classification | None = None) -> TaskResult` is synchronous.
Dependencies explicitly supply bundle, environment source, provider, classifier,
repository, budget authority, clock, finite limits, trusted execution controls,
V0 check registry and tool executor. No implicit global composition.

States: created -> classified -> routed -> admitted -> running -> validating;
validation leads to succeeded or recovering. Recovery returns through routed /
admitted for generation, or validating for a tool-only retry. Any nonterminal
state may fail/block/cancel. Terminal states cannot transition. Immutable attempt
records are appended when started and replaced only to finalize that same started
attempt; finalized evidence is immutable. Classification is separately accounted.

Task/trace IDs are stable; invocation/attempt IDs are unique. Decisions preserve
initial and recovery quotes. Structured RecoveryAction records are proposals;
root reroutes every target through the policy constraints and admits every action.
Quality uses configured supported effort ordering then configured next-tier effort;
infrastructure has same/lower tier fallback only; tool recovery does not regenerate.
Unresolved diagnostic outcomes terminate with diagnosis evidence and no promotion.

Repository `create` atomically claims scoped hashed idempotency key and request
hash with TASK_CREATED; identical duplicates return existing metadata, conflicting
payloads raise IdempotencyConflict. `save` atomically updates by revision and writes
all linked records plus outbox events. On primary failure `retain_pending` writes a
durable local recovery journal; if both fail, raise a sanitized storage error with
previously persisted started evidence still available. Never admit another action.
Output is in-memory only and excluded from ordinary serialization and persistence.

Worker ownership: recovery package; admission/safety modules; storage/migrations
and telemetry event exports. Root handles lifecycle/orchestrator/V0. Later workers
own service and Phase 3 eval adapter/runner/tests. No worker commits; one root commit.
