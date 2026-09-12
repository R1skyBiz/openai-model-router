# Calibration milestone review — Segment 3

Reviewed 2026-09-10 in the retained Model Router worktree. **Recommendation: NO-GO for a frozen calibration release candidate and for paid execution of the current four-case canary.** Software regression and packaging checks pass after documented environment fixes. Corpus integrity passes, but grading completeness, historical-source verification and representative coverage remain unresolved. No new frozen calibration release candidate was produced.

The current revision remains **44 accepted case records / 35 conservative parent-source work-product groups**, or **32 groups after excluding three pilot overlaps**. Segment 2 did not reach 60 work products and added no new cases. The gap toward approximately 200 is **156 case records, 165 parent-source groups, or 168 non-pilot groups**, depending on the explicitly named unit. Independence of original jobs has not been established.

No paid API calls, live calibration, canary execution, spending authorization, new calibration allocation, policy activation or push occurred. The existing canary remains disabled and unallocated. Its fresh configuration-based conservative bound is **$3.2210944**, with a **proposed, unallocated $4 hard cap**. Mock results, authored probes and AI ratings establish neither Router quality nor judge accuracy, savings or representative task success.

**Repository and evidence scope.** Read both flight handoffs, root `AGENTS.md`, the corpus/methodology contracts and ADR 0017 before validation. The hidden/ignored-inclusive instruction search found only root `AGENTS.md`. Starting HEAD was `47d9b0a8d32399a5bb7c0c0343cdde35a5d6bd69`, the Segment 2 reporting commit, on `main`, four ahead and zero behind the local `origin/main` reference. No tracked or staged changes were present. Remote freshness was not queried.

The pre-existing untracked reports `docs/calibration-canary-readiness-v1.md` and `docs/calibration-provenance-tranche-v1.md` remain byte-identical and excluded from this commit. Fresh preservation checks cover **465 prior tracked/private/report files**, plus the Segment 2 preservation and artifact inventories. No prior corpus, manifest, source register, decision, retained calibration run or policy/oracle was changed. Checks read the seven exact local attachments already identified by the source map; no broader private-data search occurred.

**Counts and disposition.** The v2 JSONL, adjacent manifest, decision register and work-product register agree. All 44 case IDs and full-case hashes validate. There are 41 distinct accepted source references, 35 parent-source groups and five conservative split groups. These units are not interchangeable.

| Disposition accounting | Total |
| --- | ---: |
| Accepted records in v2, combined persisted status `accepted_repaired` | 44 |
| Accepted without repair under the original status vocabulary | 0 |
| Segment 2 retained without grading change, within those 44 | 41 |
| Segment 2 grading repairs, within those 44 | 3 |
| Segment 3 additions or repairs | 0 |
| Rejected in this tranche | 0 |
| Deferred in this tranche | 7 |
| Prior pilot deferrals, separate intake | 12 |

The three repairs are precise-money and latency-percentile numeric equivalence, plus auth-identity wording. The 31 semantic cases remain retained offline fixtures requiring adjudication; that is not final benchmark acceptance. This review does not silently rewrite their persisted status as rejected or deferred.

| Provenance | Case records | Parent-source groups | Fresh evidence |
| --- | ---: | ---: | --- |
| `coding_fixture` | 34 | 31 | Pinned repository functions, not production observations |
| `historical_real` | 10 | 4 | Seven sections from one verified attachment; three chat originals unresolved |
| `application_replay` | 0 | 0 | None |
| `authored_realistic` / `synthetic_control` | 0 / 0 | 0 / 0 | The separate pilot is not included |

| Category | Families | Cases | Proposed 200-case allocation | Record gap |
| --- | --- | ---: | ---: | ---: |
| Engineering | engineering 1 | 1 | 45 | 44 |
| Coding / debugging / architecture | debugging 3; architecture 9 | 12 | 35 | 23 |
| Analysis / research | analysis 10 | 10 | 35 | 25 |
| Writing / planning | writing 7; planning 1 | 8 | 30 | 22 |
| Extract / transform / knowledge | extract 6; transform 2 | 8 | 30 | 22 |
| Data / math / structured | data_analysis 4; math 1 | 5 | 15 | 10 |
| Tool / agentic | none | 0 | 10 | 10 |
| Total | | **44** | **200** | **156** |

These allocations remain proposals, not approved sampling quotas. All 44 cases are internal, low-consequence bounded text tasks: 13 deterministic, 31 semantic, zero mixed. Eight deterministic cases have JSON contracts. No executed-code, tool trajectory, operational replay or higher-consequence coverage is established.

