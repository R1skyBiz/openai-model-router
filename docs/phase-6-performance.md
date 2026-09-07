# Phase 6 local operating envelope

The frozen targets in [Phase 6 interfaces](phase-6-interfaces.md) were evaluated
with `python scripts/load_release.py`: eight concurrent application requests,
80 executions, and 1,000 synthetic retained tasks for analytics. Calls use the
application bearer boundary, shared engine, SQLite durable allocation, journals
and outbox. The activated-route row measures the shipped release; mock execute
uses injected dependencies and does not measure live evidence-refresh overhead.
All model results are deterministic mocks. Provider time is effectively
zero; these are local adapter/storage overhead measurements, not OpenAI latency.

| Operation | P50 ms | P95 ms | Throughput / second |
|---|---:|---:|---:|
| Route preview (injected mock composition) | 10.78 | 19.33 | 663.59 |
| Activated route-only release | 10.93 | 14.48 | 712.26 |
| Mock execute | 101.10 | 759.39 | 40.21 |
| Task retrieval | 15.06 | 19.67 | 525.39 |
| Idempotent duplicate | 12.56 | 45.71 | 455.36 |
| Telemetry summary, 1,000 tasks | 623.43 | 673.10 | 1.59 |
| Dashboard task query, 1,000 tasks | 618.08 | 662.29 | 1.60 |

All frozen thresholds passed: route/retrieval P95 below 250 ms, telemetry P95 below
2 seconds, mock execution above 2 tasks/second. Exactly 80 provider invocations
occurred across 80 original plus 80 duplicate requests. The retained outbox had
560 events. Raw harness output is generated at `evals/results/phase6-load.json`.

Peak RSS increased by 172,703,744 bytes (~165 MiB), including constructing and
loading the 1,000-task analytics dataset. This is a peak-allocation observation,
not a steady-state leak or long soak test. Telemetry reconstructs task evidence;
its roughly 0.65-second scan and SQLite serialized writes are the observed
bottlenecks. Do not extrapolate this run to large tenant histories or high traffic.

The supported initial envelope is one service process, at most eight active
actions, modest retained datasets, and one local journal filesystem. PostgreSQL
provides cross-process transactional allocation/task/outbox coordination; it does
not make the current analytics scan or journal a multi-host design. An outbox
backlog at the configured ceiling blocks readiness. No external broker is needed.

Failure evidence is supplied by deterministic backend tests: database write loss
and journal reconciliation; started-attempt restart without replay; duplicate
claims; concurrent budget exhaustion; outbox leasing; stale/unavailable health;
evaluator outage without intelligence escalation; deadline exhaustion; and unknown
usage holding reservations. These cases use controlled faults rather than paid
provider failures. See [the Phase 6 report](phase-6-report.md) for final counts.

Live operation has a further narrow envelope: standard text, V0 checks, bounded
input/output, one classifier invocation, finite retries/deadline/allocation and
fresh externally supplied account evidence. It stops when evidence expires.
Continuous automatic provider probing and long-running production certification
are outside this candidate's verified scope.
