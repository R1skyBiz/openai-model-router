# ADR 0013: Isolated verification, scoped health and bounded shadow evidence

Status: Accepted for explicitly authorized offline Phase 4 implementation

## Decision

Keep the approved routing policy and independent oracle unchanged. A separate
immutable `phase4-offline-v1` operational configuration binds synthetic semantic
evaluators and health limits. It does not activate the draft production policy.
The orchestrator supplies the existing synthetic readiness facts only when real
configured adapters are bound, and independently verifies every required adapter.
Higher consequence still changes required validation, not generation tier.

V1/V2 invoke ModelProvider independently with a structured score. The evaluator
cannot select generation routes. Each invocation has its own persisted started
intent, usage, rubric/configuration provenance and result. Evaluator infrastructure
retry is bounded per required evaluator per generation, under the production task
cost/deadline; it never regenerates the candidate. Successful below-threshold
assessment alone permits semantic quality recovery. V3 remains an explicitly
bound application-domain adapter, with no invented universal domain validator.

Keep evaluator attempts separate from generation attempts in TaskResult, preserving
the Phase 3 generation counter and ordered history. Semantic evaluation records
reference their charging attempt with zero duplicated charge. Production generation
and validation subtotals reconcile to production total; shadow spend is excluded.

Health uses immutable snapshots over a local scoped circuit service and injected
clock. Only normalized infrastructure failures affect provider/evaluator circuits;
tool failures affect the tool scope. Closed degraded paths can remain usable;
open/half-open and missing/stale required paths are unavailable. Half-open recovery
requires bounded explicitly admitted probes. Snapshot HTTP reads never probe.
Execution gates global retention/configuration dependencies separately from
request-specific model, evaluator and tool paths.

Shadow comparisons read validation.yaml sampling/comparison settings, disabled by
default. Explicitly enabled synthetic experiments use a separate finite task and
experiment allocation, privacy opt-in, canonical feasibility checks, no tools,
no production retries and no caller output. The existing period ceiling has no
calendar duration, so it bounds one allocation for the configuration version's
local ledger lifetime; it must never silently reset on a timer. Durable production
budget authority and cross-process allocations remain Phase 6 work.

Migration 0002 adds task-correlated verification evidence, retaining evaluator
attempts/results, domain results, snapshots/circuit evidence, and shadow pairing
with the existing transaction/outbox and durable recovery journal. Stored started
work remains uncertain on restart and is never automatically replayed. Raw
content remains in memory only. Historical policy documents retain their phase
claims; current status points to the Phase 4 report.

## Limits

Offline passes demonstrate execution semantics and evidence integrity, not live
semantic accuracy or calibrated circuit thresholds. Production execution remains
disabled; external tariff refresh, authorization, distributed reservation/health
state and interrupted-work reconciliation remain release gates. No dashboard,
adaptive policy or Phase 5 work is authorized by this decision.
