# Calibration flight handoff — Segment 1

Audited 2026-09-10. Scope: the existing Model Router repository and its retained local calibration evidence. This document records a fresh audit, not acceptance of previous conversational claims. No corpus case, source history, grading rule, routing policy, experiment configuration, or previous report was changed. No model generation, live evaluation, paid API call, canary execution, allocation, or push occurred.

## Verified repository state

| Item | Verified value at audit start |
| --- | --- |
| Repository | `<REPOSITORY_ROOT>` |
| Branch | `main` |
| HEAD | `79952f4a767309bbd60bee728e3603440376f439` |
| HEAD subject | Document reviewed calibration pilot mechanics and live approval gaps |
| Tracking branch | `origin/main` |
| Local tracking and freshly queried remote tip | `0d56cf50e582c285970ad8d7774c5e06c9d9ef59` |
| Divergence | 2 ahead, 0 behind |
| Tracked changes / staged changes | None / none |
| Pre-existing untracked files | `docs/calibration-provenance-tranche-v1.md`; `docs/calibration-canary-readiness-v1.md` |

The two local commits are `828fd95b418d29ec154dc67a7783d0651ab5bda5` (editable-install smoke hardening) and the HEAD above. `git ls-remote origin refs/heads/main` verified the remote without fetching or pushing. The initial sandboxed lookup failed DNS resolution; the approved read-only retry succeeded. Remote state is a point-in-time observation.

Instructions: read root `AGENTS.md`; a hidden/ignored-inclusive search found no other repository `AGENTS.md`. Also inspected `calibration/internal/README.md`, ADR 0017, the corpus, methodology and interface contracts, the implementation/configuration/architecture/routing source-of-truth references, and relevant calibration code/tests. In particular: private corpus content stays ignored, versions remain immutable, and executable/tool work cannot be converted to text-only success claims. No new phase boundary or ADR is needed for this audit-only documentation.

The focused local reporting commit contains only this document, with the audited HEAD as its parent. Thus the expected post-commit branch is 3 ahead / 0 behind the verified remote tip; the two pre-existing untracked reports remain untouched. To resolve the reporting commit exactly after checkout, run `git log -1 --format=%H -- docs/calibration/flight-handoff-segment-1.md`. The final terminal summary records its ID; a commit cannot embed its own hash in its contents.

## Verified files, versions and pins

All paths below are repository-relative. `T` means `calibration/internal/tranche-v1/`; `R` means `.calibration/provenance-tranche-v1/`. These private directories are present locally, ignored by Git, and are not supplied by a fresh clone. The handoff contains identifiers and findings, not raw prompts, source email, rubric text, private locators or candidate answers.

| Artifact | Version / role | Records |
| --- | --- | ---: |
| `calibration/sample/corpus-v1.jsonl` + adjacent manifest | `sample-v1`, public harness sample | 24 |
| `calibration/internal/real-seed-v0.jsonl` + manifest | `real-seed-v0`, historical reconstruction seed | 26 |
| `calibration/internal/reviewed-pilot-v1.jsonl` + manifest | `reviewed-pilot-v1`, authored controls | 14 |
| `T/candidate-v1.jsonl` + manifest | `provenance-candidate-v1`, superseded development snapshot | 44 |
| `T/candidate-v2.jsonl` + manifest | `provenance-candidate-v2`, superseded development snapshot | 44 |
| `T/provenance-tranche-v1.jsonl` + manifest | `provenance-tranche-v1`, audit target | 44 |
| `T/decisions.json` | 44 acceptance decisions + 7 deferrals | 51 |
| `T/sources.json` | 31 repository-function records + 17 historical excerpt/request records | 48 |
| `T/proposed-canary-v1.jsonl` + manifest | `proposed-canary-v1`, subset, not additions | 4 |
| `T/proposed-canary-selection-v1.json` | Parent/subset case mapping and proposed budget | 4 |
| `T/proposed-canary-disabled-v1.yaml` | `proposed-canary-disabled-v1` | Disabled |
| `T/offline.yaml` | `provenance-offline-v1`, mock-only $100 ceiling | Disabled live |
| `config/calibration-v1.yaml` | `calibration-lab-sample-v1` | Disabled live |
| Policy/catalog/classifier | `router-v1.0.0` / `models-v1.0.0` / `classifier-v1.0.0` | Unchanged |

The sample, seed, pilot, both candidates, final tranche and canary load with valid adjacent manifests. All 44 final case hashes are pinned and validate. Both candidate versions contain the same 44 canonical generation inputs as the final tranche: they are not extra work products.

