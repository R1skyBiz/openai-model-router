# Phase 5 metric definitions

Phase 5 analytics are descriptive read models over retained `TaskResult` and
`ExecutionEvent` evidence. They do not execute tasks, probe dependencies, apply
current tariffs to historical usage, or alter routing policy. Money aggregation
uses `Decimal` arithmetic in an isolated context. API monetary values are decimal
strings.

## Cohorts and filters

The selected task cohort contains tasks admitted through `created_at` in the
half-open UTC window `[start, end)`. The default window is the 30 days preceding
`now`. `now`, `start`, `end`, task timestamps, and event timestamps must be
timezone-aware. Inputs are normalized to UTC; naive or reversed windows are
rejected.

Application, task family, policy version, and status are task attributes. Model
and effort have two deliberate meanings:

- Task KPIs, routing views, and the task explorer filter by the initial
  production generation route.
- Spend filters and groupings use the actual invoked model and effort for each
  charge. A recovered task initially routed to Luna can therefore appear in the
  Luna task cohort while its later Terra call appears under Terra spend.

When provider evidence is retained, its model, effort, and policy identify the
invocation. An incomplete evaluator intent without provider evidence uses its
evaluator reference and the task's pinned Phase 4 evaluator binding. Other
incomplete attempts fall back to their retained route decision.

Production composition excludes any task whose initial route, retained decision,
or production generation attempt route is marked synthetic. Attempt evidence is
the fallback for legacy/interrupted tasks without a retained initial decision.
Explicit demo composition selects only synthetic route
evidence and marks every response `meta.synthetic=true`. Event freshness and fee
correlation use only events belonging to the selected composition and task
attribute scope.

## Task outcome metrics

Let `T` be the selected admission cohort. Let `C` be tasks in `T` with status
`succeeded`, `failed`, or `cancelled`, and let `S` be succeeded tasks in `C`.
Cancelled tasks are terminal and remain in denominators. Blocked tasks remain
pending for compatibility with the frozen Phase 5 contract, are excluded from
`C`, and are reported separately. All other nonterminal states are pending.

| Metric | Formula |
| --- | --- |
| Total tasks | `count(T)` |
| Terminal tasks | `count(C)` |
| Pending tasks | `count(T - C)`, including blocked |
| Final success | `count(S) / count(C)` |
| First-pass success | Succeeded tasks with exactly one invoked production generation attempt and no action that caused recovery work, divided by `count(C)` |
| Intelligence escalation | Tasks in `C` with an effort/tier increase or a positive quality-escalation counter, divided by `count(C)` |
| Tool recovery | Tasks in `C` with retry/alternate-tool evidence or a positive tool-recovery counter, divided by `count(C)` |
| Infrastructure retry | Additional production provider calls following `TIMEOUT`, `RATE_LIMIT`, or `PROVIDER_FAILURE`, divided by all invoked production provider calls in `C` |
| Task cost | Sum of persisted production `total_cost_usd` for `C` |
| Cost per task | Task cost divided by `count(C)` |
| Effective cost per success | Task cost, including unsuccessful and recovery cost, divided by `count(S)` |
| P50/P95 task latency | Nearest-rank quantiles of `updated_at - created_at` for `C` |

The terminal `stop_success` record is completion bookkeeping and does not make a
successful task a recovered task. Effort/tier changes, generation or classifier
infrastructure retries, repeated evaluator calls for the same target/reference,
repeated same-tool/same-operation calls, positive recovery counters, tool
retries/alternates, health-aware fallback, and diagnostic recovery do. Distinct
required evaluator references or target attempts are separate validation work,
not retries.

Infrastructure retry is an attempt metric. Production generation,
classification, and evaluator calls are in its denominator; tool calls are not.
Retries are recognized within the same call purpose. Evaluator retries must also
share their parent generation attempt and evaluator reference. Quality-driven
generation attempts increase the provider-call denominator but not the
infrastructure-retry numerator.

Task latency is an admission-to-latest-task-update approximation because the
current persisted contract has no separate terminal timestamp. Terminal task
snapshots are immutable, so `updated_at` is the retained terminal time for normal
execution. A defensive zero floor prevents corrupt reversed timestamps from
producing negative dashboard latency.

## Cost completeness

A cost object has `amount`, `known_subtotal`, `missing_count`, and `status`.

- `known`: every included charge or task total is known; `amount` equals the
  complete aggregate.
- `partial`: at least one included charge or task total is unknown; `amount` is
  null and `known_subtotal` preserves observed cost.
- `unavailable`: the cohort or charge set is empty; `amount` is null and the
  known subtotal is zero.

Unknown is never displayed as zero, and estimates never replace actual fees.
`missing_count` counts incomplete charge records in spend views and incomplete
task totals in completion views. A successful terminal task with a persisted
known zero total contributes a known zero. When a ratio denominator is zero, its
amount is unavailable because dollars per task/success is undefined; the related
rate likewise has a null value with explicit numerator and denominator.