**Fresh validation findings.** The Segment 2 verifier passes, and a separate Segment 3 audit validates current records, sources, original attachment bytes, deterministic answers, duplicates, privacy, input isolation and the canary plan. The earlier Segment 1 run-integrity audit was also rerun against the retained v1 stores.

| Check | Finding |
| --- | --- |
| Schema and hashes | All 44 v2 cases and pinned manifest hashes pass; prior snapshots remain unchanged. |
| Provenance | All 48 source excerpts/summaries hash correctly; 31 function blobs/excerpts and two helpers match pinned Git objects. Seven identified attachment byte hashes match, including the original underlying seven accepted documentation sections. |
| Historical limits | Tray-capacity, siphon-explanation and positive-reply still lack identified authorized original chat records. The CAD deferral also lacks its original chat/fixture. A retained excerpt hash does not prove origin or complete sanitization. |
| Exact duplicates | 44 unique canonical inputs. Zero exact input overlaps with sample, seed or pilot. Version copies and subset membership are not additions. |
| Near duplicates | All 946 accepted pairs screened at task/context token-set Jaccard ≥0.35; one pair at 0.3684, judge-attribution/provider-scope, already grouped. Screening is not semantic independence certification. |
| Grouping | Seven architecture sections share one parent; three function-derived pairs share parents. All repository fixtures share one conservative split group. Three pilot overlaps remain explicitly bound and excluded from non-pilot counts. |
| Sanitization/privacy | Reviewed accepted task/context/grading content; full-record secret-pattern matches: zero. Corpus/source files remain 0600 and directories 0700, ignored and untracked. Original-record and data-owner review remain necessary. |
| Deterministic truth | All 13 expectations independently rederived from generation inputs through the audited derivation helper and checked against the actual grader. Fresh input inspection corroborates the helper's numeric constants. 55 assertions passed: 13 expectation comparisons and 42 valid/invalid output checks. |
| Numeric repairs | Equivalent trailing-zero/scientific forms pass both v2 numeric graders; wrong values differing by `1e-21`, malformed and non-finite forms fail. The old canary still has the unrepaired precise-money contract. |
| Strategy isolation | Every v2 canonical comparison input/envelope equals its v1 parent. Generation payloads exclude provenance, group IDs and full rubric instructions. Retained three-strategy runs have matching input hashes and validation signatures; fixed baselines have no classifier calls. |
| Leakage limits | Supplied task facts can properly overlap reference facts. Mock answers and authored anchors are review material only. No held-out contamination or model-memorization claim can be tested here. |
| Archive privacy | Newly built wheel and sdist contain no internal calibration/run/review-output paths or full accepted task/context strings. The actual private-content exclusion test also passes. |

The seven existing deferrals retain their original intent: agent-phase2 needs an executable code/test fixture; agent-phase3 needs reproducible tool/Git state; agent-phase4 needs orchestration trajectories; agent-phase5 needs browser/visual acceptance; agent-phase6 needs isolated operational release acceptance; agent-shadow needs sanitized replay/account context; obj-edit needs the intended edit, original request, mesh and application evidence. Their family totals remain coding 1, tool_workflow 3, agentic 2 and engineering 1. All 26 prior pilot dispositions remain accounted for separately, including 12 deferrals. No deferred operational task was reduced to text to fill a quota.

**Second-pass AI adjudication and its limits.** Used the existing `BlindCandidate` and `BlindGrader` contracts. A seeded permutation assigned opaque review IDs to all 44 cases, with mappings retained separately. Reviewed all 31 semantic task/context/rubric packets and the 13 deterministic cases. Packets omit source, route, strategy, model, cost and latency annotations; model names that are task facts remain visible. Case-specific proposed critical criteria and findings are retained in `.calibration/segment-3/semantic-adjudication.json`.

This is **strategy-metadata-blinded AI review, not human agreement or a fully independent double-blind review**. The same assistant had read the handoffs and prior findings; tasks and rubric IDs may be recognizable. The six existing canary probe drafts and their intended labels were also visible before scoring, so expectation blinding is not claimed. No additional reviewer agent or provider judge was invoked. Actual human reviews completed: **zero**.

The existing five equally weighted criteria still allow four complete criteria plus one absent criterion to reach 0.8. All 31 submitted scalar-boundary probes return PASS through the existing grader. This verifies score aggregation behavior only; it does not show that a real judge would assign those scores. The generic falsehood/constraint cap does not explicitly resolve every critical omission, and the runtime accepts a scalar without enforcing per-criterion compliance.

