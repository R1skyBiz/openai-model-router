# Owner review packet v1 — Segment 2.5

Review target: frozen `provenance-tranche-v2`, from local HEAD `dc2ed56b18980ff6bf8d69bf515dee8da2abcde3`. The checkout had no tracked/staged changes and two pre-existing untracked reports, which this segment preserves. This packet changes no corpus decision. Baseline: **44 accepted/repaired, 0 rejected, 7 deferred, 35 conservative groups; gaps 25 to 60 and 165 to 200**.

## How to review in 15–25 minutes

Allow 2 minutes for these rules, 12–17 minutes for the 35 cards (about 20–30 seconds each), and 3–5 minutes for the deferred queue. This is a triage and task-boundary pass, not full rubric certification. Record an exception or follow-up instead of resolving a difficult rubric inline. Full review of 31 semantic rubrics, answer anchors and original records requires separate sessions.

Each card lists every included case exactly once. Category means the stored case family/families, not a new domain classification. Provenance labels are retained classifications, not new independent verification. Descriptions paraphrase only subjects already safely represented in the committed handoffs and public repository tests; the actual 44-case corpus remains internal and ignored. The public sample is a separate harness fixture.

**Shared rubric concern R:** all 31 semantic cases use five equally weighted dimensions and threshold 0.8; four complete dimensions can mask an absent critical fifth. Decide must-pass requirements and omission, partial, equivalent-correct and contradiction anchors. Recommendations identify review work; they do not implement rubric changes or establish independent human agreement. A group containing both semantic and deterministic cases is labeled per case, not as a mixed-grading case (there are zero mixed cases).

**Shared grouping concern F:** each repository group is one pinned function under `parent-source-v1`. Multiple functions may belong to one implementation investigation. All 34 fixture cases remain in one repository-wide split group. “Accept provisional” means retain this accounting unit pending broader task-boundary evidence, not certify job independence or historical demand. “Merge” keeps existing grouped views together without deleting case records. A proposed Split needs separate original deliverables and acceptance evidence; output format alone is insufficient.

Decision choices on every card: **Accept / Merge / Split / Repair / Defer / Reject**. All fields start blank. Any owner decision is a proposal for a future version; retain frozen corpus bytes. Keep identifying notes in a private copy outside Git; public notes may contain only opaque references and sanitized decisions. Reviewer: ______  Date: ______  Counting contract accepted or proposed revision: ______

## The 35 conservative work-product groups

### 01. Tray capacity — `work-b15f0ea18ba21bff9caead9f`

**Cases / grading:** `case-99465471f1ab25217f3eb4ce` (tray-capacity, deterministic).\
**Category:** math. **Provenance:** `historical_real`.\
**Original task subject:** Calculate tray volume and convert units. **Capability:** Geometry, units and requested numeric formatting.\
**Grouping:** One retained request locator and excerpt; one case. This parent overlaps an existing pilot control. **Split/merge ambiguity:** Original recovery may change the task boundary; exclude the pilot overlap from additive counts. Original-record revalidation remains pending.\
**Grading concern:** Independent derivation passed; confirm units and two-decimal output. Original and pilot overlap still need review.\
**Recommended disposition:** Defer historical certification pending the original; retain the existing provisional group and status.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 02. Siphon explanation — `work-fa32fafd5b30822aeb13acd6`

**Cases / grading:** `case-356c6836dae623efdff07fd9` (siphon-explanation, semantic).\
**Category:** engineering. **Provenance:** `historical_real`.\
**Original task subject:** Explain siphon behavior from a bounded physical setup. **Capability:** Causal fluid-system reasoning.\
**Grouping:** One retained request locator and excerpt; one case. This parent overlaps an existing pilot control. **Split/merge ambiguity:** Original recovery may change the task boundary; exclude the pilot overlap from additive counts. Original-record revalidation remains pending.\
**Grading concern:** R: distinguish physical explanation from an operational diagnosis; recover original constraints.\
**Recommended disposition:** Defer historical certification pending the original; retain the existing provisional group and status.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 03. Positive reply — `work-aa105bdf69d338d46ea7ce58`