| Pin | SHA-256 |
| --- | --- |
| Final JSONL bytes | `b79373e95c6ecf93bf5748de7a0550575b857505d2c79a0062ba9a168b3909b2` |
| Final manifest bytes | `e24755b104a3c456ea04bb432ca3abe1862f7e33647c1e04cf44c4f357a23054` |
| Final canonical records | `2da87573ddca5f78a9246ab33b7ddc29ae4c981efad3674d96389d73a8d7434c` |
| Source map | `644ea6038dd1af6c3b2dc1f33b32f30cdeb4ba35ed4b2b9d3369c7e98d0156d2` |
| Decisions | `bae1ef38955f49ad5d0cc74dde4308990c6319619f8a01e200f95475c9d73494` |
| Pilot JSONL | `3341b1df0a34084429302c6c4ee20bf8f6cb49f681ad5522077133554fb133b2` |
| Canary JSONL | `5ce870541ca5301e67cfa172942de48099f71e31d2bc8acd5e2f0c283d69cf11` |
| Disabled canary config | `859067d474750a4c6c0c4cfeb469808988c65ca17b89cec785e6f4fd36b8a3be` |
| Model config | `b8445b7f7426f64acb4af0d80414ed42d9f1f94731bb39f70eb4f7c5e439340a` |
| Classifier config | `76255a6e47d14cdaa916c93aa47b6874341cbd6d336c379a8d3f22b18e588309` |
| Routing policy config | `09a78d3de960dee30b79b5b550f6b4c2ffe23a386998bfeee582aa42a6be6b13` |

Canonical-record hashing sorts JSON object keys, uses compact UTF-8 JSON and one newline per record, and **preserves JSONL record order**. Sorting records by ID produces a different digest; the older “canonical sorted-record” label must not be read as an instruction to reorder them.

## Recalculated counts and milestone accounting

`decisions.json` records **0 accepted without repair, 44 accepted/repaired, 0 rejected, 7 deferred**. Every accepted ID appears once in the final JSONL; every case's source, family and kind agree with its decision. Repaired is part of the combined persisted status `accepted_repaired`; it is not an additional 44 cases. The old pilot's 12 deferrals belong to a separate intake and are excluded.

Provenance labels: **10 `historical_real`, 34 `coding_fixture`, 0 `application_replay`, 0 `authored_realistic`, 0 `synthetic_control`**. These are verified stored labels; independent original-record verification has the limits below. Grading: **13 deterministic, 31 semantic, 0 mixed**. Eight deterministic cases have strict JSON output contracts and five have text/numeric answers. All 44 cases are `internal` and low consequence; there are no accepted executed-code, tool-workflow, agentic or higher-consequence cases.

| Primary intake category | Families | Cases | Initial 60 allocation | Gap to allocation | 200 allocation | Gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Engineering | engineering | 1 | 12 | 11 | 45 | 44 |
| Coding / debugging / architecture | debugging 3; architecture 9 | 12 | 12 | 0 | 35 | 23 |
| Analysis / research | analysis | 10 | 10 | 0 | 35 | 25 |
| Writing / planning | writing 7; planning 1 | 8 | 8 | 0 | 30 | 22 |
| Extract / transform / knowledge | extract 6; transform 2 | 8 | 8 | 0 | 30 | 22 |
| Data / math / structured | data_analysis 4; math 1 | 5 | 5 | 0 | 15 | 10 |
| Tool / agentic | none | 0 | 5 | 5 | 10 | 10 |
| Total | | **44** | **60** | **16** | **200** | **156** |

Allocations are the existing proposal, not newly approved sampling targets. Counts above count case records, not independent work products.

**The claim of exactly 41 distinct work products is not established.** There is no `work_product_id`, parent-workflow grouping or adjudicated definition in the corpus. Two separate calculations happen to yield 41: 44 minus three repeated source references, and 44 minus three pilot-overlapping case records. They remove different cases and cannot substitute for one another.

| Explicit counting unit | Count | Gap to 60 | Gap to 200 |
| --- | ---: | ---: | ---: |
| Accepted/repaired case records | 44 | 16 | 156 |
| Unique accepted `source_ref` values | 41 | 19 | 159 |
| Case records excluding the three pilot overlaps, without other grouping | 41 | 19 | 159 |
| Conservative parent-source groups: one per pinned test function or original request locator | **35** | **25** | **165** |
| Parent-source groups additionally excluding the three pilot-overlapping parents | **32** | **28** | **168** |

The 35 groups comprise 31 repository functions and four historical parent requests. Seven documentation excerpts collapse to one parent; three function pairs each collapse to one source. This is a reproducible conservative proxy for underlying work products, not proof of 35 statistically independent jobs. Distinct documentation deliverables could legitimately be counted separately after adjudication, while multiple functions may belong to one larger implementation job. The 60/200 **work-product** milestones remain definition-dependent. Do not announce a verified 19-work-product shortfall until that unit is settled. Historical-label counts alone give gaps of 50 and 190 case records, but only four parent requests underlie the ten labels.

