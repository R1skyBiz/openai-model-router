# Reviewed calibration pilot v1 — offline mechanics

The 26-case candidate seed produced **14 accepted/repaired cases, 0 rejected cases,
and 12 deferred cases**. `reviewed-pilot-v1` is an internal, realistic-task pilot
for testing experiment mechanics. It is not benchmark ground truth, model-quality
evidence, or authorization for paid execution. No routing policy changed.

## Corpus review and provenance

All 26 cases were inspected individually for realism, self-contained input,
privacy, grading, consequence and harness support. No credentials, identifying
customer information, health records or personal financial records were found in
the retained text. Internal provenance stays internal. Detailed case decisions,
source references and source-to-pilot mappings are retained only in ignored
`calibration/internal/pilot-review-v1.json` and accompanying internal artifacts.

The seed describes sanitized historical reconstructions but supplies no original
conversation/ticket records. All accepted cases therefore use `authored_realistic`,
not `historical_real`. Their historical provenance remains unverified. No historical
assistant answer was used as an expected answer. Planning/design cases are graded
as proposals, not as executed code or validated engineering implementations.

The sole deterministic result was independently recomputed using both Decimal and
exact rational arithmetic; the output instruction was repaired to match the exact
format being graded. The 13 semantic rubrics now have five explicit dimensions,
partial-credit anchors, equivalent-answer acceptance and a cap for materially false,
invented, unsafe or constraint-violating content. Domain reference checks and
reasoned grading criteria are recorded internally. The rubrics still require human
judge calibration before paid quality measurement.

The 12 deferrals cover missing specifications or geometry, consequence levels or
production validation that V0 cannot support, missing version-pinned evidence,
and date-sensitive/tool-dependent questions. Deferred cases were not silently
weakened or relabeled low consequence. They can be reconsidered after the missing
evidence and harness support exist.

The repository-native `write_corpus` intake function authored a new version.
`load_corpus` generated the complete case hash map, which was persisted in the
adjacent manifest and reloaded for verification. All 14 case hashes and the exact
corpus byte hash were verified. The seed bytes remain unchanged.

- Version: `reviewed-pilot-v1`
- Privacy: `internal`
- Corpus SHA-256: `3341b1df0a34084429302c6c4ee20bf8f6cb49f681ad5522077133554fb133b2`
- Input/config/mock/audit files: ignored `calibration/internal/`
- Run store: ignored `.calibration/reviewed-pilot-v1/`
- Corpus and internal review files use mode 0600; internal directory uses 0700.

## Offline execution

Verified run IDs (under the ignored run store):

- Primary: `calibration-7fae4f65d16d46299c333fd9737e7cf8`
- Audited repeat: `calibration-fb2ecb833429426ba2f1c7a8dbfacb68`
- Negative control: `calibration-15fbbd86ebfb43adaf3ce61a086bd970`

The primary run completed 42 rows: 14 cases each for ROUTER, Terra/medium and
Sol/medium. Router uses the normal classifier normalization and deterministic policy
with a scripted classification. Recovery is disabled. Each run recorded 14 mock
classifier calls, 42 mock generation calls and 39 mock semantic evaluator calls;
the deterministic case requires no semantic call. Adjudication is disabled.

A repeat audit denied socket networking and removed live credentials/opt-ins.
It verified matching canonical inputs and validation signatures across strategies,
39 opaque blind semantic candidates, matching deterministic dispositions, 14 resolved
pairs per baseline, and both JSON and Markdown report generation. A negative control
changed only the mock deterministic answer: each strategy then had 13 PASS and 1 FAIL.
The same production cost divided by 13 successes verified inclusion of failed-task
costs in ECPS. Fixed baselines have zero classifier cost; semantic judging remains
experiment overhead. Dedicated tests cover unresolved/missing-cost semantics.

All primary/repeat rows received scripted PASS dispositions. **The semantic mock
returns a constant score even for placeholder text. These results demonstrate
plumbing only, not grading accuracy, task success, classifier accuracy, savings or
model quality.** The fixed mock route is not a workload distribution estimate.
Every cohort is below the minimum sample size of 30, and the convenience-selected
realistic sample cannot support population estimates.

Simulated production spend was $0.028224 and simulated judging overhead $0.0468,
for $0.075024 simulated experiment spend per run. Actual paid spend was **$0**.
The audit confirmed task/context/rubric/output text was absent from persisted run
artifacts; capture was disabled and no `review_outputs` directory was created.
Protected capture and rejection behavior are covered by the calibration tests.
A development audit initially stopped on a list/dict assertion mistake after one
completed mock run; its evidence remains preserved and is not counted as a successful
verification. The corrected repeat and negative-control audit passed.

## Conservative live plan — no execution

The provider-free planner uses the unchanged configured model prices, includes
cache-write premiums and reserves the most expensive enabled generation route for
Router. This is a bound against pinned configuration, not a claim about current
account pricing or model availability.

| Limit | Maximum |
| --- | ---: |
| Cases | 14 |
| Strategies | 3 |
| Generation calls | 42 |
| Classifier calls | 14 |
| Primary evaluator calls, including one retry | 84 |
| Adjudication calls | 0 |
| All paid-action calls if admitted in future | 140 |
| Conservative upper bound | $11.2738304 |
| Proposed aggregate live cap | $25 |