The pass also identified specific completeness questions. Non-goals compresses a supplied exclusion list without naming micro-categories; telemetry compresses attempt fields without separately anchoring estimated cost and provider ID. Five design cases require a focused regression proposal in their instructions without an explicit criterion scoring it: `case-ef354afb0ee16a65fdec6dd5`, `case-6a42705aa58c7328f7282978`, `case-c969e77f084d0de46bcf574d`, `case-690948940bbde412442441ef` and `case-1fb42751e8f91b1cc82ceb5a`. An evaluator might apply the generic constraint cap, but omission handling is not sufficiently specified to certify it. Auth-identity's repair is source-supported; make the source-specific body-rejection requirement clear in the candidate contract and adjudicate acceptable alternatives.

The six pre-existing authored canary answers were rated per criterion and submitted to the grader's adjudicator interface as local AI annotations:

| Authored probe | AI score | AI disposition |
| --- | ---: | --- |
| malformed-paid: complete | 1.0 | PASS |
| malformed-paid: material falsehood/privacy violation | 0.0 | FAIL |
| malformed-paid: incomplete evidence/privacy regression | 0.7 | FAIL |
| siphon-explanation: complete general explanation | 1.0 | PASS |
| siphon-explanation: invented diagnosis/material falsehood | 0.0 | FAIL |
| siphon-explanation: incomplete mechanisms/observations | 0.2 | FAIL |

Thus **2 AI PASS / 4 AI FAIL**, with no human agreement statistic. These are authored anchors, not six historical cases or six generated model outputs. The adapter inserts unknown-call evidence for submitted scores without provider receipts; those retained placeholders are not provider invocations, bills or experiment outcomes. Raw review packets remain in the ignored mode-0700 evidence directory; safe review records reference hashes. No live capture was enabled.

Human review must settle all 31 semantic critical requirements, omission/partial/equivalent/contradictory answers and threshold boundaries, including the six canary drafts. It must also resolve historical originals and sanitization, accept the work-product/split counting contract, adjudicate near duplicates and broader workflow independence, and approve any claims of representative coverage. AI review and deterministic tests cannot provide those agreements.

**Model-family coverage.** Configuration includes Luna, Terra, Sol and Astra; fixed comparisons use Terra/medium and Sol/medium, and the configured semantic judge is Sol/medium with no secondary provider adjudicator. The retained primary mock run has 44 Router initial routes at Luna/none, 44 Terra/medium baselines and 44 Sol/medium baselines. These are scripted route observations, not measured coverage of real model success. Astra generation and other effort combinations have no live calibration evidence. Sol's dual baseline/judge role remains a possible style-bias source. Routing/classification oracle coverage below does not substitute for calibration workload coverage.

**Fresh tests and release checks.** Logs, JUnit results, evaluation JSON and command records are under `.calibration/segment-3/`. Python used the existing 3.12.14 runtime through `uv --offline --no-project`; the copied populated cache was used. Credentials/live opt-ins were removed. Default tests deny Python network access; PostgreSQL used only the new disposable localhost database, which was stopped afterward. No dependency or model download occurred.

| Gate | Final result |
| --- | --- |
| Complete backend suite, after isolated packaging retest | **859 distinct passed**, five initially skipped |
| PostgreSQL integration | **4 passed**, resolving the four PostgreSQL skips above |
| Calibration suite, included in backend total | **105 passed** across ten calibration files |
| Frontend | **21 passed** across three files |
| Unique backend + PostgreSQL + frontend | **884 passed**, one paid-live test intentionally skipped |
| Phase 1 routing | 142/142 applicable pass; 37 outside this phase |
| Phase 2 classification | 19/19 mock seeds pass; zero live invocations |
| Phase 3 execution/recovery | 178/178 applicable pass; one scenario deferred to Phase 4 |
| Phase 4 remaining / combined | 1/1 and 179/179 pass |
| Phase 4 additional regressions | 22/22 pass |
| Source/YAML/TOML/skill links, lock, policy/oracle integrity | Pass |
| Frontend typecheck and production build | Pass |
| Synthetic load/recovery exercise | Pass; configured latency/throughput gates met, 1,000-task telemetry fixture |
| Wheel/sdist build and archive contracts | Pass |
| Installed wheel SQLite migrations/imports | Pass |
| Clean editable install outside checkout, without dashboard assets | Pass; CLI/import/migration checks pass |