**Cases / grading:** `case-b3cb5a302fc52a4c9901d3b7` (positive-reply, semantic).\
**Category:** writing. **Provenance:** `historical_real`.\
**Original task subject:** Draft a positive response from sanitized correspondence context. **Capability:** Tone and faithful writing without invented facts.\
**Grouping:** One retained request locator and excerpt; one case. This parent overlaps an existing pilot control. **Split/merge ambiguity:** Original recovery may change the task boundary; exclude the pilot overlap from additive counts. Original-record revalidation remains pending.\
**Grading concern:** R: agree tone/completeness anchors without recovering identifying correspondence into this packet.\
**Recommended disposition:** Defer historical certification pending the original; retain the existing provisional group and status.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 04. Architecture assignment — `work-a007d74568c1fc01141799a0`

**Cases / grading:** `case-db1e9fd706c0ce34e13586e9` (mission-note, semantic); `case-67f03d51f98ddf9eee482254` (privacy-note, semantic); `case-955ece6e9e87f00ee2b874ae` (versioning-note, semantic); `case-097d5a0b621754a5bd7fec05` (boundary-note, semantic); `case-d52fef8162f767fc405b1cd0` (non-goals-note, semantic); `case-30f7782a6959ac081d79fba6` (phase-plan, semantic); `case-18adcd080c9a05a2adb2a8b1` (telemetry-note, semantic).\
**Category:** writing, planning. **Provenance:** `historical_real`.\
**Original task subject:** Produce mission, privacy, versioning, boundary, non-goals, phase-plan and telemetry sections. **Capability:** Faithful synthesis of one architecture contract.\
**Grouping:** One original architecture assignment supplies seven sections. Keep merged; separate section formats do not establish separate work products. **Split/merge ambiguity:** A split would need separately commissioned deliverables. Local attachment/section verification is recorded in Segment 2; rubric adjudication remains open.\
**Grading concern:** R for all seven rubrics: mark required privacy and boundary constraints; a missing secrets prohibition must be explicitly adjudicated.\
**Recommended disposition:** Merge (retain the existing seven-case group); Repair rubric definitions after human adjudication.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 05. Malformed response evidence — `work-b7c4662a9b73c53e27083fa3`

**Cases / grading:** `case-193566125edd46e18a149aee` (malformed-paid, semantic).\
**Category:** debugging. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain handling of malformed structured output while retaining safe paid-usage evidence. **Capability:** Separate output failure, incurred cost and privacy.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: decide whether loss of paid evidence or raw-content retention must fail.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 06. Incomplete and refusal results — `work-64ba9dd09253b93399b30d13`

**Cases / grading:** `case-1fb42751e8f91b1cc82ceb5a` (incomplete-parse, semantic); `case-633b4e2c00a6f7e509c18541` (incomplete-fields, deterministic).\
**Category:** architecture, extract. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain incomplete/refusal handling and extract its result fields. **Capability:** Status normalization and safe structured extraction.\
**Grouping:** Two views of the same pinned test function; keep merged. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R on explanation; deterministic fields must preserve incomplete/refusal distinctions and avoid content parsing.\
**Recommended disposition:** Merge paired views; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 07. Invalid usage — `work-4770af481e50dce3418e42d1`

**Cases / grading:** `case-4db17e0e93b20bddb9987518` (usage-integrity, semantic).\
**Category:** debugging. **Provenance:** `coding_fixture`.\
**Original task subject:** Diagnose malformed usage rather than silently converting it to unknown usage. **Capability:** Evidence integrity and failure classification.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: require the malformed/unknown distinction; define acceptable partial answers.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 08. SDK infrastructure failures — `work-3dee58e7594a6ce44159cb52`

**Cases / grading:** `case-c969e77f084d0de46bcf574d` (sdk-failures, semantic).\
**Category:** architecture. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain normalization of SDK failures without adapter retry or escalation. **Capability:** Infrastructure boundaries and recovery ownership.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: decide whether invented retry/escalation behavior is disqualifying.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 09. Mock exhaustion — `work-4298f49e87b918c79a9cf93b`

**Cases / grading:** `case-664d19433a6680b058ab2573` (mock-exhaustion, semantic).\
**Category:** architecture. **Provenance:** `coding_fixture`.\
**Original task subject:** Describe explicit mock exhaustion and content-free call recording. **Capability:** Deterministic mock behavior and privacy.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: adjudicate omission of exhaustion behavior or raw-content exclusion.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 10. Strict classification — `work-642a1ab8c7b3398e35254243`