## Audit findings and required decisions

### Provenance and status

All 31 repository source functions (seven files) and two supporting helper excerpts match pinned Git blob and excerpt hashes at `79952f4a767309bbd60bee728e3603440376f439`. All 42 supplied excerpt hashes in the 48-record source map match retained text. No accepted case lacks a source-map entry, and no locally verifiable pin mismatch was found. Repository fixtures are correctly labeled derivatives; their prompts are authored from tests, not production observations.

The ten accepted historical cases retain opaque original-record locators and hash-consistent sanitized excerpts. Seven also point to one original attachment hash. The original chat/attachment records are outside the repository and were **not retrieved** in this segment. A self-consistent excerpt hash cannot independently prove origin or that sanitization preserved every relevant constraint. Existing review attestations claim earlier verification; this audit verifies their presence, not their external originals. Keep the current labels as recorded but mark origin revalidation pending before claiming fresh historical ground truth. Do not relabel them as fabricated without evidence.

The six deferred implementation/workflow sources have original-attachment hashes and locators but no hash for their retained sanitized summaries. The CAD deferral has an excerpt hash. These are adequate pointers for future recovery, not self-contained execution cases. Add reviewed in-repository source evidence and normalized provenance fields in a future version. All seven deferrals are appropriate to current harness limitations. No new rejection, deletion or in-place status rewrite was made; acceptance here means retained offline fixture eligibility, not benchmark-quality certification.

### Duplicates, prompt overlap and leakage

There are 44 distinct canonical generation inputs and no exact input overlaps with the public sample, 26-case seed or 14-case pilot. Canonical equality misses meaningful source overlap:

| Shared underlying source | Cases that must remain grouped |
| --- | --- |
| One architecture assignment | mission-note, privacy-note, versioning-note, boundary-note, non-goals-note, phase-plan, telemetry-note |
| One incomplete/refusal provider test | incomplete-parse + incomplete-fields |
| One evaluator attribution test | judge-attribution + provider-scope |
| One partial-cost ranking test | partial-ranking + partial-cost-shape |
| Existing authored pilot work products | tray-capacity, siphon-explanation, positive-reply |

Pilot bindings are explicit: tray-capacity → `pilot-aabffae971b6a540047746d7`; siphon-explanation → `pilot-6425ee3af5ea0d8583695927`; positive-reply → `pilot-78207707741cf51b0ca72539`. Those controls are excluded from the three tranche runs.

A token-set Jaccard screen of all 946 accepted-case pairs, using lowercase task plus context and excluding shared formatting instructions, found one pair at the review threshold 0.35: judge-attribution / provider-scope (0.3684). Manual inspection also identified the other source-linked pairs above. This screen is a triage aid, not a semantic uniqueness certificate. The seven documentation outputs are different sections but a shared workflow; authentication and quality-panel cases are thematically related even when source functions differ. Group by parent source when constructing development, judge-calibration and held-out splits. Never pool candidate-v1, candidate-v2, canary, pilot overlaps or repeated mock runs as independent samples.

Canonical classifier/generation payloads contain only task, instructions, context and output contract. No source references or full semantic rubric instructions enter them. All three stored strategies have equal current comparison hashes and validation signatures for every case. `StrategyRun.input_sha256` actually hashes the canonical input **plus execution envelope**, via `canonical_comparison_sha256`; use that function when validating retained runs.

There is intentional overlap between supplied source facts and grading reference facts for extraction/documentation tasks. That is necessary task context, not annotation leakage. No additional direct grading-annotation leakage was found. Task-specific mock answers are keyed by case ID and semantic scores are fixed at 0.95, so these artifacts must never become live generation context or held-out truth. The judge is Sol/medium and Sol is also a baseline: opaque labels prevent route metadata leakage but do not establish absence of style bias. Source-specific facts mention model aliases; they are task data, not candidate strategy identities. No model memorization or cross-session contamination claim can be tested offline here.

### Deterministic truth and rubric weaknesses

All 13 expected answers were independently recomputed from the supplied generation inputs and passed the actual deterministic grader. This included the geometry/unit conversion, nested JSON mappings, decimal mean, half-open UTC window and percentile, terminal ECPS, and recovery ratio. No unsupported deterministic expected value was found. The terminal ECPS case explicitly defines its own terminal-task denominator; do not use that task's cancellation convention to redefine Calibration Lab's PASS/FAIL denominator.

**F — two concrete grading-contract repairs:** precise-money (`case-48a79eaf84219b89b3753a42`) and latency-percentile (`case-621cf8523fbb48b4227f78d9`) ask for a numeric result without fixing decimal formatting, but use exact string equality. Appending a trailing decimal zero preserves the numeric result and satisfies the stated task, yet the actual grader returns FAIL. Repair in a new corpus version using the supported numeric rule with zero tolerance, or explicitly require canonical serialization. The other three numeric-text cases expressly request two decimal places and do not have this particular mismatch.

