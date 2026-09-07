"""Pure, Decimal-safe Phase 5 telemetry analytics.

The analytics layer consumes immutable task snapshots and outbox events.  It
does not query storage, price historical usage, or perform provider work.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, MAX_EMAX, MIN_EMIN, localcontext
from math import isfinite
from typing import Any, Iterable

from model_router.core.contracts import FailureType, RouteDecision
from model_router.core.execution_contracts import ExecutionEvent, TaskResult, TaskStatus
from model_router.execution.arithmetic import money_sum
from model_router.telemetry.evidence import (
    initial_route as _initial_route,
    task_is_synthetic as _task_is_synthetic,
)


METRIC_DEFINITION_VERSION = "phase-5-v1"
ZERO = Decimal("0")
TERMINAL = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
INFRASTRUCTURE_FAILURES = {
    FailureType.TIMEOUT,
    FailureType.RATE_LIMIT,
    FailureType.PROVIDER_FAILURE,
}


@dataclass(frozen=True)
class _Charge:
    task: TaskResult
    amount: Decimal | None
    occurred_at: datetime | None
    role: str
    model: str | None
    effort: str | None
    purpose: str
    contribution: str
    policy_version: str


class Analytics:
    """Compute JSON-ready dashboard aggregates from retained evidence."""

    def __init__(
        self,
        tasks: tuple[TaskResult, ...],
        events: tuple[ExecutionEvent, ...],
        *,
        now: datetime,
        filters: dict[str, Any] | None,
        synthetic: bool = False,
    ) -> None:
        self.now = _aware_utc(now, "now")
        supplied = dict(filters or {})
        unknown = set(supplied) - {
            "start", "end", "application", "model", "effort", "task_family",
            "policy_version", "status",
        }
        if unknown:
            raise ValueError(f"unsupported analytics filters: {', '.join(sorted(unknown))}")
        self.start = _aware_utc(supplied.pop("start", self.now - timedelta(days=30)), "start")
        self.end = _aware_utc(supplied.pop("end", self.now), "end")
        if self.start >= self.end:
            raise ValueError("analytics start must be before end")
        self.filters = {name: _filter_text(value) for name, value in supplied.items()}
        self.synthetic = synthetic is True
        # A composition is either explicitly synthetic or production.  Mixing
        # the two would make every production KPI ambiguous.
        self._tasks = tuple(
            task for task in tasks
            if _task_is_synthetic(task) is self.synthetic and self._matches_task_attributes(task)
        )
        task_ids = {task.task_id for task in self._tasks}
        self._events = tuple(event for event in events if event.task_id in task_ids)
        self._event_index = self._index_events(self._events)
        self._cohort = tuple(
            task for task in self._tasks
            if self.start <= _utc(task.created_at) < self.end and self._matches_initial_route(task)
        )
        self._charges = tuple(
            charge for task in self._tasks for charge in self._task_charges(task)
            if self._matches_invoked_route(charge)
        )

    def summary(self) -> dict[str, Any]:
        today = self.now.replace(hour=0, minute=0, second=0, microsecond=0)
        month = today.replace(day=1)
        today_cost = self._spend_cost(today, self.now, role="production")
        mtd_cost = self._spend_cost(month, self.now, role="production")
        projection = self._project(mtd_cost, month)
        return {
            "meta": self._meta(),
            "metrics": self._metrics(self._cohort),
            "spend_today": today_cost,
            "spend_mtd": mtd_cost,
            "projected_month": projection,
            "forecast_method": "linear_mtd_run_rate",
            "policy_versions": sorted({task.policy_version for task in self._cohort}),
        }

    def spend(self) -> dict[str, Any]:
        timed = tuple(
            charge for charge in self._charges
            if charge.occurred_at is not None and self.start <= charge.occurred_at < self.end
        )
        production = tuple(charge for charge in timed if charge.role == "production")
        shadow = tuple(charge for charge in timed if charge.role == "shadow")
        unallocated = tuple(charge for charge in self._charges if charge.occurred_at is None)
        notes = []
        if unallocated:
            notes.append(
                "Spend uses charge occurrence time; unallocated charges are excluded from window totals."
            )
        if any(charge.amount is None for charge in production):
            notes.append(
                "Spend groups with incomplete costs are ranked by known subtotal; order is not a complete-cost ranking."
            )
        cumulative: list[_Charge] = []
        series = []
        for day in _utc_days(self.start, self.end):
            next_day = day + timedelta(days=1)
            day_production = tuple(c for c in production if day <= c.occurred_at < next_day)
            day_shadow = tuple(c for c in shadow if day <= c.occurred_at < next_day)
            cumulative.extend(day_production)
            series.append({
                "date": day.date().isoformat(),
                "production": _charge_cost(day_production),
                "shadow": _charge_cost(day_shadow),
                "cumulative_production": _charge_cost(cumulative),
            })
        return {
            "meta": self._meta(notes=tuple(notes)),
            "production": _charge_cost(production),
            "shadow": _charge_cost(shadow),
            "all_spend": _charge_cost((*production, *shadow)),
            "unallocated": _charge_cost(unallocated),
            "series": series,
            "by_model": self._spend_groups(production, lambda c: c.model or "unassigned"),
            "by_effort": self._spend_groups(production, lambda c: c.effort or "unassigned"),
            "by_application": self._spend_groups(
                production, lambda c: c.task.application_id or "unassigned"
            ),
            "by_task_family": self._spend_groups(
                production, lambda c: _task_family(c.task) or "unassigned"
            ),
            "by_policy": self._spend_groups(production, lambda c: c.policy_version),
            "by_purpose": self._spend_groups(production, lambda c: c.purpose),
            "by_contribution": self._spend_groups(production, lambda c: c.contribution),
        }

    def routing(self) -> dict[str, Any]:
        routed = tuple((task, _initial_route(task)) for task in self._cohort)
        routed = tuple((task, route) for task, route in routed if route is not None)
        models = [route.selected_model_alias for _, route in routed]
        efforts = [str(route.reasoning_effort) for _, route in routed]
        complexities = [str(route.complexity_score) for _, route in routed]
        families = [_task_family(task) or "unassigned" for task, _ in routed]
        validations = [str(route.validation_level) for _, route in routed]
        rationales = [code for _, route in routed for code in route.rationale_codes]
        family_flow = [(family, route.selected_model_alias) for (task, route), family in zip(routed, families)]
        escalation_flow: list[tuple[str, str]] = []
        for task, initial in routed:
            source = _route_key(initial)
            for action in task.recovery_actions:
                if action.action in {"increase_effort", "increase_tier"} and action.route is not None:
                    escalation_flow.append((source, f"{action.route.model}/{action.route.effort}"))
        trend = []
        for day in _utc_days(self.start, self.end):
            daily = tuple(task for task in self._cohort if day <= _utc(task.created_at) < day + timedelta(days=1))
            metrics = self._metrics(daily)
            trend.append({
                "date": day.date().isoformat(),
                "first_pass_success": metrics["first_pass_success"],
                "final_success": metrics["final_success"],
                "effective_cost_per_success": metrics["effective_cost_per_success"],
            })
        return {
            "meta": self._meta(),
            "models": _distribution(models),
            "efforts": _distribution(efforts),
            "complexities": _distribution(complexities),
            "task_families": _distribution(families),
            "validations": _distribution(validations),
            "rationale_codes": _distribution(rationales),
            "family_model_flow": _flows(family_flow),
            "escalation_flow": _flows(escalation_flow),
            "preferred_floor_relaxation": _task_rate(
                routed, lambda pair: "FLOOR_RELAXED" in pair[1].rationale_codes
            ),
            "constrained_fallback": _task_rate(
                routed, lambda pair: "CONSTRAINED_FALLBACK" in pair[1].rationale_codes
            ),
            "trend": trend,
        }

    def efficacy(self) -> dict[str, Any]:
        groups: dict[tuple[str | None, str | None], list[TaskResult]] = defaultdict(list)
        for task in self._cohort:
            route = _initial_route(task)
            groups[(
                route.selected_model_alias if route else None,
                str(route.reasoning_effort) if route else None,
            )].append(task)
        return {
            "meta": self._meta(),
            "cohorts": [
                self._cohort_record(
                    f"{model or 'unrouted'} / {effort or 'unassigned'}",
                    items,
                    model=model,
                    effort=effort,
                    policy_version=None,
                )
                for (model, effort), items in sorted(groups.items(), key=lambda item: _none_sort(item[0]))
            ],
        }

    def policies(self) -> dict[str, Any]:
        groups: dict[str, list[TaskResult]] = defaultdict(list)
        for task in self._cohort:
            groups[task.policy_version].append(task)
        return {
            "meta": self._meta(),
            "cohorts": [
                self._cohort_record(
                    key, items, model=None, effort=None, policy_version=key
                )
                for key, items in sorted(groups.items())
            ],
            "comparison_note": (
                "Policy cohorts are observational; samples under 30 terminal tasks are insufficient."
            ),
        }

    def models(self) -> dict[str, Any]:
        groups: dict[str, list[TaskResult]] = defaultdict(list)
        for task in self._cohort:
            route = _initial_route(task)
            groups[route.selected_model_alias if route else "unrouted"].append(task)
        return {
            "meta": self._meta(),
            "cohorts": [
                self._cohort_record(key, items, model=None if key == "unrouted" else key,
                                    effort=None, policy_version=None)
                for key, items in sorted(groups.items())
            ],
        }

    def task_families(self) -> dict[str, Any]:
        groups: dict[str, list[TaskResult]] = defaultdict(list)
        for task in self._cohort:
            groups[_task_family(task) or "unassigned"].append(task)
        return {
            "meta": self._meta(),
            "cohorts": [
                self._cohort_record(key, items, model=None, effort=None, policy_version=None)
                for key, items in sorted(groups.items())
            ],
        }

    def _metrics(self, tasks: Iterable[TaskResult]) -> dict[str, Any]:
        tasks = tuple(tasks)
        terminal = tuple(task for task in tasks if task.status in TERMINAL)
        successful = tuple(task for task in terminal if task.status == TaskStatus.SUCCEEDED)
        blocked = tuple(task for task in tasks if task.status == TaskStatus.BLOCKED)
        cancelled = tuple(task for task in terminal if task.status == TaskStatus.CANCELLED)
        pending = tuple(task for task in tasks if task.status not in TERMINAL)
        task_cost = _task_totals(terminal)
        latencies = [
            max(0.0, (_utc(task.updated_at) - _utc(task.created_at)).total_seconds() * 1000)
            for task in terminal
        ]
        provider_calls, infrastructure_retries = self._provider_retry_counts(terminal)
        return {
            "total_tasks": len(tasks),
            "terminal_tasks": len(terminal),
            "pending_tasks": len(pending),
            "cancelled_tasks": len(cancelled),
            "blocked_tasks": len(blocked),
            "successful_tasks": len(successful),
            "first_pass_success": _rate(
                sum(1 for task in terminal if _first_pass_success(task)), len(terminal)
            ),
            "final_success": _rate(len(successful), len(terminal)),
            "escalation_rate": _rate(
                sum(1 for task in terminal if _quality_escalated(task)), len(terminal)
            ),
            "infrastructure_retry_rate": _rate(infrastructure_retries, provider_calls),
            "tool_recovery_rate": _rate(
                sum(1 for task in terminal if _tool_recovered(task)), len(terminal)
            ),
            "cost": task_cost,
            "cost_per_task": _divide_cost(task_cost, len(terminal)),
            "effective_cost_per_success": _divide_cost(task_cost, len(successful)),
            "p50_latency_ms": _nearest_rank(latencies, Decimal("0.50")),
            "p95_latency_ms": _nearest_rank(latencies, Decimal("0.95")),
        }

    def _provider_retry_counts(self, tasks: tuple[TaskResult, ...]) -> tuple[int, int]:
        calls = retries = 0
        for task in tasks:
            production = tuple(
                attempt for attempt in task.attempts
                if attempt.role == "production" and _invoked(attempt)
            )
            evaluators = tuple(
                attempt for attempt in task.evaluator_attempts
                if attempt.role == "production" and _invoked(attempt)
            )
            calls += len(production) + len(evaluators)
            purpose_groups: dict[str, list[Any]] = defaultdict(list)
            for attempt in production:
                purpose_groups[attempt.purpose].append(attempt)
            for group in purpose_groups.values():
                group.sort(key=lambda attempt: (attempt.sequence, _utc(attempt.started_at)))
                retries += sum(1 for current, previous in zip(group[1:], group) if _infra_failure(previous))
            evaluator_groups: dict[tuple[str | None, str | None], list[Any]] = defaultdict(list)
            for attempt in evaluators:
                evaluator_groups[(attempt.parent_attempt_id, attempt.evaluator_ref)].append(attempt)
            for group in evaluator_groups.values():
                group.sort(key=lambda attempt: (attempt.sequence, _utc(attempt.started_at)))
                retries += sum(1 for current, previous in zip(group[1:], group) if _infra_failure(previous))
        return calls, retries

    def _cohort_record(
        self,
        key: str,
        tasks: Iterable[TaskResult],
        *,
        model: str | None,
        effort: str | None,
        policy_version: str | None,
    ) -> dict[str, Any]:
        tasks = tuple(tasks)
        terminal_count = sum(task.status in TERMINAL for task in tasks)
        return {
            "key": key,
            "model": model,
            "effort": effort,
            "policy_version": policy_version,
            "metrics": self._metrics(tasks),
            "quality": _quality(tasks),
            "insufficient_sample": terminal_count < 30,
        }

    def _matches_task_attributes(self, task: TaskResult) -> bool:
        values = {
            "application": task.application_id,
            "task_family": _task_family(task),
            "policy_version": task.policy_version,
            "status": str(task.status),
        }
        return all(
            values[name] == self.filters.get(name)
            for name in values
            if self.filters.get(name) is not None
        )

    def _matches_initial_route(self, task: TaskResult) -> bool:
        route = _initial_route(task)
        model = self.filters.get("model")
        effort = self.filters.get("effort")
        return (
            (model is None or route is not None and route.selected_model_alias == model)
            and (effort is None or route is not None and str(route.reasoning_effort) == effort)
        )

    def _matches_invoked_route(self, charge: _Charge) -> bool:
        model = self.filters.get("model")
        effort = self.filters.get("effort")
        return ((model is None or charge.model == model)
                and (effort is None or charge.effort == effort))

    def _task_charges(self, task: TaskResult) -> Iterable[_Charge]:
        retry_attempts, retry_tools = _retry_charge_ids(task)
        for attempt in (*task.attempts, *task.evaluator_attempts):
            if not _invoked(attempt):
                continue
            purpose = attempt.purpose
            model, effort, policy = _invoked_attribution(task, attempt)
            yield _Charge(
                task=task,
                amount=attempt.actual_cost_usd,
                occurred_at=self._attempt_timestamp(attempt),
                role=attempt.role,
                model=model,
                effort=effort,
                purpose=purpose,
                contribution=("retry" if attempt.attempt_id in retry_attempts
                              else "validation" if purpose == "evaluation" else purpose),
                policy_version=policy,
            )
            # Non-evaluator checks attached to generation attempts own their fee.
            for validation in attempt.validations:
                if validation.evaluator_attempt_id is None:
                    yield self._validation_charge(
                        task, validation, attempt.role,
                        contribution="retry" if attempt.attempt_id in retry_attempts else "validation",
                    )
        for validation in task.domain_validations:
            yield self._validation_charge(task, validation, "production", contribution="validation")
        for tool in task.tool_events:
            yield _Charge(
                task=task,
                amount=tool.cost_usd,
                occurred_at=self._correlated_timestamp(task.task_id, "tool", tool.tool_event_id),
                role="production",
                model=None,
                effort=None,
                purpose="tool",
                contribution="retry" if tool.tool_event_id in retry_tools else "tool",
                policy_version=task.policy_version,
            )
        for run in task.shadow_runs:
            for attempt in run.attempts:
                if not _invoked(attempt):
                    continue
                model, effort, policy = _invoked_attribution(task, attempt)
                yield _Charge(
                    task=task,
                    amount=attempt.actual_cost_usd,
                    occurred_at=self._attempt_timestamp(attempt),
                    role="shadow",
                    model=model,
                    effort=effort,
                    purpose=attempt.purpose,
                    contribution="validation" if attempt.purpose == "evaluation" else attempt.purpose,
                    policy_version=policy,
                )
                for validation in attempt.validations:
                    if validation.evaluator_attempt_id is None:
                        yield self._validation_charge(task, validation, "shadow")

    def _validation_charge(
        self,
        task: TaskResult,
        validation: Any,
        role: str,
        *,
        contribution: str = "validation",
    ) -> _Charge:
        return _Charge(
            task=task,
            amount=validation.cost_usd,
            occurred_at=self._correlated_timestamp(task.task_id, "evaluation", validation.evaluation_id),
            role=role,
            model=None,
            effort=None,
            purpose="validation",
            contribution=contribution,
            policy_version=task.policy_version,
        )

    def _attempt_timestamp(self, attempt: Any) -> datetime:
        return _utc(attempt.completed_at or attempt.started_at)

    def _correlated_timestamp(self, task_id: str, kind: str, identity: str) -> datetime | None:
        return self._event_index.get((task_id, kind, identity))

    @staticmethod
    def _index_events(events: tuple[ExecutionEvent, ...]) -> dict[tuple[str, str, str], datetime]:
        result: dict[tuple[str, str, str], datetime] = {}
        for event in sorted(events, key=lambda event: (_utc(event.occurred_at), event.event_id)):
            stamp = _utc(event.occurred_at)
            if event.attempt_id and event.kind in {"ATTEMPT_STARTED", "ATTEMPT_COMPLETED"}:
                key = (event.task_id, "attempt", event.attempt_id)
                if event.kind == "ATTEMPT_COMPLETED" or key not in result:
                    result[key] = stamp
            if event.tool_event_id and event.kind in {"TOOL_STARTED", "TOOL_COMPLETED"}:
                key = (event.task_id, "tool", event.tool_event_id)
                if event.kind == "TOOL_COMPLETED" or key not in result:
                    result[key] = stamp
            if event.evaluation_id and event.kind == "VALIDATION_COMPLETED":
                result[(event.task_id, "evaluation", event.evaluation_id)] = stamp
        return result

    def _spend_cost(self, start: datetime, end: datetime, *, role: str) -> dict[str, Any]:
        return _charge_cost(tuple(
            charge for charge in self._charges
            if charge.role == role and charge.occurred_at is not None
            and start <= charge.occurred_at < end
        ))

    def _project(self, mtd: dict[str, Any], month_start: datetime) -> dict[str, Any]:
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        elapsed = Decimal(str((self.now - month_start).total_seconds()))
        duration = Decimal(str((next_month - month_start).total_seconds()))
        if elapsed <= ZERO or mtd["status"] == "unavailable":
            return _cost(None, ZERO, mtd["missing_count"], "unavailable")
        factor = _decimal_divide(duration, elapsed)
        known = _decimal_multiply(Decimal(mtd["known_subtotal"]), factor)
        amount = (_decimal_multiply(Decimal(mtd["amount"]), factor)
                  if mtd["amount"] is not None else None)
        return _cost(amount, known, mtd["missing_count"], mtd["status"])

    @staticmethod
    def _spend_groups(charges: tuple[_Charge, ...], key: Any) -> list[dict[str, Any]]:
        groups: dict[str, list[_Charge]] = defaultdict(list)
        for charge in charges:
            groups[str(key(charge))].append(charge)
        records = [
            {"key": name, "cost": _charge_cost(items), "count": len(items)}
            for name, items in groups.items()
        ]
        return sorted(records, key=lambda record: (
            Decimal(record["cost"]["known_subtotal"]).copy_negate(), record["key"]
        ))

    def _meta(self, *, notes: tuple[str, ...] = ()) -> dict[str, Any]:
        freshness = max((_utc(event.occurred_at) for event in self._events), default=None)
        all_filters = {
            "application": None,
            "model": None,
            "effort": None,
            "task_family": None,
            "policy_version": None,
            "status": None,
        }
        all_filters.update(self.filters)
        return {
            "metric_definition_version": METRIC_DEFINITION_VERSION,
            "start": _iso(self.start),
            "end": _iso(self.end),
            "generated_at": _iso(self.now),
            "freshness": _iso(freshness) if freshness is not None else None,
            "synthetic": self.synthetic,
            "currency": "USD",
            "filters": all_filters,
            "notes": list(notes),
        }


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"analytics {name} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("retained telemetry timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _filter_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        raise ValueError("analytics filter values must be non-empty")
    return text


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _money(value: Decimal) -> str:
    if value == ZERO:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _cost(
    amount: Decimal | None,
    known_subtotal: Decimal,
    missing_count: int,
    status: str,
) -> dict[str, Any]:
    return {
        "amount": _money(amount) if amount is not None else None,
        "known_subtotal": _money(known_subtotal),
        "missing_count": missing_count,
        "status": status,
    }


def _charge_cost(charges: Iterable[_Charge]) -> dict[str, Any]:
    charges = tuple(charges)
    if not charges:
        return _cost(None, ZERO, 0, "unavailable")
    known = money_sum(charge.amount for charge in charges if charge.amount is not None)
    missing = sum(charge.amount is None for charge in charges)
    if missing:
        return _cost(None, known, missing, "partial")
    return _cost(known, known, 0, "known")


def _task_totals(tasks: Iterable[TaskResult]) -> dict[str, Any]:
    tasks = tuple(tasks)
    if not tasks:
        return _cost(None, ZERO, 0, "unavailable")
    known = money_sum(task.known_cost_usd for task in tasks)
    missing = sum(task.total_cost_usd is None for task in tasks)
    if missing:
        return _cost(None, known, missing, "partial")
    total = money_sum(task.total_cost_usd for task in tasks if task.total_cost_usd is not None)
    return _cost(total, total, 0, "known")


def _divide_cost(cost: dict[str, Any], denominator: int) -> dict[str, Any]:
    if denominator == 0:
        return _cost(None, ZERO, cost["missing_count"], "unavailable")
    known = _decimal_divide(Decimal(cost["known_subtotal"]), Decimal(denominator))
    amount = (_decimal_divide(Decimal(cost["amount"]), Decimal(denominator))
              if cost["amount"] is not None else None)
    return _cost(amount, known, cost["missing_count"], cost["status"])


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def _task_rate(items: Iterable[Any], predicate: Any) -> dict[str, Any]:
    items = tuple(items)
    return _rate(sum(1 for item in items if predicate(item)), len(items))


def _nearest_rank(values: Iterable[float], percentile: Decimal) -> float | None:
    values = sorted(values)
    if not values:
        return None
    numerator, denominator = percentile.as_integer_ratio()
    rank = (numerator * len(values) + denominator - 1) // denominator
    return values[max(0, rank - 1)]


def _distribution(values: Iterable[str]) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[str(value)] += 1
    total = sum(counts.values())
    return [
        {"key": key, "count": count, "share": count / total if total else None}
        for key, count in sorted(counts.items())
    ]


def _flows(values: Iterable[tuple[str, str]]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return [
        {"source": source, "target": target, "count": count}
        for (source, target), count in sorted(counts.items())
    ]


def _utc_days(start: datetime, end: datetime) -> Iterable[datetime]:
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        yield day
        day += timedelta(days=1)


def _task_family(task: TaskResult) -> str | None:
    return task.classification.task_family if task.classification is not None else None


def _route_key(route: RouteDecision) -> str:
    return f"{route.selected_model_alias}/{route.reasoning_effort}"


def _invoked(attempt: Any) -> bool:
    # Cancelled pre-dispatch reservations are not spend. A started record is an
    # invocation intent with potentially unknown charge and therefore is spend evidence.
    if getattr(attempt.provider_outcome, 'stage', None) == 'preflight':
        return False
    return not (str(attempt.status) == "cancelled" and attempt.provider_outcome is None)


def _infra_failure(attempt: Any) -> bool:
    failure = attempt.failure
    failure_type = (
        failure.failure_type if failure is not None
        else getattr(attempt.provider_outcome, "failure_type", None)
    )
    return failure_type in INFRASTRUCTURE_FAILURES


def _first_pass_success(task: TaskResult) -> bool:
    generations = tuple(
        attempt for attempt in task.attempts
        if attempt.purpose == "generation" and attempt.role == "production" and _invoked(attempt)
    )
    retry_attempts, retry_tools = _retry_charge_ids(task)
    return (
        task.status == TaskStatus.SUCCEEDED
        and len(generations) == 1
        and not retry_attempts
        and not retry_tools
        and task.counters.quality_escalations == 0
        and task.counters.infrastructure_retries == 0
        and task.counters.tool_recoveries == 0
        and not any(action.action in {
            "increase_effort", "increase_tier", "retry_backoff", "health_aware_fallback",
            "retry_tool", "alternate_tool", "retry_evaluator", "diagnose",
        } for action in task.recovery_actions)
        and generations[0].status == "succeeded"
    )


def _quality_escalated(task: TaskResult) -> bool:
    return task.counters.quality_escalations > 0 or any(
        action.action in {"increase_effort", "increase_tier"}
        for action in task.recovery_actions
    )


def _tool_recovered(task: TaskResult) -> bool:
    return task.counters.tool_recoveries > 0 or any(
        action.action in {"retry_tool", "alternate_tool"}
        for action in task.recovery_actions
    )


def _quality(tasks: Iterable[TaskResult]) -> dict[str, Any]:
    # Select the final applicable observation first. A later evaluator error
    # invalidates an earlier score for that target instead of resurrecting it.
    final: dict[tuple[str, str, str, str, str], Any] = {}
    for task in tasks:
        for attempt in (*task.attempts, *task.evaluator_attempts):
            for validation in attempt.validations:
                if validation.applicable and validation.rubric_version is not None:
                    target = validation.target_attempt_id or attempt.parent_attempt_id or attempt.attempt_id
                    final[(task.task_id, target, validation.rubric_version,
                           validation.check, attempt.role)] = validation
    grouped: dict[tuple[str, str, float, float, str], list[float]] = defaultdict(list)
    for (_, _, rubric, check, role), value in final.items():
        if (
            value.status not in {"passed", "failed"}
            or value.score is None
            or value.score_min is None
            or value.score_max is None
            or not all(isfinite(number) for number in (
                value.score, value.score_min, value.score_max
            ))
        ):
            continue
        grouped[(rubric, check, value.score_min, value.score_max, role)].append(value.score)
    groups = [
        {
            "rubric_version": rubric,
            "check": check,
            "score_min": score_min,
            "score_max": score_max,
            "mean": sum(scores) / len(scores),
            "sample_size": len(scores),
            "role": role,
        }
        for (rubric, check, score_min, score_max, role), scores in sorted(grouped.items())
    ]
    if not groups:
        return {"comparable": False, "reason": "no_comparable_evaluator_scores", "groups": []}
    if len(groups) > 1:
        return {"comparable": False, "reason": "mixed_rubric_check_scale_or_role", "groups": groups}
    return {"comparable": True, "reason": None, "groups": groups}


def _none_sort(value: tuple[str | None, str | None]) -> tuple[str, str]:
    return value[0] or "", value[1] or ""


def _retry_charge_ids(task: TaskResult) -> tuple[set[str], set[str]]:
    attempts: set[str] = set()
    generations = [
        attempt for attempt in task.attempts
        if attempt.purpose == "generation" and attempt.role == "production" and _invoked(attempt)
    ]
    attempts.update(attempt.attempt_id for attempt in generations[1:])
    classifier_groups: dict[str, list[Any]] = defaultdict(list)
    for attempt in task.attempts:
        if attempt.purpose == "classification" and attempt.role == "production" and _invoked(attempt):
            classifier_groups[attempt.role].append(attempt)
    for group in classifier_groups.values():
        group.sort(key=lambda attempt: (attempt.sequence, _utc(attempt.started_at)))
        attempts.update(
            current.attempt_id
            for current, previous in zip(group[1:], group)
            if _infra_failure(previous)
        )
    evaluator_groups: dict[tuple[str | None, str | None], list[Any]] = defaultdict(list)
    for attempt in task.evaluator_attempts:
        if attempt.role == "production" and _invoked(attempt):
            evaluator_groups[(attempt.parent_attempt_id, attempt.evaluator_ref)].append(attempt)
    for group in evaluator_groups.values():
        group.sort(key=lambda attempt: (attempt.sequence, _utc(attempt.started_at)))
        attempts.update(attempt.attempt_id for attempt in group[1:])
    tools: set[str] = set()
    tool_groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for outcome in task.tool_events:
        tool_groups[(outcome.tool, outcome.operation)].append(outcome)
    for group in tool_groups.values():
        tools.update(outcome.tool_event_id for outcome in group[1:])
    return attempts, tools


def _invoked_attribution(task: TaskResult, attempt: Any) -> tuple[str | None, str | None, str]:
    outcome = attempt.provider_outcome
    if outcome is not None:
        return outcome.model_alias, str(outcome.reasoning_effort), outcome.policy_version
    if attempt.purpose == "evaluation" and attempt.evaluator_ref and task.phase4_config:
        for binding in task.phase4_config.get("evaluators", ()):
            if binding.get("ref") == attempt.evaluator_ref:
                return (
                    binding.get("model_alias"),
                    str(binding["reasoning_effort"]) if binding.get("reasoning_effort") else None,
                    task.policy_version,
                )
    route = attempt.decision if isinstance(attempt.decision, RouteDecision) else None
    return (
        route.selected_model_alias if route else None,
        str(route.reasoning_effort) if route else None,
        route.policy_version if route else task.policy_version,
    )


def _arithmetic_context(*values: Decimal) -> Context:
    digits = max((len(value.as_tuple().digits) for value in values), default=1)
    exponent_span = max((abs(value.as_tuple().exponent) for value in values), default=0)
    return Context(prec=max(80, digits * 2 + exponent_span + 32), Emax=MAX_EMAX, Emin=MIN_EMIN)


def _decimal_divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext(_arithmetic_context(numerator, denominator)):
        return numerator / denominator


def _decimal_multiply(left: Decimal, right: Decimal) -> Decimal:
    with localcontext(_arithmetic_context(left, right)):
        return left * right