**Cases / grading:** `case-6a42705aa58c7328f7282978` (strict-classification, semantic).\
**Category:** architecture. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain rejection of invalid classifier output without retaining its values. **Capability:** Strict contracts and safe error handling.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: decide which schema and privacy omissions must fail.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 11. Classifier provenance — `work-7b4363e95dd83e3f3ff5578e`

**Cases / grading:** `case-690948940bbde412442441ef` (classifier-provenance, semantic).\
**Category:** architecture. **Provenance:** `coding_fixture`.\
**Original task subject:** Describe trusted provenance assignment and recomputation of classification totals. **Capability:** Server-owned evidence and accounting consistency.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: require trusted provenance and recomputation rather than supplied totals.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 12. Authentication identity — `work-63caf8eb7316f5d8a39ce7db`

**Cases / grading:** `case-555addf49086f45952e297d4` (auth-identity, semantic).\
**Category:** architecture. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain protection against spoofed query/header/environment identity. **Capability:** Trusted tenant identity and secure boundary behavior.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: v2 permits secure ignore/override of query/header identity and rejects forbidden body identity. Owner must adjudicate repaired wording and anchors.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 13. Cross-application reads — `work-59b607f2f1643ee4e47f7669`

**Cases / grading:** `case-7e5e4c68dc37b0a71cc75871` (cross-tenant-read, semantic).\
**Category:** architecture. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain fail-closed task and telemetry reads across applications. **Capability:** Isolation and access-control reasoning.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: adjudicate whether either unscoped read is a critical failure.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 14. Unknown cost reservation — `work-cc464b92d17b53b208af496b`

**Cases / grading:** `case-ef354afb0ee16a65fdec6dd5` (preview-uncertainty, semantic).\
**Category:** architecture. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain retaining reservations and avoiding replay when cost is unknown. **Capability:** Uncertain spend and idempotency.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: require both reservation retention and no duplicate execution.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 15. Restore integrity — `work-8bcf72754452227fdc0e3e8e`

**Cases / grading:** `case-3916a6c54788c3fd18b7ca6d` (restore-evidence, semantic).\
**Category:** architecture. **Provenance:** `coding_fixture`.\
**Original task subject:** Describe restoration of allocation, outbox and idempotency evidence from a quiescent backup. **Capability:** Recovery invariants and durable state.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: identify mandatory restored evidence; this text case does not execute recovery.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 16. Editable-install smoke — `work-8d60ca39133c181fd23b7099`

**Cases / grading:** `case-bd29d1663b653c1ff1526348` (editable-smoke, semantic).\
**Category:** debugging. **Provenance:** `coding_fixture`.\
**Original task subject:** Diagnose a fresh editable install without dashboard assets. **Capability:** Packaging boundaries and reproducible diagnosis.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: distinguish an environment/import defect from a packaging change; no install is executed by this case.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 17. Unknown and partial costs — `work-775b9e0a0d3b368f2a8ed933`

**Cases / grading:** `case-9a28de21f13bbb0a8ff4341e` (partial-costs, semantic).\
**Category:** analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain why unknown, partial and empty costs do not become zero. **Capability:** Honest aggregation under missing evidence.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: require each missingness distinction; agree partial-credit anchors.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 18. Task versus spend attribution — `work-d886c2e4756474d8361b5177`

**Cases / grading:** `case-974afa79188591375dcd2c29` (attribution, semantic).\
**Category:** analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain initial-route ownership of task KPIs and invoked-route ownership of spend. **Capability:** Correct metric grain and attribution.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: decide whether conflating route ownership is a critical failure.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 19. Evaluator spend attribution — `work-5b13fbb20afc4480bc892266`

**Cases / grading:** `case-5e1b5481a6a2754cb093bf3b` (judge-attribution, semantic); `case-607eeb5fd782032de85dada7` (provider-scope, deterministic).\
**Category:** analysis, extract. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain provider-evidence ownership of evaluator model/effort spend and extract its scope. **Capability:** Evidence-based attribution and structured extraction.\
**Grouping:** Two views of the same pinned test function; keep merged. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R on explanation; deterministic extraction must retain provider scope. Known near-duplicate pair shares one parent.\
**Recommended disposition:** Merge paired views; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 20. Partial-cost ranking — `work-41952d2aca4f098b0e80cabb`