**R — all 31 semantic cases need human rubric adjudication before quality claims.** Each uses five equally weighted 0/0.5/1 dimensions and threshold 0.8. Four complete criteria plus one entirely absent criterion reaches PASS. The falsehood/invention/explicit-constraint cap does not explicitly make omission of every rubric-critical requirement fatal. For example, privacy-note can omit the prohibition on secrets while covering four other dimensions. Identify must-pass criteria and calibrate omission, partial, boundary and contradictory answers, rather than assuming a generic mean measures success. This is a structural rubric risk, not an observed live judge error. Some criteria can reasonably be optional; adjudication must distinguish those from mandatory requirements.

Rubrics contain case-specific criteria and permit equivalent wording, but “partial” has no case-specific answer anchors. `reference_facts` mostly repeats those criteria instead of providing a separately adjudicated gold answer. The provider evaluator returns a scalar score; per-criterion compliance and application of the cap are not enforced by the runtime. The six canary probe drafts are awaiting human agreement, and the broader judge-calibration panel is not completed. Human review must settle strictness, completeness and score reliability before promoting any semantic case to calibrated ground truth. This segment does not propose a runtime change.

**A — auth-identity needs a specific wording adjudication.** Its rubric refers to rejecting the spoofed request, while its pinned regression permits a successful request when the untrusted header is ignored and rejects the forbidden body identity. Ensure a secure ignore/override design is accepted where appropriate and distinguish header/query scoping from body rejection. The core identity/privacy requirement is supported; a blanket rejection requirement is not.

### Privacy and sanitization

Reviewed all 44 task/context/grading records and all seven retained deferral summaries. No apparent identifying customer data, live credentials, health records or personal financial records were found in retained case content; the repository's secret-pattern check found zero matches in full accepted records. Opaque synthetic request IDs and fixture values are not evidence of real users. Local source maps retain private locators and test excerpts containing dummy secret strings; do not copy them into public reports.

All files under the tranche and its retained run store are mode 0600, directories 0700; no permission exceptions were found. The three completed run stores contain no full task/context/rubric strings in raw or JSON-escaped form and no `review_outputs` directories. Git ignores the corpus and run paths, with no tracked private contents. The actual archive-exclusion test passed after cache remediation. Pattern scans and excerpt inspection do not prove perfect sanitization; original-record comparison and data-owner review remain required. Provider retention/account settings were not inspected. Disabled local capture does not establish provider-side privacy readiness.

## Exact accepted-case repair/adjudication register

Every one of the 44 cases was reviewed. Codes: **F** numeric-format repair; **R** semantic rubric/anchor adjudication; **H** historical original-record revalidation within scope; **G** shared parent/source counting and split decision; **C** pilot-control overlap exclusion; **A** authentication rejection wording. A dash means no additional case-specific repair identified beyond general corpus limitations. Flags are a review queue, not changes to the persisted status.

