# Calibration Lab v0.2 — Phase 1 implementation report

Approved starting baseline: `495cfff0855f00f0253cadc93b62352384373a37`.

This phase delivers an isolated workload comparison laboratory. It does not establish
real-world model quality or Router savings. No paid calibration was run, routing
policy and the independent oracle remain unchanged, and no release was published.
The distribution version remains the existing v0.1 release-candidate version.

## Architecture and contracts

`model_router.calibration` owns versioned Pydantic corpus, experiment, manifest,
call, grade, strategy-result and budget contracts. The runner reuses the existing
classifier/provider boundaries, deterministic router, bounded recovery decisions and
historical cost accounting. Experiment orchestration, grading, persistence and
analytics remain separate from production execution and telemetry. The existing CLI
delegates only the new `calibrate` command. No production SQL migration or frontend
expansion was introduced. [ADR 0017](decisions/0017-calibration-lab-boundary.md)
records the experimentation boundary.

The JSONL corpus and adjacent manifest pin exact source bytes, version, case count,
privacy and normalized case hashes. Cases carry task/instructions/context, capability
requirements, consequence, bounds, output contract, tool policy, grading plan and
optional source/family/tag annotations. Those annotations never enter model input.
The 24 committed public cases are synthetic controls or authored fictional tasks,
with separately supplied mock responses. Private historical inputs are not included.

## Strategies and grading

ROUTER classifies normally, routes deterministically and uses the selected model and
effort; recovery is allowed only when explicitly enabled. TERRA_BASELINE and
SOL_BASELINE use fixed medium effort and never classify. Additional fixed strategies
use the same schema. All strategies receive the same canonical task and comparison
envelope. Execution and blind judging order are seeded and randomized separately.

Deterministic graders support exact values, a fail-closed schema subset, numeric
tolerance, required/forbidden fields and registered invariants. Semantic grading
uses independent invocations with versioned rubrics, explicit scale/threshold and
optional reference facts. Judges see opaque candidate labels without strategy,
model, route, cost or latency. Optional stronger adjudication is sampled and bounded.
Contradictions remain in review evidence; deterministic results win only when the
authored contract genuinely measures success. Judge infrastructure failures produce
UNKNOWN or NEEDS_REVIEW, never a fabricated quality failure.

Production-equivalent validation in this phase is V0. Cases requiring tools,
unsupported schemas, or V1/V2/V3 production validation are INVALID. Arbitrary fixture
commands are not executed; the optional trusted code sandbox is deferred. Corpus
intake must preserve these unsupported strata rather than disguising their coverage.

## Economics and reporting

Backend-owned formulas report attempted/resolved counts, all five result states,
pass/unknown/first-pass/final-success rates, mean/P50/P95 production cost, ECPS,
latency, escalation and classifier cost. Segments cover family, shared Router-derived
complexity, initial model/effort, source, consequence, policy and tags.

ECPS includes all resolved PASS/FAIL production costs, including failures and
recovery, divided by PASS count. UNKNOWN, NEEDS_REVIEW and INVALID have explicit
separate denominators; their incurred spend remains in experiment totals. Missing
included costs and zero-success cohorts produce null metrics. Classifier cost belongs
only to ROUTER; judges/adjudication are experiment overhead. Money uses Decimal and
JSON decimal strings. Markdown displays up to eight significant digits.

Paired comparisons require matching inputs and validation. Reports expose
over/under-routing candidates and the cheapest *observed* passing strategy without
claims about untested routes. Small cohorts show INSUFFICIENT SAMPLE. Descriptive
Wilson intervals have stated assumptions; no automatic significance or policy change
is inferred. [Methodology](calibration-methodology.md) defines the exact denominators.

## Privacy, reproducibility and live gates

Run directories and final snapshots are exclusive and immutable. Safe action journals
are locked and fsynced; manifest/snapshot checksums detect corruption. Manifests pin
corpus/case hashes, policy, model catalog, pricing, classifier, rubric hashes,
strategies, configuration, seed, software provenance and timestamp. Raw task/output/
reference content does not enter ordinary reports. Explicit protected review capture
can retain unresolved/disputed outputs with restrictive permissions and content-hash
references; capture defaults off and secret-shaped outputs are rejected.

Private corpora and generated evidence are ignored and excluded from source, wheel
and Docker artifacts. Tests build actual archives with private sentinels and verify
their absence. The default `.calibration/` run store is also excluded.

No-call planning bounds generation, classification, retries, judges and adjudication.
Live dispatch requires explicit CLI/environment/config opt-in, fresh credential-bound
release evidence, allowed privacy, clean committed source, supported adapters and
release-compatible request limits. A named local allocation ledger at a pinned
absolute path reserves the whole run bound under a file lock. Spend survives restart;
known overruns remain charged, while uncertain calls hold the reservation and stop
further work. This is a single-host experiment allocation. No paid end-to-end live
benchmark was executed as part of validation.