**Cases / grading:** `case-1f91937b3d1a83dba30cb810` (partial-ranking, semantic); `case-340bf58ac845f59e0437ebcb` (partial-cost-shape, deterministic).\
**Category:** analysis, extract. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain ordering by known subtotal and extract the partial-ranking disclosure. **Capability:** Transparent ranking with incomplete cost evidence.\
**Grouping:** Two views of the same pinned test function; keep merged. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R on explanation; deterministic fields must retain partial status and correct ranking basis.\
**Recommended disposition:** Merge paired views; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 21. Calendar spend window — `work-2cc2bce8b25a03b88faae836`

**Cases / grading:** `case-5e0dfde57b94a744041a5ecb` (calendar-window, semantic).\
**Category:** analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain calendar spend and linear projection independent of a selected display window. **Capability:** Time-scope and projection reasoning.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: distinguish calendar scope from selected-window filtering; avoid implying a forecast guarantee.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 22. Compatible quality scores — `work-6403756bbdf79d33eb84b6dc`

**Cases / grading:** `case-b954ef108e036bb81f26de67` (compatible-quality, semantic).\
**Category:** analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain final-score selection per target and separation of incompatible rubrics. **Capability:** Comparable quality aggregation.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: require finality and rubric compatibility; no judge-quality conclusion follows.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 23. Final evaluator error — `work-01e4ab59131c8a0ce44c63ab`

**Cases / grading:** `case-55808d5af5d835a3c240577f` (final-judge-error, semantic).\
**Category:** analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain task-scoped target IDs and a final error superseding a prior score. **Capability:** Evidence identity and finality.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: decide whether retaining an obsolete score must fail.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 24. Mixed score scales — `work-7f781d7c6bd4cbdd0858250c`

**Cases / grading:** `case-4df438680253d37591c2891e` (mixed-scales, semantic).\
**Category:** analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain why identical rubric labels with different scales are incomparable. **Capability:** Metric compatibility and scale reasoning.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: adjudicate invalid pooling despite matching rubric identity.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 25. Required evaluators — `work-5ef29cfb1384a906e2023307`

**Cases / grading:** `case-8c16171f346624d6cfa41097` (parallel-evaluators, semantic).\
**Category:** analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Distinguish separate required evaluators from evaluator retries. **Capability:** Invocation purpose and retry accounting.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: require distinct evaluator identity/purpose rather than counting all extra calls as retries.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 26. Synthetic evidence isolation — `work-f61e2db91a2fd2f006f23906`

**Cases / grading:** `case-bbb7e2b7816b90020174807d` (synthetic-isolation, semantic).\
**Category:** analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Explain isolation of synthetic composition and marking its metadata. **Capability:** Evidence provenance and reporting limits.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** R: require explicit synthetic provenance; mock success is mechanics evidence only.\
**Recommended disposition:** Accept provisional fixture unit; adjudicate R before quality use.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 27. Usage mapping — `work-7105d57c85d2eae20cc4f647`

**Cases / grading:** `case-7733fc892b01be03fd15c754` (usage-map, deterministic).\
**Category:** transform. **Provenance:** `coding_fixture`.\
**Original task subject:** Transform provider usage into the requested structured result. **Capability:** Nested mapping and preservation of supplied usage facts.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** Deterministic JSON: confirm exact fields/types; schema validity alone is insufficient.\
**Recommended disposition:** Accept provisional fixture unit; retain current deterministic contract.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 28. Safe retry metadata — `work-0d9030ddc760a836803d5cac`

**Cases / grading:** `case-e78ea16b93538660b983cb17` (retry-header, deterministic).\
**Category:** transform. **Provenance:** `coding_fixture`.\
**Original task subject:** Transform rate-limit evidence into safe retry metadata. **Capability:** Selective extraction and exclusion of unsafe data.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** Deterministic JSON: retain permitted retry fields only; check omissions and extra fields.\
**Recommended disposition:** Accept provisional fixture unit; retain current deterministic contract.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 29. Structured answer — `work-9f0ab9bda08735ea124d53e2`