| Case ID | Label | Grading | Actions |
| --- | --- | --- | --- |
| `case-99465471f1ab25217f3eb4ce` | tray-capacity | Deterministic | H, C |
| `case-356c6836dae623efdff07fd9` | siphon-explanation | Semantic | R, H, C |
| `case-b3cb5a302fc52a4c9901d3b7` | positive-reply | Semantic | R, H, C |
| `case-db1e9fd706c0ce34e13586e9` | mission-note | Semantic | R, H, G |
| `case-67f03d51f98ddf9eee482254` | privacy-note | Semantic | R, H, G |
| `case-955ece6e9e87f00ee2b874ae` | versioning-note | Semantic | R, H, G |
| `case-097d5a0b621754a5bd7fec05` | boundary-note | Semantic | R, H, G |
| `case-d52fef8162f767fc405b1cd0` | non-goals-note | Semantic | R, H, G |
| `case-30f7782a6959ac081d79fba6` | phase-plan | Semantic | R, H, G |
| `case-18adcd080c9a05a2adb2a8b1` | telemetry-note | Semantic | R, H, G |
| `case-193566125edd46e18a149aee` | malformed-paid | Semantic | R |
| `case-1fb42751e8f91b1cc82ceb5a` | incomplete-parse | Semantic | R, G |
| `case-4db17e0e93b20bddb9987518` | usage-integrity | Semantic | R |
| `case-c969e77f084d0de46bcf574d` | sdk-failures | Semantic | R |
| `case-664d19433a6680b058ab2573` | mock-exhaustion | Semantic | R |
| `case-6a42705aa58c7328f7282978` | strict-classification | Semantic | R |
| `case-690948940bbde412442441ef` | classifier-provenance | Semantic | R |
| `case-555addf49086f45952e297d4` | auth-identity | Semantic | R, A |
| `case-7e5e4c68dc37b0a71cc75871` | cross-tenant-read | Semantic | R |
| `case-ef354afb0ee16a65fdec6dd5` | preview-uncertainty | Semantic | R |
| `case-3916a6c54788c3fd18b7ca6d` | restore-evidence | Semantic | R |
| `case-bd29d1663b653c1ff1526348` | editable-smoke | Semantic | R |
| `case-9a28de21f13bbb0a8ff4341e` | partial-costs | Semantic | R |
| `case-974afa79188591375dcd2c29` | attribution | Semantic | R |
| `case-5e1b5481a6a2754cb093bf3b` | judge-attribution | Semantic | R, G |
| `case-1f91937b3d1a83dba30cb810` | partial-ranking | Semantic | R, G |
| `case-5e0dfde57b94a744041a5ecb` | calendar-window | Semantic | R |
| `case-b954ef108e036bb81f26de67` | compatible-quality | Semantic | R |
| `case-55808d5af5d835a3c240577f` | final-judge-error | Semantic | R |
| `case-4df438680253d37591c2891e` | mixed-scales | Semantic | R |
| `case-8c16171f346624d6cfa41097` | parallel-evaluators | Semantic | R |
| `case-bbb7e2b7816b90020174807d` | synthetic-isolation | Semantic | R |
| `case-7733fc892b01be03fd15c754` | usage-map | Deterministic | — |
| `case-e78ea16b93538660b983cb17` | retry-header | Deterministic | — |
| `case-633b4e2c00a6f7e509c18541` | incomplete-fields | Deterministic | G |
| `case-28a18a670a9cafcefeecf4c6` | structured-answer | Deterministic | — |
| `case-607eeb5fd782032de85dada7` | provider-scope | Deterministic | G |
| `case-3cc4efaf470e8cb62b607555` | package-entry | Deterministic | — |
| `case-4ad7c10f3079ec0caec87352` | unauthenticated-shape | Deterministic | — |
| `case-340bf58ac845f59e0437ebcb` | partial-cost-shape | Deterministic | G |
| `case-7aa2acab6a2ffb801c3dc912` | terminal-ecps | Deterministic | — |
| `case-48a79eaf84219b89b3753a42` | precise-money | Deterministic | F |
| `case-621cf8523fbb48b4227f78d9` | latency-percentile | Deterministic | F |
| `case-3fc6345b3fc71f02e0d5c1fb` | tool-recovery-rate | Deterministic | — |

**37 unique accepted cases have at least one follow-up flag; seven have none.** This comprises 31 semantic cases, the historical deterministic tray case, two numeric-format cases, and three source-sharing deterministic cases. Flags overlap. F identifies demonstrated false-negative grading; R/H/G/C/A require review, not automatic rejection.

## Exact seven deferred candidates

These IDs are `candidate_id` values in `T/decisions.json`; they are not runnable `case_id` records. For every row, also recover the original source into the repository under appropriate privacy handling, verify it against its retained locator/hash, retain source/adaptation distinctions, and review sanitization before intake. For the six agent-* rows, add a hash for the retained sanitized summary as well.

| Candidate ID | Label / family | What is needed before reconsideration |
| --- | --- | --- |
| `candidate-d8a0783c61087103e6e542a9` | agent-phase2 / coding | Pinned starting tree, complete classifier/provider assignment and dependencies, trusted filesystem/code sandbox, deterministic executable acceptance tests and output-diff review. |
| `candidate-b75829ad9c3b7090271a15d2` | agent-phase3 / tool_workflow | Pinned implementation task and repository state, reproducible tool trajectory, isolated filesystem/Git execution, explicit side-effect boundaries and executable acceptance evidence. Preserve original commit/push scope as source history; do not execute it during intake. |
| `candidate-35a6d1ce2be9d5237022c429` | agent-phase4 / agentic | Original integration requirements, worker inputs/outputs, reproducible multi-agent/tool orchestration and trajectory grader, validation/health/eval acceptance tests. |
| `candidate-054a072b62e7241d26638f7d` | agent-phase5 / tool_workflow | Pinned frontend/data assets, browser/filesystem harness, defined viewport set, visual/accessibility acceptance evidence and screenshot review. |
| `candidate-2429e1229aeefdbfbf897287` | agent-phase6 / agentic | Frozen release inputs, isolated build/load/recovery environment, production-hardening acceptance criteria and relevant operational validators. Preserve operational consequence. |
| `candidate-6f370a6c34e21bc23ddadb7c` | agent-shadow / tool_workflow | Sanitized application context, pinned Router/application releases, replayable runtime/tool observations, account-context evidence without secrets, shadow-isolation and no-side-effect acceptance tests. |
| `candidate-ea4b35c999a7f4f2ff0073de` | obj-edit / engineering | Exact application version, intended OBJ edit and mesh/geometry fixture, pinned documentation/application evidence, and verifiable edit outcome; browser/CAD support if interactive editing is required. |

