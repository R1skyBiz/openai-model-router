# Calibration methodology

The question is whether dynamic Router execution lowers Effective Cost per Successful
Task (ECPS) against Terra/medium and Sol/medium, without materially lowering quality
or reliability on representative real workloads. This Phase 1 builds the laboratory;
the committed sample is a harness fixture, not benchmark evidence.

## Fair comparison

Each case supplies one canonical task/instructions/context/output contract. The
classification call and every generation strategy use that same canonical payload.
Family hints, source labels, tags, privacy and grading references are annotations,
never classifier inputs. Capability requirements, output/schema constraints, tool
availability, consequence, and deadline limits are shared. Model-specific constraints
must reject or explicitly document a comparison; silent prompt changes are prohibited.

Execution order is seeded and randomized per case. Candidate labels and grading
order are randomized separately before judging. A judge sees the requested task,
constraints, candidate and pinned rubric/reference evidence, with no model, route,
strategy, cost or latency. Provider metadata is attached to retained scores after
invocation. Blinding cannot erase stylistic clues inside generated text; randomized
labels do not eliminate model-judge bias or prompt injection risk.

Production V0 checks are common execution requirements; corpus grading determines
whether the requested result was achieved. Unsupported tool execution, unavailable
required production validation, or invalid grading contracts must remain visible.
They must never silently be waived to improve Router results. Baselines have one
generation attempt; Router recovery occurs only when explicitly configured and
follows existing bounded recovery rules. Calibration judges cannot trigger routing
recovery or rewrite policy. Thus blind grading can expose a production V0 false
positive, but never silently repairs it.

## Grading hierarchy

Prefer exact answers, structured schemas, numeric tolerances, required/forbidden
fields and trusted invariant checks. The schema grader validates a documented
subset and fails closed for unsupported keywords. Arbitrary corpus shell commands
and code execution are not supported. A fixture reference is INVALID until a trusted
sandbox adapter is available.

Semantic grading uses a separately invoked evaluator and a rubric ID/version, explicit
scale, threshold and optional reference facts. A successful below-threshold score can
establish FAIL. Timeouts, invalid scores, rubric mismatches and outages cannot establish
a task failure; they remain UNKNOWN/NEEDS_REVIEW after bounded evaluator-only retries.
Every invocation cost remains visible, including failed evaluations.

When `deterministic_authoritative` is true, deterministic evidence may settle the
outcome despite a semantic contradiction. Authors must enable this only when the
checks actually measure the requested result; structural JSON validity alone is
usually insufficient. Contradictions remain in the review queue. Otherwise conflicting
judgments require review or an explicitly configured adjudicator. Human-only cases
are exported with opaque candidate/run references; a human reviews the protected
corpus and any separately retained output under its privacy policy. Capture defaults off. An explicitly configured protected review-output export
retains a content-hashed reference for review; otherwise embedded callers must
consume the in-memory candidate before it is discarded. The CLI cannot recreate
unretained output.

An optional stronger evaluator uses configured model/effort, sample probability,
maximum adjudications, finite retries and call limits. No model is unconditionally
required as judge. Human review should audit judge disagreements, false positives,
and a random sample of agreements before treating scores as trustworthy. This
approach follows the general guidance to use task-specific tests and account for
judge bias in [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

## Cost and denominators

For each strategy, production-equivalent cost is the sum of classifier (Router only),
all generation attempts, retries/escalations and required production validation.
Fixed baselines never pay a classifier fee. Calibration judging, adjudication and
other experimental strategies are excluded from that strategy's production cost.
Total experiment spend sums every strategy's production work plus all judges and
adjudication, including unresolved/invalidated work already performed.

Resolved means PASS or FAIL. Canonical ECPS is:

```text
sum(production-equivalent cost of every resolved attempted task)
----------------------------------------------------------------
number of PASS tasks
```

FAIL costs remain in the numerator. UNKNOWN, NEEDS_REVIEW and INVALID are reported
separately and excluded from resolved denominators. Their incurred spend remains in
experiment-inclusive totals. This exclusion can bias ECPS if unresolved cases are
systematic; report coverage and paired resolved sample sizes alongside ECPS.
Missing included costs make ECPS unavailable, preserving the known subtotal. Zero
passes or no resolved data likewise produces null rather than zero or infinity.

Pass rate/final success use PASS / resolved. First-pass success uses final PASS with
one generation and no actual recovery / resolved. UNKNOWN rate uses UNKNOWN / all
recorded case-strategy rows; unresolved rate additionally includes NEEDS_REVIEW.
Invalid pre-dispatch rows do not inflate attempted calls. Router escalation rate
uses resolved Router tasks with intelligence escalation / resolved Router tasks.
Classifier spend includes all classifier calls. Quantiles use nearest ranks.
Latency covers generation-attempted case-strategy execution and excludes subsequent
calibration judging. Monetary calculations and JSON amounts use Decimal/decimal strings.
Offline costs are simulated and total actual paid spend is zero.

Segmentation uses family, complexity band, initial model/effort, source kind,
consequence, policy version and tags, always retaining the strategy dimension.
Initial-route cohorts attribute downstream recovery cost to that route. Spend
breakdown uses the actual calls. Annotation absence is explicit, never fabricated.

## Descriptive observations

Paired comparisons require the same canonical input hash and validation signature,
with both final results resolved. Unknown, missing and incomparable evidence is
excluded from paired differences and reported explicitly. Differences are absolute
Router minus baseline and relative to baseline; zero baseline denominators are null.

An over-routing candidate means materially greater initial generation cost than a
passing comparable cheaper baseline, under a configurable ratio. Classifier overhead
alone cannot establish this observation. An under-routing candidate means initial
quality/validation failure or intelligence escalation while a configured stronger
baseline passes on its first attempt. Infrastructure outages alone do not establish
under-routing. Neither observation automatically diagnoses the optimal route.

Cheapest observed passing strategy compares only passing tested strategies with
comparable validation and complete costs. Ties are preserved. This is observed
success, not proof about any untested cheaper route or a causal optimum.

Every cohort reports sample size. Below the configured minimum (sample config: 30
resolved cases), display INSUFFICIENT SAMPLE. Individual pass proportions include
descriptive 95% Wilson intervals assuming independent representative cases. These
are not confidence intervals for paired ECPS differences. No automatic significance
claim or p-value-based policy decision is made. Duplicates, repeated tasks, family
imbalance, judge correlation and workload drift can invalidate simple assumptions.

## Later policy proposals

Assemble a representative, deduplicated historical corpus, pre-register its strata,
quality thresholds, review plan and experiment allocation, and review missingness
before interpreting results. A future policy proposal must cite the frozen evidence,
identify affected routing envelopes, create a new policy version, pass the independent
179-case oracle and regressions, and receive explicit human-controlled activation.
No experiment modifies the existing policy or oracle.