**Cases / grading:** `case-28a18a670a9cafcefeecf4c6` (structured-answer, deterministic).\
**Category:** extract. **Provenance:** `coding_fixture`.\
**Original task subject:** Extract the parsed structured answer from raw-response handling evidence. **Capability:** Response/parsed-model distinctions.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** Deterministic JSON: confirm parsed values and output shape, not narrative equivalence.\
**Recommended disposition:** Accept provisional fixture unit; retain current deterministic contract.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 30. Package metadata — `work-cd2630a245a19706a285275c`

**Cases / grading:** `case-3cc4efaf470e8cb62b607555` (package-entry, deterministic).\
**Category:** extract. **Provenance:** `coding_fixture`.\
**Original task subject:** Extract declared release metadata, runtime and resources. **Capability:** Reading a pinned packaging contract.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** Deterministic JSON: judge against the pinned fixture; later package versions are separate evidence.\
**Recommended disposition:** Accept provisional fixture unit; retain current deterministic contract.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 31. Public endpoint surface — `work-76722887519491de5c54e19c`

**Cases / grading:** `case-4ad7c10f3079ec0caec87352` (unauthenticated-shape, deterministic).\
**Category:** extract. **Provenance:** `coding_fixture`.\
**Original task subject:** Extract the minimal public surface and authentication requirement elsewhere. **Capability:** API access-boundary extraction.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** Deterministic JSON: missing protected endpoints or added public access must not pass.\
**Recommended disposition:** Accept provisional fixture unit; retain current deterministic contract.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 32. Terminal task cost — `work-3ccd3a16b6b2387c33fb11fb`

**Cases / grading:** `case-7aa2acab6a2ffb801c3dc912` (terminal-ecps, deterministic).\
**Category:** data_analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Calculate cost per terminal task using explicit task-state denominators. **Capability:** Numerator/denominator discipline.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** Deterministic two-decimal output: this fixture cancellation convention does not redefine Calibration Lab PASS/FAIL ECPS.\
**Recommended disposition:** Accept provisional fixture unit; retain current deterministic contract.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 33. Precise monetary mean — `work-202ad5d39cff8ef0cd27a6a0`

**Cases / grading:** `case-48a79eaf84219b89b3753a42` (precise-money, deterministic).\
**Category:** data_analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Calculate a decimal monetary aggregate despite hostile ambient precision. **Capability:** Exact decimal arithmetic.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** v2 zero-tolerance numeric repair verified; equivalent trailing-zero/scientific notation passes, incorrect or non-finite values fail.\
**Recommended disposition:** Accept provisional fixture unit; retain current deterministic contract.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 34. Windowed percentile — `work-9522493760288ecc9ba26f34`

**Cases / grading:** `case-621cf8523fbb48b4227f78d9` (latency-percentile, deterministic).\
**Category:** data_analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Calculate a nearest-rank latency percentile in a half-open UTC window. **Capability:** Window boundaries and order statistics.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** v2 zero-tolerance numeric repair verified; confirm inclusion boundaries/rank, with equivalent numeric notation accepted.\
**Recommended disposition:** Accept provisional fixture unit; retain current deterministic contract.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

### 35. Recovery task rate — `work-09058b57559537a47320e11e`

**Cases / grading:** `case-3fc6345b3fc71f02e0d5c1fb` (tool-recovery-rate, deterministic).\
**Category:** data_analysis. **Provenance:** `coding_fixture`.\
**Original task subject:** Calculate tool recovery as a task rate without inflating infrastructure retries. **Capability:** Task-level denominators and failure taxonomy.\
**Grouping:** One separate pinned test function; retain one provisional fixture unit. **Split/merge ambiguity:** F: broader implementation investigation may require merging with related functions; no source-supported split is proposed.\
**Grading concern:** Deterministic two-decimal output; this arithmetic fixture provides no executed tool-workflow coverage.\
**Recommended disposition:** Accept provisional fixture unit; retain current deterministic contract.\
**Owner decision:** ☐ Accept ☐ Merge ☐ Split ☐ Repair ☐ Defer ☐ Reject\
**Owner notes:** ______

## Seven deferred candidates

