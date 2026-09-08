# Calibration Lab

Calibration Lab v0.2 Phase 1 is controlled experiment infrastructure. It compares
ROUTER (normal classification and deterministic routing), TERRA_BASELINE
(Terra/medium), and SOL_BASELINE (Sol/medium) on identical cases. Optional fixed
strategies extend the same contract for future ladder experiments. No execution
here tunes policy or publishes a release. No paid benchmark was run to implement it.

The shared contracts live in `src/model_router/calibration/contracts.py` and
[the frozen interface note](calibration-interfaces.md). The lab uses independent
filesystem persistence, provider/classifier ports, the existing router and recovery
policy, blind deterministic/semantic grading, central economics and JSON/Markdown
reports. There is no production telemetry or dashboard schema change.

## Offline workflow

Run from the repository root after the normal `uv sync --extra dev` setup:

```bash
uv run --offline model-router calibrate validate calibration/sample/corpus-v1.jsonl
uv run --offline model-router calibrate plan calibration/sample/corpus-v1.jsonl --config config/calibration-v1.yaml
uv run --offline model-router calibrate run calibration/sample/corpus-v1.jsonl --config config/calibration-v1.yaml --offline
uv run --offline model-router calibrate report <run-id>
uv run --offline model-router calibrate report <run-id> --format json
```

Run creates a new exclusive directory under ignored `.calibration/runs/` containing
`manifest.json`, `events.jsonl`, `run.json`, `report.json` and `report.md`. `--store`
selects another protected location. No automatic resume or overwrite is supported.
An interrupted journal retains started work for operator reconciliation; a rerun
creates a new experiment and never replays the earlier invocation automatically.

The 24-case public sample spans arithmetic, transformations, extraction, reasoning,
classification, writing, planning and code-shaped tasks. `mock-v1.json` supplies
scripted generation/classification/semantic outputs to exercise the harness. These
are intentionally supplied fixture answers; passing them makes no claim about model
quality, classifier accuracy or measured Router savings. `--mock-fixture` selects an
explicit alternate offline fixture. Ordinary tests remove credentials and deny network.

## Planning and live admission

`calibrate plan` makes zero provider calls. It pins configured prices and conservatively
counts all possible generation/classifier calls, evaluator retries and bounded
adjudications. It reports maximum calls, estimated upper bound, configured aggregate
cap and admissibility. Unknown price/capability evidence or an exceeded run cap
rejects the plan. Live admission additionally checks the durable allocation's remaining
balance. Sampling probability is not an upper bound on actual sampled calls.

The checked-in experiment has `live_enabled: false`. Live execution requires all of:

- An explicit `--live` invocation and `RUN_LIVE_CALIBRATION=1`.
- A dedicated experiment config with `live_enabled: true`, a positive finite
  `aggregate_cap_usd`, a named `allocation_id`, a finite `allocation_cap_usd`, a pinned absolute
  `allocation_directory`,
  explicit `allowed_privacy` under a versioned privacy policy, and an admissible conservative plan.
- A matching separately approved release manifest, active configured policy/catalog/
  prices/classifier and current immutable account/model/pricing evidence bound to the
  exact credential through the existing secure release convention.
- A fresh check before every paid action, bounded serialized input/output/time,
  durable per-run allocation and action intent, and complete actual-cost settlement.

The existing credential environment source is read only after explicit live setup.
Presence of `OPENAI_API_KEY` alone does nothing. Credentials are never printed,
written to reports or persisted in the corpus. This phase authorizes no paid run;
a future operator must assemble and review a concrete corpus and allocation first.

A separately named local allocation ledger in the configured absolute
`allocation_directory` reserves the whole conservative run bound under a file lock before paid work.
Settled spend survives restart, and earlier reservations reduce the amount available
for later runs. Unknown costs hold their allocation and block further work.
The immutable experiment config pins the ledger directory. There is no live CLI
override: changing the directory or ID requires a newly authorized experiment
configuration. Keep the same ledger for every run sharing an allocation. This coordinates a bounded single-host
experiment allocation, not an account-wide or distributed production budget. Started or unknown-cost calls stop further paid work and
retain evidence. No automatic reset/resume of a stopped run is provided. Reconcile
provider billing and the journal before allocating a new experiment after uncertainty.

