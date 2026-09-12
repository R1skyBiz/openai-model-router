# Calibration Lab Phase 1 frozen contracts

Approved baseline: 495cfff0855f00f0253cadc93b62352384373a37. Root inspected
AGENTS.md, all Accepted ADRs (0001–0016), Phase 4–6 reports, evals (graders is
currently empty), classifier/provider, validation, execution/recovery, accounting,
SQL storage/budgets, and dashboard analytics. Initial working tree was clean.

The executable frozen v1 schema is `src/model_router/calibration/contracts.py`.
Changes to this shared boundary require root integration. No production routing,
policy, oracle, telemetry formulas, or execution contracts are modified.

Plan: (1) freeze schema; (2) parallel corpus/intake/persistence, runner/planning/live
admission, and blind grading; (3) root analytics/CLI/reporting/integration; (4) Sol
High adversarial review; (5) all regression gates, then commit/push main.

Corpus JSONL plus adjacent `.manifest.json` pins bytes/version/count/privacy.
`CalibrationCase` annotations never enter generation/classification input. Only
explicit task, instructions, context and output constraints enter a single canonical
input. All strategies share capability, output, tool and deadline envelopes.
Unsupported tools/production validators are INVALID before paid work. Phase 1
production validation is V0; grading can independently be deterministic/semantic.

Runner port: `CalibrationRunner(bundle, classifier_config, config, *, provider,
classifier, grader, store, live_guard=None)`. `run(cases, corpus_manifest,
offline=True)` returns CalibrationRun. Use unchanged router and recovery policy,
with separate lab orchestration and evidence; no production telemetry writes.
Every provider action passes budget admission and persists intent before dispatch.
Live support uses existing secure release evidence conventions, explicit env/config
opt-in, fresh credential-bound evidence, conservative aggregate reservation and
unknown-cost stop. No paid run is authorized during implementation.

Grading port: `BlindGrader(evaluator=None, adjudicator=None, config=None)` and
`grade(candidate, *, adjudicate=False) -> Grade`. Evaluator port:
`evaluate(candidate, rubric) -> SemanticScore`; candidate has no strategy/model/
latency/cost/route fields. Results attach to strategy only after blind grading.
Grade call evidence is overhead, never production-equivalent cost.

Storage port: `CalibrationStore(root)`, `start(manifest)`,
`append_event(run_id, event: dict)`, `finish(run)`, `load(run_id)`.
Immutable exclusive run directories and append-only safe metadata journal retain
started/uncertain actions. Reruns create new IDs, never resume dispatch. Raw task,
reference, rubric prose and outputs are absent from persisted reports/evidence;
keep hashes/version provenance. No SQL migration needed for this isolated store.
Explicit `capture_review_outputs` adds separately protected, checksummed candidate
files through `save_review_output` / `load_review_output`; ordinary snapshots carry
only their references. `CalibrationAllocation` pins a configured absolute ledger
directory, allocation identity and cap, reserving run bounds across process restarts.

Analytics: `analyze(run) -> dict` and `render_markdown(report) -> str`.
Resolved = PASS/FAIL only; all other states explicitly separate. ECPS includes
all resolved production costs (including failed/recovered work), divided by PASS.
Any missing included cost makes ECPS null; known subtotals stay available. Judges
and adjudication are overhead; total experiment spend includes every strategy and
all overhead, including unresolved work. Empty/zero-success ratios are null.
Comparisons require identical inputs and validation signatures; cheapest success
is observed only. Small cohorts are labeled INSUFFICIENT SAMPLE.
