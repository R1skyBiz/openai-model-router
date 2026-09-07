from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel
import pytest

from model_router.core.contracts import Context, FailureType, Limits, Request
from model_router.core.execution_contracts import (
    Counters,
    ExecutionControls,
    ExecutionLimits,
    ToolCall,
)
from model_router.execution.admission import MemoryBudgetAuthority, check_admission
from model_router.execution.clock import MockClock
from model_router.execution.safety import request_digest, scoped_key_digest


def _request(**changes) -> Request:
    values = {
        "task_id": "task-1",
        "trace_id": "trace-1",
        "input": "private prompt",
        "requirements": ("text",),
        "consequence": "low",
        "context": Context(input_tokens=10, expected_output_tokens=10),
        "constraints": Limits(),
    }
    values.update(changes)
    return Request(**values)


def _limits(**changes) -> ExecutionLimits:
    values = {
        "max_total_generation_attempts": 3,
        "max_quality_escalations": 2,
        "max_infrastructure_retries": 1,
        "max_tool_recoveries": 1,
        "max_elapsed_ms": 30_000,
        "initial_backoff_ms": 100,
        "max_backoff_ms": 1_000,
        "task_cost_ceiling_usd": "1.00",
    }
    values.update(changes)
    return ExecutionLimits(**values)


def test_admission_fails_closed_and_enforces_time_cost_and_attempts():
    request = _request()
    controls = ExecutionControls(authorized=True)
    counters = Counters()

    assert check_admission(request, controls, None, counters, 0, "1", "0.1").cause_code == "execution_limits_required"
    assert check_admission(request, ExecutionControls(), _limits(), counters, 0, "1", "0.1").cause_code == "execution_not_authorized"
    assert check_admission(request, controls, _limits(), counters, 30_000, "1", "0.1").failure_type is FailureType.TIMEOUT
    assert check_admission(request, controls, _limits(), counters, 0, None, "0.1").cause_code == "remaining_budget_required"
    assert check_admission(request, controls, _limits(), counters, 0, "1", None).cause_code == "action_cost_required"
    assert check_admission(request, controls, _limits(), counters, 0, "0.09", "0.1").cause_code == "remaining_budget_exceeded"
    assert check_admission(request, controls, _limits(), Counters(generation_attempts=3), 0, "1", "0.1").cause_code == "generation_attempts_exhausted"
    assert check_admission(
        request,
        controls,
        _limits(),
        Counters(quality_escalations=2),
        0,
        "1",
        "0.1",
        action="increase_effort",
    ).cause_code == "quality_escalations_exhausted"
    assert check_admission(request, controls, _limits(), counters, 0, "1", "0.1") is None


def test_tool_scope_and_replay_use_concrete_call_evidence():
    request = _request(side_effecting_tool=True, idempotency_evidence=True)
    unsafe = ToolCall(tool="mail", operation="send", side_effecting=True)
    authorized = ExecutionControls(
        authorized=True,
        authorized_tools=("mail",),
        side_effects_authorized=True,
        tool_calls=(unsafe,),
    )

    failure = check_admission(
        request,
        authorized,
        _limits(),
        Counters(),
        0,
        "1",
        "0.1",
        action="tool_recovery",
        replay=True,
        tool_call=unsafe,
    )
    assert failure is not None and failure.cause_code == "unsafe_tool_replay"

    safe = unsafe.model_copy(update={"idempotency_key": "send-1"})
    safe_controls = authorized.model_copy(update={"tool_calls": (safe,)})
    assert check_admission(
        request, safe_controls, _limits(), Counters(), 0, "1", "0.1",
        action="tool_recovery", replay=True, tool_call=safe,
    ) is None

    other_operation = safe.model_copy(update={"operation": "delete"})
    failure = check_admission(
        request, safe_controls, _limits(), Counters(), 0, "1", "0.1",
        action="tool", tool_call=other_operation,
    )
    assert failure is not None and failure.cause_code == "tool_call_not_authorized"

    declared_alternate = ToolCall(
        tool="primary-writer",
        operation="create",
        side_effecting=True,
        idempotency_key="primary-only-key",
        alternate_tool="backup-writer",
    )
    alternate = declared_alternate.model_copy(
        update={"tool": "backup-writer", "alternate_tool": None}
    )
    alternate_controls = ExecutionControls(
        authorized=True,
        authorized_tools=("primary-writer", "backup-writer"),
        side_effects_authorized=True,
        tool_calls=(declared_alternate,),
    )
    failure = check_admission(
        request,
        alternate_controls,
        _limits(),
        Counters(),
        0,
        "1",
        "0.1",
        action="tool_recovery",
        replay=True,
        tool_call=alternate,
    )
    assert failure is not None and failure.cause_code == "unsafe_tool_replay"

    reconciled_declaration = declared_alternate.model_copy(
        update={"reconciliation_evidence": True}
    )
    reconciled = reconciled_declaration.model_copy(
        update={"tool": "backup-writer", "alternate_tool": None}
    )
    reconciled_controls = alternate_controls.model_copy(
        update={"tool_calls": (reconciled_declaration,)}
    )
    assert check_admission(
        request,
        reconciled_controls,
        _limits(),
        Counters(),
        0,
        "1",
        "0.1",
        action="tool_recovery",
        replay=True,
        tool_call=reconciled,
    ) is None