Live Phase 1 supports text and explicitly supported strict structured-output schemas,
with V0 production validation. Provider schema conversion must preserve the pinned
contract. Unsupported schemas, tools or required V1/V2/V3 production validation are
INVALID; they are not silently downgraded. Semantic lab grading is an independent
experiment judge and its cost is overhead. Paid runs require a clean committed source tree and release-compatible action/deadline
limits. Offline execution accepts only explicit mock adapter types; live classifiers
and judges must use the admitted provider boundary. A trusted code-execution sandbox remains
future work; arbitrary shell in corpus data is never executed.

## Results and interpretation

[Methodology](calibration-methodology.md) defines fairness, grading, cost roles,
denominators, sampling, uncertainty and observation limits. The backend owns every
formula; future read-only API/dashboard clients can use the JSON contract directly.
Reports contain experiment/corpus pins, total spend, strategy results, paired Router
comparisons, family/complexity segments, over/under-routing candidates, observed
cheapest passing strategies, review queues, cost breakdowns, latency and limitations.

PASS and FAIL are resolved outcomes. UNKNOWN, INVALID and NEEDS_REVIEW remain
separate. A successful semantic call below threshold may fail a candidate; a judge
outage cannot. Deterministic evidence can override semantic scores only when the
authored contract declares that it measures success. Every contradiction remains
exported. Optional sampled adjudication uses separately configured stronger grading;
no evaluator is treated as ground truth.

Production-equivalent Router cost includes classifier, all generation/recovery and
required production validation. Fixed baselines have no classifier cost. Judges and
adjudication are experiment overhead. Experiment-inclusive spend includes all
strategies and unresolved work. ECPS includes failed resolved costs, excludes unresolved
outcomes explicitly and is unavailable if any included cost is missing or no case
passes. Offline observed costs are simulated and paid spend is zero.

## First real corpus: 150–300 cases

Use [the corpus/privacy guide](calibration-corpus.md). Start with historical work
across real families, complexity and consequence, preserving original task content,
output constraints, context and tool availability after privacy review. Track source
kind precisely: historical, replay, coding fixture, authored realistic or synthetic.
Do not manufacture cases to meet the target count.

```bash
uv run --offline model-router calibrate template
uv run --offline model-router calibrate schema
uv run --offline model-router calibrate case-id --source-ref safe-ticket-reference
uv run --offline model-router calibrate import calibration/private/intake.jsonl --output calibration/private/reviewed-v1.jsonl --version real-intake-v1
uv run --offline model-router calibrate deduplicate calibration/private/intake.jsonl --output calibration/private/dedup-v1.jsonl --version real-dedup-v1
uv run --offline model-router calibrate annotate calibration/private/dedup-v1.jsonl --output calibration/private/annotated-v2.jsonl --version real-annotated-v2 --case-id case-id --family analysis --tag historical
uv run --offline model-router calibrate validate calibration/private/annotated-v2.jsonl
```

Templates start internal and human-review-needed. Replace grading with objective
checks/reference rubrics where possible, review whether deterministic checks measure
success, deduplicate exact canonical inputs and manually review near-duplicates.
Annotations write a new version and cannot change canonical model input. ID generation
hashes safe source references without including source text in the returned ID.

Review corpus strata, task bounds, supported capabilities, rubrics and privacy before
planning a paid run. Freeze the experiment config/seed/cap; calibrate judges against
human assessments and inspect disagreement/unknown coverage. Later policy changes
must be separate versioned proposals with independent eval coverage and explicit
human-controlled activation. [ADR 0017](decisions/0017-calibration-lab-boundary.md)
records this experimentation boundary.

## Protected review outputs

Set `capture_review_outputs: true` in an explicit experiment config to retain outputs
only for disagreements and unresolved human-review outcomes. The versioned privacy
policy's `allowed_privacy` must permit the corpus. Capture defaults off, and raw
outputs remain absent from ordinary reports, telemetry and source artifacts. The
separate private `review_outputs/` files use restrictive permissions and content
hashes; recognizable secret-bearing outputs are rejected from capture.

The JSON review queue carries `output_reference` when capture succeeded. Use
`model-router calibrate review-output <run-id> <candidate-id> --store <store>` to
explicitly retrieve that protected candidate alongside the original protected corpus.
Without capture, the returned embedded `CalibrationRun` retains output in memory;
the CLI reports missing output retention and cannot recover discarded content.
Never paste protected outputs into a public report.