## CLI and sample verification

`model-router calibrate` provides `validate`, `plan`, `run --offline/--live`,
`report`, `schema`, `template`, `case-id`, `import`, `deduplicate`, `annotate` and
explicit `review-output` retrieval. Reports are JSON and Markdown over the same
immutable sanitized evidence. See [the lab guide](calibration-lab.md) for commands.

The final offline sample completed 72 case-strategy executions: 24 each for ROUTER,
Terra and Sol. All scripted expectations passed. Simulated production work totaled
USD 0.048384 and judge overhead USD 0.0108, reconciling to USD 0.059184 simulated
experiment spend. Actual paid spend was USD 0. These fixture economics must not be
interpreted as a benchmark conclusion.

## Verification

| Gate | Result |
| --- | --- |
| Full offline backend pytest | 858 passed; 5 opt-in tests skipped |
| New calibration coverage within backend total | 105 tests |
| PostgreSQL migration/storage/concurrency, isolated test database | 4 passed separately |
| Frontend | 21 tests; typecheck and production build passed |
| Phase 1 runner | 142 applicable cases passed; 37 stage-specific skips |
| Phase 2 runner | 19 mock classifier seeds passed |
| Phase 3 runner | 178 applicable cases passed; 17 recovery scenarios; evaluator case deferred to Phase 4 |
| Phase 4 runner | 1 applicable evaluator case passed |
| Combined independent oracle | 179/179 passed |
| Regression corpus | 22/22 passed |
| Classifier-only route behavior | Existing tests passed in full backend suite |
| Migration and package smoke | SQLite up/down/up, installed wheel and clean editable installation passed |
| Source checks | Locked dependencies, YAML/TOML, skill links, secret scan, offline network guards and diff whitespace passed |

The full verification command was `scripts/verify_release.py --offline
--skip-frontend-install` using the local uv runtime. PostgreSQL ran against a separate
ephemeral test database; the local test server was stopped afterward. Existing
Starlette deprecation warnings remain; no new production warning was introduced.

## Independent review

Sol High adversarial review examined fairness, blinded grading, cost completeness,
UNKNOWN denominators, recovery, comparison claims, privacy, live admission and
production/oracle preservation. Material findings were fixed with focused coverage:

- Bound actual serialized requests, reject unsupported schema conversion, and keep
  per-strategy deadline failures from stopping unrelated strategies.
- Preserve queued/in-progress responses as UNKNOWN for both provider result shapes,
  validate returned model/service-tier pricing bindings, and retain paid costs when
  an overrun stops dispatch.
- Bind live adapters and all classifier/judge provider ports to admission; verify
  CLI composition without constructing an SDK client before dispatch.
- Pin per-case content/privacy, preserve shared comparison segments, and reject
  conflicting rubric versions.
- Add durable cross-run allocation accounting with immutable identity/cap/history,
  protected human-review output references, private intake permissions at creation,
  and complete artifact exclusions.
- Use mathematical number equality for JSON Schema while retaining strict exact
  grading; remove authoritative exact grading from free-form sample tasks.
- Keep infrastructure deadline failures out of under-routing observations.
- Honor configured recovery backoff and recheck the deadline before retrying, so
  recovery-enabled trials preserve bounded retry timing and latency accounting.

Final Sol High independent review: **no remaining material blockers**. The reviewer
also independently reproduced a known overrun through the runner and durable ledger
without network access: the actual charge remained settled after dispatch stopped.
Review was read-only and made no paid calls.

## Next: the first real 150–300 cases

1. Select representative historical tasks across source, family, complexity,
   consequence and failure modes. Preserve original constraints and provenance;
   do not manufacture cases to reach a target count.
2. Review privacy and scrub credentials before importing into the ignored private
   corpus. Generate stable IDs, deduplicate canonical inputs and manually inspect
   near-duplicates. Freeze a versioned manifest after annotation and validation.
3. Author deterministic checks or reference rubrics that measure the requested
   result. Review unsupported cases explicitly and calibrate semantic judges against
   human assessments, including agreement samples and disagreements.
4. Pre-register strata, minimum cohort sizes, quality/reliability tolerances,
   uncertainty handling, review retention and a finite experiment allocation.
5. Inspect a conservative plan and obtain separate authorization before any paid
   calibration. Interpret frozen evidence descriptively; any later policy proposal
   needs its own version, eval coverage and explicit activation.

[Corpus and privacy intake guide](calibration-corpus.md).
