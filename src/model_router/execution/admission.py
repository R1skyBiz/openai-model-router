"""Fail-closed execution admission and an in-memory budget authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import RLock
from typing import Literal

from model_router.core.contracts import FailureType, Money, Request
from model_router.execution.arithmetic import money_sum, money_difference
from model_router.core.execution_contracts import (
    Counters,
    ExecutionControls,
    ExecutionLimits,
    Failure,
    ToolCall,
)


AdmissionAction = Literal[
    "classification",
    "generation",
    "quality_escalation",
    "infrastructure_retry",
    "validation",
    "tool",
    "tool_recovery",
    "increase_effort",
    "increase_tier",
    "retry_backoff",
    "health_aware_fallback",
    "retry_tool",
    "alternate_tool",
]


def _failure(failure_type: FailureType, cause_code: str) -> Failure:
    return Failure(
        failure_type=failure_type,
        source="admission",
        stage="admission",
        cause_code=cause_code,
        retryable=False,
    )


def _amount(value: object) -> Decimal | None:
    """Normalize trusted decimal inputs without allowing floats or non-finite values."""

    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        return None
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount


def check_admission(
    request: Request,
    controls: ExecutionControls,
    limits: ExecutionLimits | None,
    counters: Counters,
    elapsed_ms: int,
    remaining_usd: Money | None,
    cost_usd: Money | None,
    *,
    action: AdmissionAction = "generation",
    replay: bool = False,
    tool_call: ToolCall | None = None,
) -> Failure | None:
    """Return a typed blocker, or ``None`` when one bounded action is admissible.

    All inputs describe the next action. This function does not reserve funds;
    callers reserve the admitted amount immediately before dispatch.
    """

    del request  # Caller-supplied approval and replay booleans are not authority.

    if limits is None:
        return _failure(FailureType.CAPABILITY_FAILURE, "execution_limits_required")
    if controls is None or controls.authorized is not True:
        return _failure(FailureType.CAPABILITY_FAILURE, "execution_not_authorized")
    if isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, int) or elapsed_ms < 0:
        return _failure(FailureType.TIMEOUT, "elapsed_time_invalid")
    if elapsed_ms >= limits.max_elapsed_ms:
        return _failure(FailureType.TIMEOUT, "deadline_exhausted")

    attempt_blocker = _attempt_blocker(action, counters, limits)
    if attempt_blocker is not None:
        return attempt_blocker

    remaining = _amount(remaining_usd)
    cost = _amount(cost_usd)
    if remaining is None:
        return _failure(FailureType.BUDGET_FAILURE, "remaining_budget_required")
    if cost is None:
        return _failure(FailureType.BUDGET_FAILURE, "action_cost_required")
    if cost > limits.task_cost_ceiling_usd:
        return _failure(FailureType.BUDGET_FAILURE, "task_cost_ceiling_exceeded")
    if cost > remaining:
        return _failure(FailureType.BUDGET_FAILURE, "remaining_budget_exceeded")

    if (
        action in {"tool", "tool_recovery", "retry_tool", "alternate_tool"}
        or tool_call is not None
    ):
        blocker = _check_tool(controls, tool_call, replay=replay)
        if blocker is not None:
            return blocker
    elif replay:
        # A generation retry is safe because no external side effect is replayed.
        # Tool replay requires the concrete ToolCall and is handled above.
        pass

    return None


def _attempt_blocker(
    action: str, counters: Counters, limits: ExecutionLimits
) -> Failure | None:
    if action not in {
        "classification",
        "generation",
        "quality_escalation",
        "infrastructure_retry",
        "validation",
        "tool",
        "tool_recovery",
        "increase_effort",
        "increase_tier",
        "retry_backoff",
        "health_aware_fallback",
        "retry_tool",
        "alternate_tool",
    }:
        return _failure(FailureType.CAPABILITY_FAILURE, "unknown_action")

    if action in {
        "generation",
        "quality_escalation",
        "infrastructure_retry",
        "increase_effort",
        "increase_tier",
        "retry_backoff",
        "health_aware_fallback",
    }:
        if counters.generation_attempts >= limits.max_total_generation_attempts:
            return _failure(FailureType.UNKNOWN_FAILURE, "generation_attempts_exhausted")
    if action in {"quality_escalation", "increase_effort", "increase_tier"}:
        if counters.quality_escalations >= limits.max_quality_escalations:
            return _failure(FailureType.QUALITY_FAILURE, "quality_escalations_exhausted")
    if action in {"infrastructure_retry", "retry_backoff", "health_aware_fallback"}:
        if counters.infrastructure_retries >= limits.max_infrastructure_retries:
            return _failure(FailureType.PROVIDER_FAILURE, "infrastructure_retries_exhausted")
    if action in {"tool_recovery", "retry_tool", "alternate_tool"}:
        if counters.tool_recoveries >= limits.max_tool_recoveries:
            return _failure(FailureType.TOOL_FAILURE, "tool_recoveries_exhausted")
    return None


def _check_tool(
    controls: ExecutionControls,
    call: ToolCall | None,
    *,
    replay: bool,
) -> Failure | None:
    if call is None:
        return _failure(FailureType.TOOL_FAILURE, "tool_call_required")
    if call.tool not in controls.authorized_tools:
        return _failure(FailureType.TOOL_FAILURE, "tool_not_authorized")
    alternate = any(
        declared.alternate_tool == call.tool
        and call
        == declared.model_copy(update={"tool": call.tool, "alternate_tool": None})
        for declared in controls.tool_calls
    )
    if controls.tool_calls and call not in controls.tool_calls and not alternate:
        return _failure(FailureType.TOOL_FAILURE, "tool_call_not_authorized")
    if call.side_effecting and controls.side_effects_authorized is not True:
        return _failure(FailureType.TOOL_FAILURE, "side_effect_not_authorized")
    if (
        replay
        and call.side_effecting
        and (
            call.reconciliation_evidence is not True
            and (alternate or call.idempotency_key is None)
        )
    ):
        return _failure(FailureType.TOOL_FAILURE, "unsafe_tool_replay")
    return None


@dataclass
class _Reservation:
    reserved: Decimal
    actual: Decimal | None = None
    settled: bool = False

    @property
    def debit(self) -> Decimal:
        return self.actual if self.settled and self.actual is not None else self.reserved


class MemoryBudgetAuthority:
    """Thread-safe finite per-task balances with idempotent action reservations.

    ``balances`` installs explicit task balances. ``default_ceiling`` may be used
    for synthetic tasks created after construction. If neither supplies a task's
    balance, that task has zero available funds rather than an unlimited balance.
    """

    def __init__(
        self,
        balances: Mapping[str, Money] | None = None,
        *,
        default_ceiling: Money | None = None,
    ) -> None:
        self._lock = RLock()
        default = _amount(default_ceiling) if default_ceiling is not None else None
        if default_ceiling is not None and default is None:
            raise ValueError("default_ceiling must be finite and nonnegative")
        self._default_ceiling = default
        self._balances: dict[str, Decimal] = {}
        self._reservations: dict[str, dict[str, _Reservation]] = {}
        for task_id, amount in (balances or {}).items():
            self.set_balance(task_id, amount)

    def set_balance(self, task_id: str, amount: Money) -> None:
        """Set up a task before reservations exist; never erase prior spending."""

        normalized = _amount(amount)
        if not task_id or normalized is None:
            raise ValueError("task balance requires a task id and finite amount")
        with self._lock:
            if self._reservations.get(task_id):
                raise ValueError("cannot replace a balance after reservation")
            self._balances[task_id] = normalized

    def remaining(self, task_id: str) -> Decimal:
        with self._lock:
            balance = self._task_balance(task_id)
            debited = money_sum(reservation.debit for reservation in self._reservations.get(task_id, {}).values())
            return max(Decimal("0"), money_difference(balance, debited))

    def reserve(self, task_id: str, action_id: str, amount: Money) -> bool:
        normalized = _amount(amount)
        if not task_id or not action_id or normalized is None:
            return False
        with self._lock:
            task_reservations = self._reservations.setdefault(task_id, {})
            existing = task_reservations.get(action_id)
            if existing is not None:
                return existing.reserved == normalized
            if normalized > self.remaining(task_id):
                return False
            task_reservations[action_id] = _Reservation(reserved=normalized)
            return True

    def settle(self, task_id: str, action_id: str, actual: Money | None) -> None:
        with self._lock:
            try:
                reservation = self._reservations[task_id][action_id]
            except KeyError as error:
                raise KeyError("cannot settle an action without a reservation") from error

            # An unknown provider/tool outcome holds the original reservation.
            if actual is None:
                return
            normalized = _amount(actual)
            if normalized is None:
                raise ValueError("actual cost must be finite and nonnegative")
            if reservation.settled:
                if reservation.actual != normalized:
                    raise ValueError("action is already settled with a different amount")
                return
            reservation.actual = normalized
            reservation.settled = True

    def _task_balance(self, task_id: str) -> Decimal:
        balance = self._balances.get(task_id)
        if balance is not None:
            return balance
        if self._default_ceiling is not None:
            self._balances[task_id] = self._default_ceiling
            return self._default_ceiling
        return Decimal("0")


__all__ = ["AdmissionAction", "MemoryBudgetAuthority", "check_admission"]