The evaluator ceiling conservatively includes the deterministic-only case too.
Sampling does not reduce any bound. Generation input/output limits are 8192/1024;
classifier output limit is 2048; evaluator input/output limits are 16384/512.

Independent Decimal recomputation matched the planner:

| Component | Upper bound USD |
| --- | ---: |
| Router generation | 2.1504 |
| Terra generation | 0.458752 |
| Sol generation | 0.86016 |
| Classification | 0.0630784 |
| Primary evaluation and retries | 7.74144 |
| Adjudication | 0 |
| Total | 11.2738304 |

The $25 cap is a proposal only; no allocation was created. Future paid execution
still needs explicit approval, an immutable live-enabled experiment and matching
release, fresh account/model/pricing/credential evidence, a pinned absolute durable
allocation ledger with sufficient balance, and human calibration of semantic judges.
Sol/medium is both a baseline and the sole semantic judge; its scalar-only scores
and absence of adjudication require human/golden-output calibration and bias checks
before model-quality interpretation. A quality study must also address verified
provenance and representative sampling. Local capture being disabled does not
prevent a future live run from transmitting internal task text to the provider;
future live approval must explicitly cover provider-side data handling.
Any adjudicator, recovery, token-limit or corpus expansion requires a new cost plan.

## Expansion toward 200 cases

Strata below are a mutually exclusive manual intake mapping by primary work product;
they do not use the scripted classifier output or double-count domain tags.

| Target stratum | Target | Pilot | Additional realistic cases |
| --- | ---: | ---: | ---: |
| Engineering | 45 | 4 | 41 |
| Analysis / research | 35 | 2 | 33 |
| Coding / debugging / architecture | 35 | 4 | 31 |
| Writing / planning | 30 | 3 | 27 |
| Extract / transform / knowledge | 30 | 0 | 30 |
| Data / math / structured | 15 | 1 | 14 |
| Tool / agentic | 10 | 0 | 10 |
| Total | 200 | 14 | 186 |

These are realistic-case gaps. If the target requires independently verified
historical cases, **all 200 slots remain unverified** until source records are
recovered; the pilot cannot be counted as 14 verified historical cases.

Prioritize short, deterministic extraction/transformation and structured-data tasks;
actual code/debugging snapshots with expected behavior; and analysis tasks with
frozen source tables/documents. These add objective grading and diversity beyond
semantic proposals. Preserve failures and ambiguous outcomes as well as successes.
Collect longer inputs and varied complexity/consequence without waiving harness limits.

The next 50 source-backed intake candidates should target 8 engineering, 10 analysis,
10 coding/debugging, 8 writing/planning, 8 extraction/transformation, 4 data/math, and
2 tool/agentic records. Tool cases should be collected with sanitized observations
and expected actions but deferred from execution until replay/sandbox support exists.
For each record retain an opaque source reference, timestamp, sanitized input,
required context, output constraints and independent expected result or rubric.
Deduplicate by source/workflow and manually inspect near-duplicates. Count historical
provenance only after reviewing original records; do not fabricate replacements.

## Verification and independent review

Packaging cleanup commit: `828fd95b418d29ec154dc67a7783d0651ab5bda5` (separate from this report). A Sol High reviewer
approved the cleanup with no actionable findings; Hatchling and production packaging
configuration are unchanged. The complete offline release verifier exited 0.

| Gate | Result |
| --- | --- |
| Full backend suite | 859 passed, 5 skipped (4 opt-in PostgreSQL, 1 paid live) |
| Calibration-specific suite | 105 passed |
| Phase 1 oracle | 142/142 applicable; 37 explicitly out of Phase 1 scope |
| Phase 2 mock classification | 19/19 |
| Phase 3 | 178/178 applicable |
| Phase 4 | 1/1 applicable |
| Combined oracle | 179/179 |
| Extra routing regressions | 22/22 |
| Release load/recovery gate | Passed |
| Frontend tests | 21/21 across 3 files |
| Frontend typecheck and build | Passed |
| Wheel/sdist and installed-wheel migrations | Passed |
| Fresh editable install, imports and CLI | Passed |
| Locked config/policy/oracle integrity and diff whitespace | Passed |
| PostgreSQL integration | 4/4 passed in a separate Python 3.12 environment with cached driver |
| Independent pilot review | Sol High approved; no actionable offline blockers |

The independent Sol High pilot reviewer checked all 26 decisions, source mappings,
corpus/case hashes, deterministic arithmetic, rubric fairness, run checksums and
raw-content scans, paired comparisons, failed-cost ECPS, archive/Git exclusion and
the independent cost calculation. They approved the mechanics-only pilot and report
with no actionable offline blockers. They reviewed regression summaries rather than
rerunning the broad suites. Full retrieval of one conceptual reference page remained
unavailable; no crop-specific thresholds depend on it. Historical provenance, judge
calibration, provider handling and live quality remain the explicit future gates above.

No calibration runtime code, routing policy or oracle changed. Private corpus contents,
source mappings, mock outputs and detailed review notes are excluded from Git and
release artifacts. The next approval gate concerns a concrete live experiment;
this report does not authorize it.
