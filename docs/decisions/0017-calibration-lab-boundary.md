# ADR 0017: Isolated, immutable calibration experiments

Status: Accepted for explicitly authorized v0.2 Calibration Lab Phase 1.

## Decision

Build controlled multi-strategy experiments in `model_router.calibration`, separate
from production execution telemetry, preview records and dashboard metrics. Reuse
the classifier/provider ports, deterministic router, recovery policy and historical
prices; keep experiment admission, grading and evidence in the lab boundary. Fixed
baselines do not classify. No policy activation, adaptation, reinforcement learning
or release publishing is authorized by this boundary.

Freeze corpus/result/manifest/grade/budget contracts before parallel implementation.
Versioned JSONL corpora require explicit privacy and content hashes. A canonical
input excludes task-family hints and all evaluation annotations; all strategies
receive identical content, output constraints, capabilities and deadline envelopes.
Unsupported tools or required production validators are explicit INVALID cases.
The Phase 1 production-equivalent validation implementation is V0. Optional code
fixture execution remains unsupported until a trusted bounded sandbox is provided.

Use separate immutable exclusive run directories and append-only fsynced action
journals. This bounded local experiment store requires no production SQL migration.
Every paid invocation reserves a conservative bound and retains intent before
calling the provider. Started/unknown actions are never replayed automatically.
Experiments are serial within a run. A separate named, locked, fsynced allocation
ledger reserves each run's complete upper bound and retains settled/uncertain cost
across restarts. A rerun has a new ID and cannot reset the same allocation's spend.

Independent graders see opaque candidate labels and task/rubric/output data only.
They do not receive strategy/model/cost/route metadata. Production validation is
separate from calibration grading. Deterministic evidence is authoritative only
when explicitly declared to measure success; disagreement is always retained.
Evaluator outages leave UNKNOWN/NEEDS_REVIEW, never generation quality failure.
Stronger adjudication is optional, sampled and bounded. No judge is ground truth.

Money is Decimal with historical pricing snapshots. Production-equivalent cost
includes classifier (Router only), all generation and required production validation
attempts. Judges/adjudication are experiment overhead. Total experiment spend also
includes every baseline and unresolved outcome. ECPS sums resolved PASS/FAIL costs,
including failed work, and divides by PASS count; unresolved states are separately
reported. Missing costs propagate nulls and halt further paid work.

## Consequences

Reports provide descriptive paired comparisons, observed cheapest passing strategies,
and over/under-routing candidates. They neither claim untested counterfactuals nor
apply policy changes. Small cohorts are explicitly insufficient; confidence intervals
have stated assumptions. Private corpora and generated outputs are ignored and excluded
from source/wheel/container artifacts. Only public sample fixtures are committed.
Raw corpus data lives under an explicit versioned privacy allowlist; persisted
experiment reports retain safe provenance and hashes, excluding task/output/reference/
rubric prose. Explicitly opted-in protected review-output files permit human
adjudication without adding raw content to reports or production telemetry.

Live calibration requires a separate explicit configuration, runtime opt-in, positive
finite aggregate cap, an admissible no-call plan and fresh credential-bound release
evidence. A credential alone does nothing. This implementation phase runs no paid
calibration and makes no claims about routing economics on real workloads.