Deferred family distribution is coding 1, tool_workflow 3, agentic 2, engineering 1. The architecture/calibration v0 harness cannot currently execute these work products fairly. None should be relabeled low-consequence text work merely to fill a category quota.

## Available source locations discovered inside the repository

| Location | Useful evidence / intake limitation |
| --- | --- |
| `T/sources.json`, `T/decisions.json` | Exact source mappings, adaptation notes, original locators, parent attachment hashes and current decisions. Primary local entry point. |
| Git objects at the audited HEAD; `tests/test_phase2_provider.py` | Eight pinned source functions; provider envelopes, failure normalization, usage and privacy fixtures. |
| `tests/test_phase2_classifier.py` | Two pinned source functions; schema validation and trusted classification provenance. |
| `tests/test_phase6_auth.py` | Three pinned source functions; identity, scoping and public error shapes. |
| `tests/test_classify_route.py`; `tests/test_phase6_recovery.py` | One pinned function each; unresolved cost/idempotency and restore integrity. |
| `tests/test_phase6_package.py`; `scripts/verify_release.py` | Two pinned test functions plus two helper excerpts; packaging contract and install acceptance. |
| `tests/test_phase5_analytics.py` | Fourteen pinned functions; money, attribution, quality compatibility, time windows and recovery denominators. |
| `docs/decisions/`, `docs/implementation-spec-v1.md`, `docs/architecture.md`, `docs/routing-policy-v1.md`, `docs/configuration.md`, `config/` | Versioned local contracts. Distinguish normative requirements from historical user-request originals and verify stale status prose against implementation. |
| `evals/cases/`, `evals/fixtures/`, `evals/phase2_data/`, `evals/phase4_data/`, `evals/results/` | Routing oracles, synthetic fixtures and generated results. Useful for validation; not automatically new historical work products or independent calibration cases. |
| `calibration/internal/real-seed-v0.jsonl`, `reviewed-pilot-v1.jsonl`, `pilot-review-v1.json` | Existing controls/earlier decisions and overlap checks; no verified extra quota contribution. |
| `T/build.py`, `freeze.py`, `verify_reproducibility.py`, `sol-review-audit.py`, `audit.py` | Prior construction and mechanics logic. Builders/freezers write artifacts and read external originals; do not run them merely to audit. This segment imported only the independent derivation helper, never its external-reading main routine. |
| `T/intake-summary.json`, `freeze-audit.json`, `sol-review-final.json`, `reproducibility-audit.json`, `regression-summary.json` | Prior claims with pins; corroborate against underlying records, not counts alone. |
| `R/`; `.calibration/reviewed-pilot-v1/` | Retained experiment manifests, snapshots, journals and reports. Mock results are mechanics evidence only. |
| `T/source-search-audit.json`, `file-inventory*.txt`, `leo-object-inventory.txt` | Previous broader source-search inventories. Their sibling-project findings were not independently repeated under this repository-only scope. |
| `.release/final-live-20260907/`; `docs/evidence/live-verification-2026-09-07.json` | Existing earlier release/provider verification artifacts, not tranche application replays. Inventory only; no live scripts executed or new source-history inference. |
| `docs/previews/`, `examples/`, dashboard source | Existing visual/code context; outputs and demo artifacts do not establish historical demand or a replay trajectory. |

Original chat exports and attachment bytes referenced by the source map are not repository-local source records. No sibling project, original attachment store or external chat was mined in this segment. The prior search report says requested farm/refrigeration/engineering spreadsheet material was absent in its broader search; that is retained historical search evidence, not a fresh claim that such sources do not exist elsewhere.

## Verified offline runs and disabled canary

Loaded the three retained final-tranche runs through `CalibrationStore.load`, validating manifest and snapshot checksums and recounting rows/calls. No new experiment runs were created.

| Mode | Run ID | Rows | Dispositions per strategy |
| --- | --- | ---: | --- |
| Primary | `calibration-907c83365f8b43328b9551a5fc225482` | 132 | 44 PASS |
| Repeat | `calibration-05630f4b25c7414b911a7f75b3458695` | 132 | 44 PASS |
| Deterministic negative control | `calibration-17a0ad3209584db2ad0350e755e33b31` | 132 | 31 PASS, 13 FAIL |