Phase totals overlap the same 179-case oracle and are not additive. Calibration tests are part of the backend count. The initial backend invocation was **858 passed, 1 failed, 5 skipped**: its editable-install subprocess resolved a relative `UV_CACHE_DIR` under a temporary checkout and could not find the locked SQLAlchemy wheel offline. The isolated retest passed with an absolute populated cache path. No packaging code, Hatchling configuration or lockfile changed.

The first PostgreSQL attempt produced **four setup errors** because the sandbox denied localhost TCP. The approved retry reached the new cluster but produced **four setup errors** because `initdb --no-locale` had defaulted to SQL_ASCII, causing SQLAlchemy's version parser to receive bytes. A fresh UTF-8 database from template0 corrected setup; all four integration tests then passed. Earlier logs remain available. Final unresolved test failures: **zero**. Backend warnings were dependency deprecations. The local release workflow was exercised; the CI Docker container build was not run and no container/deployment certification is claimed.

Reproduction uses the retained private scripts: `audit.py` and `adjudicate.py` create exclusive evidence files and should run only in a fresh evidence directory; they refuse existing output files. `run_gates.py` records each release command/exit code in `gates.json` and directs evaluation outputs away from prior artifacts. `final_verify.py` rechecks preservation, unique test totals and archive privacy. The broad regression command was:

```sh
env -u OPENAI_API_KEY -u RUN_LIVE_OPENAI_TESTS -u RUN_LIVE_CALIBRATION \
  -u POSTGRES_TEST_DATABASE_URL \
  UV_CACHE_DIR='<REPOSITORY_ROOT>/.calibration/segment-1-build-cache' \
  uv run --offline --no-project /private/tmp/model-router-pilot-pg-venv/bin/python \
  -m pytest --basetemp=.calibration/segment-3/backend-tmp \
  -o cache_dir=.calibration/segment-3/pytest-cache \
  --junitxml=.calibration/segment-3/backend.xml
```

The displayed command uses the corrected absolute cache setting; the initial invocation used its relative spelling. The final PostgreSQL run used the same runtime with `tests/test_phase6_postgres.py` and `POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://router_segment3@127.0.0.1:55439/segment3_utf8`. That disposable server is stopped. No production database was used.

**Freeze decision.** No versioned frozen calibration RC was produced. A passing software suite is insufficient: rubric completeness/omission behavior remains underspecified, original evidence is missing for three retained historical cases, and category/source coverage does not meet the proposed milestone. Human adjudication is also outstanding. The existing hash-pinned `provenance-tranche-v2` remains an offline development revision; its existing manifest is not a newly certified RC. Wheel/sdist artifacts built for software release checks are unrelated to freezing the calibration corpus.

**Exact disabled canary and recalculated budget.** The current subset remains `calibration/internal/tranche-v1/proposed-canary-v1.jsonl`, governed by `proposed-canary-disabled-v1.yaml`:

| Case | Exact ID | Current caveat |
| --- | --- | --- |
| retry-header | `case-e78ea16b93538660b983cb17` | Deterministic extraction |
| precise-money | `case-48a79eaf84219b89b3753a42` | Old subset still uses exact-string grading; v2 numeric repair is not bound |
| malformed-paid | `case-193566125edd46e18a149aee` | Semantic human anchors pending |
| siphon-explanation | `case-356c6836dae623efdff07fd9` | Semantic anchors and historical original pending; pilot overlap |

Provider-free `plan_budget` against current `config/models.yaml`, `config/classifier.yaml` and the exact disabled experiment returns an arithmetically admissible plan with no cost-planning blockers. This is not live authorization or current account-price verification.

| Conservative component | USD |
| --- | ---: |
| Router generation: four calls at maximum enabled-model tariff | 0.6144 |
| Terra baseline: four calls | 0.131072 |
| Sol baseline: four calls | 0.24576 |
| Classifier: four calls | 0.0180224 |
| Evaluators including one retry: at most 24 calls | 2.21184 |
| **Total bound** | **3.2210944** |
| **Proposed hard cap, unallocated** | **4.0000000** |
| Headroom | 0.7789056 |

Maximum dispatch counts are **12 generation + 4 classification + 24 evaluation = 40**. Router recovery is disabled; fixed baselines get one attempt. Generation/classification input cap is 8,192 tokens, generation output cap 1,024; judge caps are 16,384 input / 512 output with one retry, and classifier output cap is taken from its configuration. The planner uses the worst configured ordinary/cached/cache-write input tariff and output price, with Astra bounding Router generation. It conservatively reserves judging for every candidate, including deterministic cases. No stronger adjudicator is configured. Any model, subset, token/retry limit, evaluator, service tier or tariff change requires recalculation.

