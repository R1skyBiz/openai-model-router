"""Read-only telemetry queries and safe task/timeline projections."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from math import ceil
from typing import Any

from model_router.core.contracts import FailureType, RouteDecision
from model_router.core.execution_contracts import (
    Attempt,
    ExecutionEvent,
    TaskResult,
    ValidationOutcome,
)
from model_router.storage.telemetry import TelemetrySnapshot, read_telemetry_snapshot
from model_router.telemetry.analytics import Analytics
from model_router.telemetry.evidence import initial_route, task_is_synthetic


_FILTERS = {
    "start", "end", "application", "model", "effort", "task_family",
    "policy_version", "status",
}
_TOKEN_FIELDS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_tokens", "total_tokens",
)
_TITLES = {
    "TASK_CREATED": "Created",
    "TASK_CLASSIFIED": "Classified",
    "ROUTE_SELECTED": "Route selected",
    "ATTEMPT_STARTED": "Attempt started",
    "ATTEMPT_COMPLETED": "Attempt completed",
    "VALIDATION_COMPLETED": "Validation completed",
    "RECOVERY_SELECTED": "Recovery selected",
    "TOOL_STARTED": "Tool started",
    "TOOL_COMPLETED": "Tool completed",
    "TASK_SUCCEEDED": "Succeeded",
    "TASK_FAILED": "Failed",
    "TASK_BLOCKED": "Blocked",
    "TASK_CANCELLED": "Cancelled",
}


class TelemetryQuery:
    """Compose pure analytics over one scoped SQLite evidence snapshot per read."""

    def __init__(
        self,
        repository: object,
        *,
        now: Callable[[], datetime] | datetime,
        application_scope: str | None | Callable[[], str | None],
        synthetic: bool = False,
    ) -> None:
        if application_scope is not None and not callable(application_scope) and not str(application_scope):
            raise ValueError("application_scope must be non-empty")
        self.repository = repository
        self._now_source = now
        self._application_scope_source = application_scope
        self.synthetic = synthetic is True

    def summary(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._analytics(filters).summary()

    def spend(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._analytics(filters).spend()

    def routing(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._analytics(filters).routing()

    def efficacy(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._analytics(filters).efficacy()

    def policies(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._analytics(filters).policies()

    def models(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._analytics(filters).models()

    def task_families(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._analytics(filters).task_families()

    def tasks(
        self,
        filters: Mapping[str, Any] | None = None,
        *,
        offset: int = 0,
        limit: int = 25,
    ) -> dict[str, Any]:
        offset, limit = _pagination(offset, limit, maximum=100)
        analytics, _snapshot = self._context(filters)
        selected = sorted(
            analytics._cohort,  # Selection semantics are owned by Analytics.
            key=lambda task: (_utc(task.created_at), task.task_id),
            reverse=True,
        )
        return {
            "meta": analytics.summary()["meta"],
            "items": [_task_item(task) for task in selected[offset: offset + limit]],
            "total": len(selected),
            "offset": offset,
            "limit": limit,
        }

    def task_detail(
        self,
        task_id: str,
        filters: Mapping[str, Any] | None = None,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> dict[str, Any] | None:
        offset, limit = _pagination(offset, limit, maximum=500)
        if not task_id:
            return None
        analytics, snapshot = self._context(filters)
        task = next((item for item in analytics._cohort if item.task_id == task_id), None)
        if task is None:
            return None
        events = tuple(event for event in snapshot.events if event.task_id == task.task_id)
        timeline = _timeline(task, events)
        return {
            "meta": analytics.summary()["meta"],
            "task": _task_item(task),
            "timeline": timeline[offset: offset + limit],
            "total": len(timeline),
            "offset": offset,
            "limit": limit,
        }

    def health(self, filters: Mapping[str, Any] | None = None) -> dict[str, Any]:
        analytics, snapshot = self._context(filters)
        now = analytics.now
        selected = tuple(analytics._cohort)
        task_ids = {task.task_id for task in selected}

        observations: dict[tuple[str, str | None, str | None], Any] = {}
        for task in selected:
            for health_snapshot in task.health_snapshots:
                for observation in health_snapshot.observations:
                    key = (observation.component, observation.model, observation.capability)
                    current = observations.get(key)
                    if current is None or _utc(observation.observed_at) > _utc(current.observed_at):
                        observations[key] = observation

        components = []
        periods = []
        seen_periods: set[tuple[Any, ...]] = set()
        for task in selected:
            for health_snapshot in task.health_snapshots:
                for observation in health_snapshot.observations:
                    if _utc(observation.observed_at) > now:
                        # Future evidence cannot establish a historical
                        # degraded interval. It remains UNKNOWN in components.
                        continue
                    observed_state = _observed_health_state(observation)
                    if observed_state != "HEALTHY":
                        identity = (
                            health_snapshot.snapshot_id,
                            observation.component,
                            observation.model,
                            observation.capability,
                            _utc(observation.observed_at),
                            _utc(observation.valid_until),
                            observed_state,
                        )
                        if identity in seen_periods:
                            continue
                        seen_periods.add(identity)
                        periods.append({
                            "start": _iso(observation.observed_at),
                            "end": _iso(observation.valid_until),
                            "component": observation.component,
                            "state": observed_state,
                        })
        periods.sort(key=lambda item: (item["start"], item["component"], item["state"]))
        for key in sorted(observations, key=lambda item: tuple(value or "" for value in item)):
            observation = observations[key]
            state = _health_state(observation, now)
            components.append({
                "component": observation.component,
                "model": observation.model,
                "capability": observation.capability,
                "state": state,
                "observed_at": _iso(observation.observed_at),
                "valid_until": _iso(observation.valid_until),
                "circuit_state": observation.circuit_state,
                "failure_count": observation.failure_count,
                "latency_ms": observation.latency_ms,
                "required": observation.required,
            })

        attempts = tuple(
            attempt
            for task in selected
            for attempt in (*task.attempts, *task.evaluator_attempts)
            if attempt.role == "production" and _attempt_invoked(attempt)
        )
        failures = tuple(attempt for attempt in attempts if _attempt_failed(attempt))
        latencies = sorted(
            latency for attempt in attempts
            if (latency := _attempt_latency(attempt)) is not None
        )
        pending_events = tuple(
            event for event in snapshot.events
            if event.task_id in task_ids and event.event_id in snapshot.pending_event_ids
        )
        states = [component["state"] for component in components]
        meta = analytics.summary()["meta"]
        meta["notes"].append(
            "Degraded periods are retained observation intervals, not proof of continuous outage."
        )
        return {
            "meta": meta,
            "state": _overall_health(states),
            "production_ready": False,
            "readiness_note": (
                "Read-only retained evidence cannot establish current production readiness."
            ),
            "components": components,
            "outbox_pending": len(pending_events),
            "oldest_pending_at": (
                _iso(min(event.occurred_at for event in pending_events))
                if pending_events else None
            ),
            "p50_latency_ms": _nearest_rank(latencies, 0.50),
            "p95_latency_ms": _nearest_rank(latencies, 0.95),
            "failure_rate": _rate(len(failures), len(attempts)),
            "timeouts": sum(_failure_type(attempt) == FailureType.TIMEOUT for attempt in failures),
            "rate_limits": sum(_failure_type(attempt) == FailureType.RATE_LIMIT for attempt in failures),
            "degraded_periods": periods,
        }

    def _analytics(self, filters: Mapping[str, Any] | None) -> Analytics:
        analytics, _snapshot = self._context(filters)
        return analytics

    def _context(
        self, filters: Mapping[str, Any] | None
    ) -> tuple[Analytics, TelemetrySnapshot]:
        now = self._now()
        normalized = _normalize_filters(filters)
        application_scope = self._application_scope()
        if application_scope is not None:
            normalized["application"] = application_scope
        snapshot = read_telemetry_snapshot(self.repository)
        if application_scope is None and not self.synthetic:
            # New production telemetry fails closed without a trusted
            # application identity. The legacy task metadata endpoint retains
            # its prior behavior outside this query boundary.
            scoped_tasks = ()
        else:
            scoped_tasks = tuple(
                task for task in snapshot.tasks
                if (
                    self.synthetic and application_scope is None
                    or task.application_id == application_scope
                )
            )
        task_ids = {task.task_id for task in scoped_tasks}
        scoped_events = tuple(event for event in snapshot.events if event.task_id in task_ids)
        return (
            Analytics(
                scoped_tasks,
                scoped_events,
                now=now,
                filters=normalized,
                synthetic=self.synthetic,
            ),
            snapshot,
        )

    def _now(self) -> datetime:
        value = self._now_source() if callable(self._now_source) else self._now_source
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError("telemetry clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    def _application_scope(self) -> str | None:
        source = self._application_scope_source
        value = source() if callable(source) else source
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError("application scope must be a non-empty string")
        return value


def _normalize_filters(filters: Mapping[str, Any] | None) -> dict[str, Any]:
    values = dict(filters or {})
    if set(values) - _FILTERS:
        raise ValueError("unsupported telemetry filter")
    normalized: dict[str, Any] = {}
    for name, value in values.items():
        if value is None:
            continue
        if name in {"start", "end"}:
            normalized[name] = _parse_datetime(value)
        else:
            if not isinstance(value, str) or not value:
                raise ValueError("telemetry filter values must be non-empty strings")
            normalized[name] = value
    if "start" in normalized and "end" in normalized and normalized["start"] >= normalized["end"]:
        raise ValueError("telemetry start must be before end")
    return normalized


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("invalid telemetry timestamp") from None
    else:
        raise ValueError("invalid telemetry timestamp")
    if parsed.utcoffset() is None:
        raise ValueError("telemetry timestamps must include an offset")
    return parsed.astimezone(UTC)


def _pagination(offset: int, limit: int, *, maximum: int) -> tuple[int, int]:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("invalid telemetry offset")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise ValueError("invalid telemetry limit")
    return offset, limit


def _task_item(task: TaskResult) -> dict[str, Any]:
    route = initial_route(task)
    return {
        "task_id": task.task_id,
        "created_at": _iso(task.created_at),
        "application": task.application_id,
        "task_family": task.classification.task_family if task.classification else None,
        "complexity": (
            route.complexity_score if route is not None
            else task.classification.components.total if task.classification else None
        ),
        "model": route.selected_model_alias if route is not None else None,
        "effort": str(route.reasoning_effort) if route is not None else None,
        "status": str(task.status),
        "cost": _cost(task.total_cost_usd, task.known_cost_usd),
        "latency_ms": max(
            0.0, (_utc(task.updated_at) - _utc(task.created_at)).total_seconds() * 1000
        ),
        "escalated": any(
            action.action in {"increase_effort", "increase_tier"}
            for action in task.recovery_actions
        ),
        "policy_version": task.policy_version,
        "synthetic": task_is_synthetic(task),
    }


def _timeline(task: TaskResult, events: tuple[ExecutionEvent, ...]) -> list[dict[str, Any]]:
    decisions = {
        decision.decision_id: decision
        for decision in task.decisions
        if isinstance(decision, RouteDecision)
    }
    if isinstance(task.initial_decision, RouteDecision):
        decisions.setdefault(task.initial_decision.decision_id, task.initial_decision)
    attempts = {
        attempt.attempt_id: attempt
        for attempt in (*task.attempts, *task.evaluator_attempts)
    }
    for run in task.shadow_runs:
        attempts.update({attempt.attempt_id: attempt for attempt in run.attempts})
    tools = {tool.tool_event_id: tool for tool in task.tool_events}
    validations: dict[str, ValidationOutcome] = {}
    for attempt in attempts.values():
        validations.update({item.evaluation_id: item for item in attempt.validations})
    validations.update({item.evaluation_id: item for item in task.domain_validations})
    health_snapshots = {
        snapshot.snapshot_id: snapshot for snapshot in task.health_snapshots
    }
    recoveries: dict[str, list[Any]] = defaultdict(list)
    for recovery in task.recovery_actions:
        recoveries[recovery.action].append(recovery)

    steps = []
    # Storage supplies SQLite append order for equal timestamps. Python's
    # stable sort preserves that factual tie-break without inventing a global
    # kind precedence or relying on random event identifiers.
    for event in sorted(events, key=lambda item: _utc(item.occurred_at)):
        event_attempt = attempts.get(event.attempt_id) if event.attempt_id else None
        attempt = event_attempt
        decision = decisions.get(event.decision_id) if event.decision_id else None
        if decision is None and attempt is not None and isinstance(attempt.decision, RouteDecision):
            decision = attempt.decision
        tool = tools.get(event.tool_event_id) if event.tool_event_id else None
        validation = validations.get(event.evaluation_id) if event.evaluation_id else None
        if (
            validation is not None
            and validation.evaluator_attempt_id is not None
            and validation.evaluator_attempt_id in attempts
        ):
            attempt = attempts[validation.evaluator_attempt_id]
            decision = (
                attempt.decision if isinstance(attempt.decision, RouteDecision) else None
            )
        recovery = None
        if event.action and recoveries[event.action]:
            recovery = recoveries[event.action].pop(0)
        outcome = attempt.provider_outcome if attempt is not None else None
        usage = (
            outcome.usage
            if event.kind == "ATTEMPT_COMPLETED" and outcome is not None
            else None
        )
        metadata: dict[str, str | int | float | bool | None] = {}
        for name in ("attempt_id", "decision_id", "tool_event_id", "evaluation_id"):
            value = getattr(event, name)
            if value is not None:
                metadata[name] = value
        if event.kind == "TASK_CLASSIFIED" and task.classification is not None:
            metadata.update({
                "task_family": task.classification.task_family,
                "complexity": task.classification.components.total,
            })
        if decision is not None:
            metadata.update({
                "validation_level": str(decision.validation_level),
                "routing_result": decision.routing_result,
                "executable": decision.executable,
            })
            if decision.health_snapshot_id is not None:
                health_snapshot = health_snapshots.get(decision.health_snapshot_id)
                if health_snapshot is None:
                    metadata["health_evidence"] = "missing"
                else:
                    metadata.update({
                        "health_evidence": "retained",
                        "health_observed_at": _iso(health_snapshot.observed_at),
                        "health_valid_until": _iso(health_snapshot.valid_until),
                        "health_component_count": len(health_snapshot.observations),
                        "health_component_states": ",".join(sorted({
                            observation.state
                            for observation in health_snapshot.observations
                        })),
                        "health_circuit_states": ",".join(sorted({
                            observation.circuit_state
                            for observation in health_snapshot.observations
                        })),
                    })
        if attempt is not None:
            metadata["purpose"] = attempt.purpose
            if event.kind == "ATTEMPT_COMPLETED":
                metadata["attempt_status"] = str(attempt.status)
        if tool is not None:
            metadata.update({
                "tool": tool.tool,
                "operation": tool.operation,
                "side_effecting": tool.side_effecting,
                "replay_safe": tool.replay_safe,
            })
            if event.kind == "TOOL_COMPLETED":
                metadata["tool_status"] = tool.status
        if validation is not None:
            metadata.update({
                "check": validation.check,
                "applicable": validation.applicable,
                "validation_status": validation.status,
                "rubric_version": validation.rubric_version,
                "score": validation.score,
                "score_min": validation.score_min,
                "score_max": validation.score_max,
            })
        model = (
            outcome.model_alias if outcome is not None
            else decision.selected_model_alias if decision is not None else None
        )
        effort = (
            str(outcome.reasoning_effort) if outcome is not None
            else str(decision.reasoning_effort) if decision is not None else None
        )
        steps.append({
            "id": event.event_id,
            "kind": event.kind,
            "timestamp": _iso(event.occurred_at),
            "title": _timeline_title(event, attempt, model, effort),
            "model": model,
            "effort": effort,
            "rationale_codes": list(
                recovery.rationale_codes if recovery is not None
                else decision.rationale_codes if decision is not None else ()
            ),
            "tokens": {
                name: getattr(usage, name) if usage is not None else None
                for name in _TOKEN_FIELDS
            },
            "cost": _step_cost(event.kind, event_attempt, tool, validation),
            "latency_ms": _step_latency(event.kind, event_attempt, tool),
            "validation": validation.status if validation is not None else None,
            "failure_type": (
                str(event.failure_type) if event.failure_type is not None
                else str(event_attempt.failure.failure_type)
                if event.kind == "ATTEMPT_COMPLETED"
                and event_attempt is not None
                and event_attempt.failure is not None
                else str(tool.failure.failure_type)
                if event.kind == "TOOL_COMPLETED"
                and tool is not None
                and tool.failure is not None
                else str(validation.failure.failure_type)
                if event.kind == "VALIDATION_COMPLETED"
                and validation is not None
                and validation.failure is not None
                else None
            ),
            "recovery_action": event.action,
            "health_snapshot_id": decision.health_snapshot_id if decision is not None else None,
            "policy_version": event.policy_version,
            "pricing_version": (
                attempt.pricing_version if attempt is not None
                else decision.pricing_version if decision is not None else None
            ),
            "role": attempt.role if attempt is not None else "production",
            "metadata": metadata,
        })
    return steps


def _timeline_title(
    event: ExecutionEvent,
    attempt: Attempt | None,
    model: str | None,
    effort: str | None,
) -> str:
    if event.kind in {"ATTEMPT_STARTED", "ATTEMPT_COMPLETED"} and attempt is not None:
        phase = "Started" if event.kind == "ATTEMPT_STARTED" else "Completed"
        label = {
            "generation": "Attempt",
            "evaluation": "Evaluation",
            "classification": "Classification",
        }[attempt.purpose]
        return (
            f"{label} {attempt.sequence} — {model or 'unknown'} / "
            f"{effort or 'unknown'} · {phase}"
        )
    return _TITLES.get(event.kind, event.kind.replace("_", " ").title())


def _step_cost(
    kind: str,
    attempt: Attempt | None,
    tool: Any,
    validation: ValidationOutcome | None,
):
    if kind == "TOOL_COMPLETED" and tool is not None:
        return _cost(tool.cost_usd, tool.cost_usd or Decimal("0"))
    if (
        kind == "VALIDATION_COMPLETED"
        and validation is not None
        and validation.evaluator_attempt_id is None
    ):
        return _cost(validation.cost_usd, validation.cost_usd or Decimal("0"))
    if kind == "ATTEMPT_COMPLETED" and attempt is not None:
        return _cost(attempt.actual_cost_usd, attempt.actual_cost_usd or Decimal("0"))
    return None


def _step_latency(kind: str, attempt: Attempt | None, tool: Any) -> float | None:
    if kind == "TOOL_COMPLETED" and tool is not None:
        return tool.latency_ms
    if kind == "ATTEMPT_COMPLETED":
        return _attempt_latency(attempt)
    return None


def _cost(amount: Decimal | None, known: Decimal) -> dict[str, Any]:
    if amount is None:
        return {
            "amount": None,
            "known_subtotal": _money(known),
            "missing_count": 1,
            # This helper always projects an existing task/charge.  A missing
            # amount is incomplete evidence even when its known subtotal is 0;
            # "unavailable" is reserved for an empty aggregate cohort.
            "status": "partial",
        }
    return {
        "amount": _money(amount),
        "known_subtotal": _money(amount),
        "missing_count": 0,
        "status": "known",
    }


def _money(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _health_state(observation: Any, now: datetime) -> str:
    if _utc(observation.observed_at) > now:
        return "UNKNOWN"
    if observation.check_status in {"missing", "disabled"}:
        return "UNKNOWN"
    if observation.check_status == "stale" or _utc(observation.valid_until) <= now:
        return "STALE"
    return observation.state


def _observed_health_state(observation: Any) -> str:
    if observation.check_status in {"missing", "disabled"}:
        return "UNKNOWN"
    if observation.check_status == "stale":
        return "STALE"
    return observation.state


def _overall_health(states: list[str]) -> str:
    if not states:
        return "UNKNOWN"
    for state in ("UNHEALTHY", "STALE", "DEGRADED", "UNKNOWN"):
        if state in states:
            return state
    return "HEALTHY"


def _attempt_invoked(attempt: Attempt) -> bool:
    return not (str(attempt.status) == "cancelled" and attempt.provider_outcome is None)


def _attempt_failed(attempt: Attempt) -> bool:
    return (
        str(attempt.status) in {"failed", "unknown"}
        or attempt.failure is not None
        or getattr(attempt.provider_outcome, "outcome", None) == "failure"
    )


def _failure_type(attempt: Attempt) -> FailureType | None:
    if attempt.failure is not None:
        return attempt.failure.failure_type
    outcome = attempt.provider_outcome
    return getattr(outcome, "failure_type", None)


def _attempt_latency(attempt: Attempt | None) -> float | None:
    if attempt is None:
        return None
    if attempt.provider_outcome is not None:
        return attempt.provider_outcome.latency_ms
    if attempt.completed_at is None:
        return None
    return max(0.0, (_utc(attempt.completed_at) - _utc(attempt.started_at)).total_seconds() * 1000)


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    return values[max(0, ceil(percentile * len(values)) - 1)]


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("retained telemetry timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


__all__ = ["TelemetryQuery"]