Each run has 44 rows per strategy, 44 classifier calls, 132 generation calls and 93 semantic judge calls; fixed baselines incur no classifier calls. All are marked offline and completed, pin the same final corpus, and retain 44 comparable pairs per baseline with no exclusions. Recomputed simulated production cost is $0.088704, judging overhead $0.1116 and inclusive experiment cost $0.200304 per run; recorded paid cost is $0. These checks establish integrity of local simulated evidence, not account-wide billing or model quality. Constant mock scores do not validate semantic rubrics.

The **calibration** canary is disabled: `live_enabled: false`, capture false, and null release/allocation fields in `proposed-canary-disabled-v1.yaml`. Its four mapped cases are retry-header, precise-money, malformed-paid and siphon-explanation; all subset generation inputs match their parents. The selected precise-money case is affected by F above, so the existing subset should remain frozen/disabled while a replacement version is reviewed.

A fresh provider-free call to `plan_budget` for the exact four-case subset reproduces **$3.2210944** against the pinned current repository config and **$4 proposed cap**, reserving at most 12 generation, 4 classifier and 24 evaluator calls. Retained independent cost components sum to the same result: $0.6144 Router generation + $0.131072 Terra + $0.24576 Sol + $0.0180224 classification + $2.21184 evaluation/retries. This is a config-based bound, not current market/account pricing verification, live admission approval or a completed canary. No paid budget was allocated. Older production release canary artifacts elsewhere in the repository do not mean this calibration canary ran.

## Segment 2 intake priorities

1. Set the counting contract before expansion: retain a versioned `work_product_id`, parent workflow/source identity, control overlap, adaptation type and split group. Adjudicate the 35/32 conservative groups versus separately deliverable outputs; never use the convenient number 41 without naming its unit.
2. Repair the two demonstrated numeric grading mismatches in a **new** corpus version, with appropriate focused validation. Adjudicate semantic critical omissions, equivalent answers and the authentication wording; calibrate human anchors before treating semantic PASS as quality ground truth. Preserve all prior frozen bytes and failed/ambiguous evidence.
3. Recover original historical evidence into the repository with approved sanitization and compare it with the retained pins. Resolve all H flags and parent relationships. Record unverifiable origin explicitly instead of promoting a historical label by assertion.
4. Prioritize genuinely distinct physical-engineering and tool/agentic sources: these account for the nominal 11 + 5 case-allocation gaps. No suitable additional engineering records were established here. Keep operational/tool candidates deferred until the necessary harness exists; do not fill those gaps by renaming software architecture.
5. Within available local source material, favor distinct structured-data/extraction inputs with independently checkable answers and dated, frozen analysis source tables. Avoid further slicing the same analytics/provider test functions to increase the count. Collect original requests and failure outcomes, not generated narrative alone.
6. Preserve parent groups across development/judge-calibration/held-out splits, diversify beyond this single repository and low-consequence text, and keep the pilot, canary, candidate versions and mock artifacts out of additive milestone counts. No intake priority authorizes paid work.

## Commands, targeted tests and results

All shell work ran from the repository root. Reads used `rg`, `cat`, `sed`, Python JSON/AST inspection and pinned `git show`; no source builder, full release verifier, full backend suite, PostgreSQL service or frontend suite was run.

Repository/instruction checks:

```sh
pwd
rg --files --hidden --no-ignore -g 'AGENTS.md' -g '!node_modules' -g '!.venv' -g '!.git'
cat AGENTS.md
git status --short --branch
git log -1 --format=fuller
git remote -v
git rev-list --left-right --count HEAD...@{upstream}
git show-ref refs/remotes/origin/main
git log --oneline origin/main..HEAD
git ls-remote origin refs/heads/main
git check-ignore calibration/internal/tranche-v1/provenance-tranche-v1.jsonl .calibration/provenance-tranche-v1 .calibration/segment-1
git ls-files calibration/internal .calibration
```

The first test setup command was `env UV_CACHE_DIR=.uv-cache UV_PROJECT_ENVIRONMENT=.venv uv run --offline --frozen --extra dev pytest ...` with the ten calibration test files below. It stopped before tests because `pygments==2.21.0` was absent from the local cache; it created an ignored `.venv`. A subsequent `uv run --offline --no-project --no-sync ...` launch without `UV_CACHE_DIR` failed sandbox access to the default cache. The approved retry explicitly used an in-repository cache and an existing Python 3.12.14 runtime. No dependencies were downloaded and no runtime outside the repository was modified.

Initial executed targeted suite:

```sh
env UV_CACHE_DIR=.uv-cache uv run --offline --no-project --no-sync \
  /private/tmp/model-router-pilot-pg-venv/bin/python -m pytest \
  tests/test_calibration_corpus.py tests/test_calibration_grading.py \
  tests/test_calibration_privacy.py tests/test_calibration_runner.py \
  tests/test_calibration_budget.py tests/test_calibration_storage.py \
  tests/test_calibration_output.py tests/test_calibration_allocation.py \
  tests/test_calibration_cli.py tests/test_calibration_analytics.py \
  --basetemp=.calibration/segment-1-pytest \
  -o cache_dir=.calibration/segment-1-pytest-cache
```