Completion metrics trust the persisted historical task total and known subtotal.
This preserves fees from failed attempts and all production work without
re-pricing usage. Shadow cost is excluded.

## Spend occurrence accounting

Spend uses the fee occurrence time in `[start, end)` independently of task
admission time, so an old task with current in-flight work contributes current
spend. The charge ledger uses these non-overlapping authorities:

- model calls: `Attempt.actual_cost_usd`, including production generation,
  classification, evaluator, and shadow attempts;
- direct generation validation: validation outcomes without an
  `evaluator_attempt_id`;
- evaluator validation results: zero-fee references only; the evaluator attempt
  owns the model-call fee and is counted once;
- domain validation: the domain validation outcome;
- tools: `ToolOutcome.cost_usd`;
- shadow: attempts nested in `ShadowRun`, always reported separately.

Attempt fees use attempt completion time, falling back to start time for an
unfinished intent. A cancelled pre-dispatch attempt with no provider evidence is
not an invoked call or spend charge even when settlement records known zero.
Timestamp-less validation and tool fees use a correlated outbox completion/start
event. Fees with no correlated time appear under `unallocated`; they are excluded
from the selected-window production, shadow, all-spend, series, and grouping
totals. The unallocated view includes all otherwise eligible unplaceable fees
because there is no defensible timestamp with which to include or exclude them
from the requested window.

Every retained tool outcome is invocation evidence. A succeeded, failed,
started, or unknown tool outcome with no actual fee remains an unknown charge;
neither a missing estimate nor a terminal status silently removes it from spend.

`production` and `shadow` are occurrence-window totals. `all_spend` combines only
those two visible totals. Spend groups contain production charges only, and group
`count` is charge count rather than task count. Purpose retains the invocation
purpose (`generation`, `classification`, `evaluation`, `validation`, or `tool`).
Groups sort by known subtotal from highest to lowest with a stable key tie-break.
When any charge is incomplete, response notes state that this is not an exact
complete-cost ranking.
Contribution labels additional generation and evaluator calls, and subsequent
same-tool/same-operation calls, as `retry`; other fees retain their generation,
validation, classification, or tool contribution. This retry label describes
incremental work and includes both quality escalation and infrastructure
recovery.

The current tool record has no explicit predecessor/recovery ID. The contribution
breakdown therefore infers a subsequent same-tool/same-operation call as retry
work. The separate tool-recovery task rate uses explicit recovery actions and
counters and is authoritative when the two views differ.

## UTC calendar spend and projection

Summary spend today is production occurrence spend from UTC midnight to `now`.
Month-to-date spend is production occurrence spend from the first UTC day of the
month to `now`. These windows ignore the selected start/end window but retain all
non-time filters.

Projected monthly spend uses:

```text
month-to-date production spend * UTC month duration / elapsed UTC month seconds
```

The method is `linear_mtd_run_rate`. A partial MTD cost produces a partial
projection from its known subtotal and preserves the missing-evidence count. An
empty MTD charge set or zero elapsed time produces unavailable projection. It is
a run-rate display, not a budget commitment.

Daily spend series use UTC calendar days touched by the selected window.
Cumulative production begins at the selected window, not at the beginning of all
retained history. Unallocated charges do not enter the series.

## Routing and efficacy

Model, reasoning-effort, complexity, task-family, and validation distributions
use the initial production generation route. Shares use the number of routed
tasks as their distribution denominator. Unrouted tasks remain in task KPI
cohorts but not route distributions. Task-family-to-model flow uses one edge per
initial route. Escalation flow records quality-driven effort/tier targets from the
initial route. Preferred-floor relaxation and constrained fallback are task rates
over initially routed tasks and use retained rationale codes.

Efficacy groups tasks by initial model and effort and attributes every downstream
production cost and final outcome to that initial route. Model and task-family
endpoints expose the same KPI/quality cohort shape. Policy comparisons group by
the task's pinned policy version. Any policy cohort with fewer than 30 terminal
tasks is labeled insufficient; this is a display guard and makes no significance
claim.

Routing trend points recompute completion KPIs for each UTC admission day in the
selected window. Days without admitted tasks retain null-rate and unavailable-
cost semantics.

## Evaluator quality

Quality includes only finite scores from final applicable `passed` or `failed`
evaluator observations. For each target attempt, rubric version, check, and role,
the last retained observation wins, preventing evaluator retries from counting
multiple scores for the same target. Target identity is scoped by task because
adapters are not required to make their local target IDs globally unique. The
final applicable observation is selected before score validity is checked, so a
later skipped/error outcome suppresses an earlier score rather than resurrecting
stale quality evidence. Skipped/error outcomes and missing or non-finite scores
are excluded rather than converted to zero.

Scores are grouped by the exact tuple of rubric version, check, score minimum,
score maximum, and role. A cohort is comparable only when exactly one such group
has observations. Multiple groups return their separate means and sample sizes
with reason `mixed_rubric_check_scale_or_role`; no observations return
`no_comparable_evaluator_scores`. Production efficacy does not merge shadow
quality into production quality.