Verified: `live_enabled=false`, `capture_review_outputs=false`, and null `release_manifest`, `allocation_id`, `allocation_cap_usd` and `allocation_directory`. No canary allocation was created. Test-local allocation fixtures are not paid allocations. The $25 proposal remains unauthorized. These checks concern the calibration canary, not account-wide billing or unrelated historical release probes.

**Conditions before any paid execution.** All remain gates, not authorization granted by this report:

1. Resolve the corpus release blockers and human critical-criteria/anchor decisions in a new version, preserve prior bytes, rerun validation, and freeze an explicitly scoped release candidate. Do not manufacture source history or interpret mock PASS as quality evidence.
2. Rebuild a separately versioned four-case subset from the approved parent, including the numeric repair; pin every case, rubric, manifest and configuration hash. Resolve the siphon source/privacy gate or explicitly approve a justified replacement with new hashes and a new cost plan.
3. Obtain actual human ratings for complete, incomplete, omission, contradiction and equivalent-answer anchors. Audit disagreements and sampled agreements; establish zero false passes on agreed clear-negative canary anchors before judging quality. The six draft ratings here do not meet that requirement.
4. Obtain named data-owner/operator approval for the exact sanitized tasks and judge references transmitted, provenance rights, account/project retention and training-sharing controls, model exceptions, endpoint/region and caching behavior. `store=false` alone does not establish zero retention. Keep live review-output capture off unless separately approved with retention/deletion controls.
5. Verify applicable account access, model/effort support, standard-tier and cache/region prices against the intended account. Recalculate the conservative bound and approve a sufficient finite hard cap; the present $4 is only a proposal.
6. Assemble a clean pinned immutable software/experiment release matching policy and classifier hashes, enabled operations, privacy allowlist and all generation/classifier/evaluator limits. Obtain fresh credential-bound evidence required by the live gates. Existing unrelated release evidence is not reusable by assumption.
7. Against that exact release, pass no-paid transport fault probes for timeout after dispatch, unpriced/malformed responses, restart with an outstanding action and non-replay/idempotency. Verify durable reservation, uncertain-cost retention, stop behavior and protected-output handling. General regression success is not a new exact-release attestation.
8. Obtain explicit user authorization for this exact run and cap. Only afterward provision its separate durable allocation, verify available balance and matching IDs/paths, enable the explicit live configuration/runtime opt-in, and execute once. A credential, arithmetic plan or this recommendation is not spending approval. Stop on uncertainty, guard failure or unpriced work; reconcile before any separately approved rerun.

The corpus still needs genuinely distinct source-backed engineering and executable/tool work, broader source diversity, and an owner-approved counting/split contract. The approximately 200-case gap is not closed by candidate versions, canary subsets, pilot overlaps, authored anchor answers or repeated mock runs.

**Pins, files and local commit.** Private evidence remains ignored under `.calibration/segment-3/`; a fresh clone will not contain the corpus or review packets. The following hashes make this report inspectable in the retained worktree:

| Artifact | SHA-256 |
| --- | --- |
| v2 JSONL | `a867cb1241dd0ae7ffc9715ff45cd4167cb8b5d62a8ca1688a3b33fb1cba6e15` |
| v2 manifest | `cb547541135e3b68147576f6be89acf051c2747806575c1877fbbebcb7f80020` |
| Segment 3 corpus audit | `d451c2bf31c2edcc70f3c3c4a4b604512ea486f422e731423f648fd127b59ccf` |
| Semantic adjudication | `e0151597658511cd470cb7306bf2a337de4350ca827d8651e144873f4babe0eb` |
| Authored-anchor adjudication | `434c6ebaeffb1a28a71525a181d134ce760e1d743cb40c8e949aab0e0d4eb0e6` |
| Final preservation/test/archive verification | `2758007ba3b2c4707f36b561f545accf32791b9fda977c1142d985b35191824e` |
| Evidence hash inventory | `9a5c9a3643c9d9a61bc6a419a07dcb6ad48ab15ae5859ced585e7336824b3570` |

Only this report enters the focused local commit, titled `Document calibration milestone review and canary no-go`. Its parent is the starting HEAD above. Resolve its exact hash after creation with `git log -1 --format=%H -- docs/calibration/calibration-milestone-review.md`; a commit cannot contain its own hash. Final status is expected to be five ahead, zero behind the unchanged local tracking reference, with only the two pre-existing untracked reports. The terminal summary records the verified commit and status. No push.