Result: **104 passed, 1 failed in 3.21s**. The failure was `test_actual_source_archive_has_no_private_calibration_content`, whose offline subprocess could not resolve `hatchling==1.27.0` from the initially empty cache. A direct diagnostic `uv build --offline` against that test's copied checkout confirmed the missing-cache cause. No assertion about leaked contents failed.

Remediation and isolated retest:

```sh
cp -R /private/tmp/openai-model-router-uv-cache .calibration/segment-1-build-cache
env UV_CACHE_DIR=.calibration/segment-1-build-cache uv run --offline --no-project \
  /private/tmp/model-router-pilot-pg-venv/bin/python -m pytest \
  tests/test_calibration_privacy.py::test_actual_source_archive_has_no_private_calibration_content \
  --basetemp=.calibration/segment-1-archive-retest \
  -o cache_dir=.calibration/segment-1-pytest-cache
```

Result: **1 passed in 1.85s**. Across the initial run and isolated retest, **all 105 distinct targeted calibration tests passed**. There was no unnecessary full-suite rerun. Existing autouse test guards remove live credentials/opt-ins and deny socket access; the archive subprocess is explicitly offline. `--no-sync` emitted a harmless warning that it has no effect with `--no-project`.

A retained read-only audit script performed the final corpus/source pin, count/group, deterministic-grader, comparison-hash, run-store, permission, privacy, budget-plan and log-hash checks:

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src UV_CACHE_DIR=.uv-cache \
  uv run --offline --no-project /private/tmp/model-router-pilot-pg-venv/bin/python \
  .calibration/segment-1/audit.py > .calibration/segment-1/audit.json
```

Result: **exit 0**. Networking is denied in the script and live opt-ins/credentials are removed. It loads existing runs and calls deterministic grading/planning only. An initial audit-script assertion compared a stored comparison hash with a generation-only hash; correcting the audit to the documented `canonical_comparison_sha256` made it pass. This was an audit-code error, not a corpus or runtime repair. Supplementary read-only loader checks validated all seven corpus versions and exact-input overlaps; manual inspection covered all 44 case bodies/rubrics and seven deferral/source summaries.

The older **859 backend / 4 PostgreSQL / 21 frontend** claims are historical evidence, not fresh test totals. The hash-pinned `calibration/internal/provenance-release-verification-v1-repeat.log` contains `859 passed, 5 skipped` and 21 frontend tests across three files. The PostgreSQL log contains four passing dots at 100%; `regression-summary.json` identifies them as four passing integration tests. Both log byte hashes match their recorded pins. This confirms retained evidence consistency; full historical execution provenance was not reconstructed, and those broad gates were intentionally not rerun.

Final checks: `git diff --check`, protected-file hash comparison, handoff completeness/case-ID checks, and an explicit one-file staged diff before the local commit. Only the handoff is staged; no private evidence or pre-existing untracked report is included.

```sh
git add docs/calibration/flight-handoff-segment-1.md
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
git commit -m "Document calibration Segment 1 ground-truth audit"
git status --short --branch
git log -1 --format=%H
git rev-list --left-right --count HEAD...@{upstream}
```

The initial sandboxed `git add` could not create the index lock; the approved retry staged only the handoff.

## Files changed and remaining uncertainties

Committed change: **`docs/calibration/flight-handoff-segment-1.md` only**. Local ignored audit output is under `.calibration/segment-1/`; test/build work is under `.calibration/segment-1-*`, `.uv-cache/` and `.venv/`. These are generated work areas, not new corpus sources or cases. Existing corpus, source/decision map, configurations, retained runs and the two pre-existing untracked reports are unchanged.

Remaining uncertainties: the agreed unit for a distinct work product; independence beyond source grouping; original historical record validity/sanitization outside this repository; representative workload/category/consequence coverage; semantic judge calibration and style bias; acceptable numeric serialization until repaired; tool/agentic execution support; provider account/privacy/pricing/release evidence; and changes to the remote after the recorded check. No quality, savings, canary readiness or quota-completion claim is supported by the mock results. Segment 2 can start from these paths, pins, exact IDs and review actions without conversational memory, but must retain access to the ignored local evidence directory.

Local audit script SHA-256: `5b66e40557a73a27a34998c548ccd49147f1dcac607a61a4f1b3842872673cd8`. Local audit JSON SHA-256: `4a53a8c1a706f6ec048af6f78b930d72a06743df2f0ffc43e5e14a402c7fd4e5`.
