# ADR 0016: Paid classification and routing preview

Status: Accepted for the explicitly authorized LEO shadow routing support boundary.

Add `POST /v1/classify-route` with the distinct `classify_route` application scope.
It admits one bounded classifier invocation, settles its measured cost, passes the
unchanged classification to the canonical router, and returns retained evidence.
The composition has no generation, tools, evaluator, recovery, or shadow executor.
`POST /v1/route` continues to require a supplied classification and performs no
provider work. `POST /v1/execute` retains its existing contract.

Store preview evidence in `routing_previews` (migration `0004_routing_previews`),
separate from production tasks, attempts and outbox. This makes exclusion from
production success, first-pass success, cost per successful task and generation
escalation metrics structural. Preview evidence and its scoped budget reservations
remain inspectable independently. Preview requests do not emit production events.

Reuse explicit release activation, immutable policy/catalog/pricing snapshots,
current credential-bound account evidence, finite time/input/output limits and
transactional SQL budget authority. A key alone enables nothing. The preview
allocation is separately named `<allocation_id>:classify-route`; it does not reset
on process restart or token rotation. In a mixed deployment it is a separate
finite allocation from execute. LEO's composition disables execute entirely.

Claim an application-scoped key before reserving. Reserve a conservative input and
output upper bound, persist started intent, then dispatch once with SDK retries
disabled. Persist measured usage/cost before settlement. Unknown cost holds funds.
Retained claimed, started, accounted or uncertain work is never automatically
replayed, including after a crash. An accounted record interrupted before final
routing requires operator reconciliation; safety takes precedence over automatic
completion. A duplicate returns retained evidence, with its original correlation
IDs. Task IDs also cannot be reused under a new key within an application.

Bound the entire HTTP body before decoding and enforce a finite per-allocation
preview-record cap transactionally, including rejected requests. Reject stale caller
policy versions before paid work. Retain exact release SHA, activation and account
evidence references on every preview. Require returned model and service tier to
match the pinned tariff before settling cost as known.

Raw task content exists only in memory and in the existing non-storing classifier
transport. Storage retains hashes, correlation IDs, limits, classifier provenance,
usage, cost, and deterministic route evidence. No raw content enters journals,
logs, outbox, telemetry, or the production dashboard. No routing policy, oracle,
model preference, validation rule or adaptive-routing mechanism changes.
