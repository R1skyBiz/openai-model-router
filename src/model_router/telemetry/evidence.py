"""Shared interpretation of retained routing provenance."""

from __future__ import annotations

from model_router.core.contracts import RouteDecision
from model_router.core.execution_contracts import TaskResult


def initial_route(task: TaskResult) -> RouteDecision | None:
    """Return the earliest retained production generation route."""

    if isinstance(task.initial_decision, RouteDecision):
        return task.initial_decision
    for attempt in task.attempts:
        if (
            attempt.purpose == "generation"
            and attempt.role == "production"
            and isinstance(attempt.decision, RouteDecision)
        ):
            return attempt.decision
    return next(
        (decision for decision in task.decisions if isinstance(decision, RouteDecision)),
        None,
    )


def task_is_synthetic(task: TaskResult) -> bool:
    """Treat any retained production routing evidence as authoritative provenance.

    The conservative ``any`` rule prevents malformed or legacy mixed evidence
    from entering production analytics. Shadow decisions are intentionally not
    inspected because their role is separately attributable.
    """

    evidence = [task.initial_decision, *task.decisions]
    evidence.extend(
        attempt.decision
        for attempt in task.attempts
        if attempt.purpose == "generation" and attempt.role == "production"
    )
    return any(
        decision is not None and decision.synthetic is True
        for decision in evidence
    )


__all__ = ["initial_route", "task_is_synthetic"]