These are candidate IDs, not accepted runnable case IDs. All seven remain deferred and contribute zero to the 35-group baseline. Owner judgment alone cannot resolve any row: it can set scope or commission recovery, but cannot supply missing fixtures or executable acceptance evidence. The six implementation attachments and derived-summary hashes were verified in Segment 2; that does not establish replay readiness. No new original is accessed here. The separate pilot’s 12 deferrals are not part of this queue.

| Candidate / subject | Why deferred; blocker classes | Exact evidence needed | Owner judgment alone? / next action |
| --- | --- | --- | --- |
| `candidate-d8a0783c61087103e6e542a9` / agent-phase2 | Implementation cannot be fairly graded as text. **External-tool dependence, grading, missing context.** | Pinned starting tree and dependencies; complete classifier/provider assignment; isolated code/filesystem runner; executable acceptance tests and reviewed resulting diff. | **No.** Recover a reproducible checkout and acceptance bundle; keep deferred until the runner exists. |
| `candidate-b75829ad9c3b7090271a15d2` / agent-phase3 | Tool/Git implementation trajectory unavailable. **External-tool dependence, grading, missing context.** | Pinned task/tree, recorded or reproducible tool steps, filesystem/Git isolation, explicit side-effect boundaries and executable acceptance results. | **No.** Specify a local replay harness. Original commit/push instructions remain historical evidence, not execution authorization. |
| `candidate-35a6d1ce2be9d5237022c429` / agent-phase4 | Orchestration success needs trajectory evidence. **External-tool dependence, grading, missing context.** | Integration requirements, worker inputs/outputs, reproducible orchestration, trajectory grader and validation/health/eval acceptance fixtures. | **No.** Assemble a frozen orchestration bundle and grade observable outcomes. |
| `candidate-054a072b62e7241d26638f7d` / agent-phase5 | Frontend outcomes need browser and visual validation. **External-tool dependence, grading, missing context.** | Pinned frontend/data assets, browser/filesystem runner, viewport set, visual/accessibility criteria and reviewed screenshots. | **No.** Recover assets and define visual acceptance before replay. |
| `candidate-2429e1229aeefdbfbf897287` / agent-phase6 | Operational hardening cannot be reduced to low-consequence prose. **External-tool dependence, grading, missing context.** | Frozen release inputs, isolated build/load/recovery environment, original consequence and executable operational validators. | **No.** Define a contained operational replay; preserve consequence. |
| `candidate-6f370a6c34e21bc23ddadb7c` / agent-shadow | Application/account/runtime evidence is incomplete. **Privacy, external-tool dependence, grading, missing context.** | Sanitized application context, pinned application/Router releases, replayable runtime/tool observations, secret-free account evidence, shadow-isolation and no-side-effect acceptance tests. | **No.** Recover an owner-approved sanitized observation bundle; do not contact accounts or run a live shadow test during intake. |
| `candidate-ea4b35c999a7f4f2ff0073de` / obj-edit | Original task and verifiable edit context absent. **Provenance, missing context, grading, external-tool dependence; possible duplication.** | Authorized original chat, exact intended edit, application/version documentation, sanitized mesh fixture and objective before/after geometry checks; resolve possible overlap with prior pilot `hist-knowledge-obj-fusion-001`. | **No.** Recover original and non-proprietary geometry; adjudicate overlap; add CAD/browser support if needed. |

All rows also require data-owner sanitization review before new derived content is accepted. No confirmed duplication or new provenance failure is inferred for the six verified implementation assignments. Their related phases may still belong to a broader workflow and must not automatically count as six independent additions.

## Evidence and follow-through

The [Segment 2 handoff](flight-handoff-segment-2.md) supplies the full public case/source/group map and repair pins; [Segment 1](flight-handoff-segment-1.md) supplies case labels and original review flags, superseded by Segment 2 repairs. Private review targets are `calibration/internal/tranche-v2/provenance-tranche-v2.jsonl`, `work-products.json`, `decisions.json` and `semantic-review-queue.json` alongside it. A fresh clone lacks these private files. Use a private review copy for rubric text and source locators.

Finish by recording proposed task-boundary exceptions, critical rubric issues and source requests. Recalculate the milestone only after adjudication; do not count repeated versions, pilot overlaps or mock runs as additions. See the [source gap plan](source-gap-plan-v1.md) and [private intake guide](private-source-intake-guide.md). Canary remains disabled; no paid calls, corpus edits or remote push are authorized by this packet.