def test_memory_budget_reservations_are_finite_idempotent_and_hold_unknowns():
    authority = MemoryBudgetAuthority({"task": "1.00"})
    assert authority.reserve("task", "attempt-1", "0.60")
    assert authority.remaining("task") == Decimal("0.40")
    assert authority.reserve("task", "attempt-1", "0.60")
    assert authority.remaining("task") == Decimal("0.40")
    assert not authority.reserve("task", "attempt-1", "0.50")
    assert not authority.reserve("task", "attempt-2", "0.50")

    authority.settle("task", "attempt-1", None)
    assert authority.remaining("task") == Decimal("0.40")
    authority.settle("task", "attempt-1", "0.25")
    assert authority.remaining("task") == Decimal("0.75")
    authority.settle("task", "attempt-1", "0.25")
    with pytest.raises(ValueError, match="different amount"):
        authority.settle("task", "attempt-1", "0.30")

    assert MemoryBudgetAuthority().remaining("unconfigured") == Decimal("0")
    defaulted = MemoryBudgetAuthority(default_ceiling="0.20")
    assert defaulted.reserve("new-task", "a", "0.20")
    assert defaulted.remaining("new-task") == Decimal("0.00")


class _Output(BaseModel):
    answer: str


class _OtherOutput(BaseModel):
    value: int


def test_request_digest_covers_hidden_values_but_not_trace_identity():
    call = ToolCall(
        tool="lookup",
        operation="find",
        arguments={"secret": "one"},
        idempotency_key="tool-key",
    )
    controls = ExecutionControls(
        authorized=True,
        idempotency_key="task-key",
        authorized_tools=("lookup",),
        tool_calls=(call,),
        output_type=_Output,
    )
    first = request_digest(_request(), controls)
    retried = request_digest(_request(task_id="task-2", trace_id="trace-2"), controls)
    assert first == retried
    assert first != request_digest(_request(input="changed"), controls)
    assert first != request_digest(
        _request(),
        controls.model_copy(update={"idempotency_key": "different"}),
    )
    assert first != request_digest(
        _request(), controls.model_copy(update={"output_type": _OtherOutput})
    )
    changed_call = call.model_copy(update={"arguments": {"secret": "two"}})
    assert first != request_digest(
        _request(),
        controls.model_copy(update={"tool_calls": (changed_call,)}),
    )
    assert scoped_key_digest("app-a", "same") != scoped_key_digest("app-b", "same")


def test_mock_clock_advances_and_records_sleep_without_wall_time():
    initial = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = MockClock(initial)
    clock.advance(25)
    clock.sleep(75)
    assert (clock.now() - initial).total_seconds() == 0.1
    assert clock.sleep_calls == [75]
    with pytest.raises(ValueError):
        clock.advance(-1)
