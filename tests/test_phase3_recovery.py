from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from model_router.core.contracts import (
    Classification,
    ComplexityComponents,
    Context,
    Effort,
    EnvironmentSnapshot,
    FailureType,
    Limits,
    ModelHealth,
    Request,
    RouteDecision,
)
from model_router.core.execution_contracts import (
    Counters,
    ExecutionLimits,
    Failure,
    RecoveryContext,
    ToolCall,
)
from model_router.escalation import choose_recovery
from model_router.policy.loader import load_bundle
from model_router.router import route


ROOT = Path(__file__).parents[1]
BUNDLE = load_bundle(ROOT / "config")


@pytest.fixture(scope="module")
def bundle():
    return BUNDLE


def _decision(
    *,
    model: str = "terra",
    effort: Effort = Effort.MEDIUM,
    score: int = 49,
    floor: int | None = None,
    hard_floor: int | None = None,
) -> RouteDecision:
    environment = _environment()
    classification = Classification(
        task_family="analysis",
        components=ComplexityComponents(
            reasoning_depth=12,
            step_dependency=11,
            context_synthesis=7,
            technical_precision=11,
            ambiguity=5,
            tool_orchestration=0,
            reliability_requirement=3,
        ),
        confidence=0.95,
        provenance="test",
    )
    request = Request(
        task_id="recovery-task",
        trace_id="recovery-trace",
        input="offline recovery test",
        requirements=("text_input", "text_output"),
        consequence="low",
        context=Context(input_tokens=10, expected_output_tokens=10),
    )
    base = route(request, classification, environment, BUNDLE)
    assert isinstance(base, RouteDecision)
    floors = ()
    if hard_floor is not None:
        floors = ({"rule_id": "test_floor", "strength": "hard", "min_tier": hard_floor},)
    return base.model_copy(
        update={
            "selected_model_alias": model,
            "reasoning_effort": effort,
            "complexity_score": score,
            "effective_limits": Limits(model_tier_floor=floor),
            "rationale_details": {"floors": floors},
        }
    )


def _environment(**models: str) -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        snapshot_id="recovery-snapshot",
        synthetic=True,
        clock=datetime(2026, 9, 6, tzinfo=timezone.utc),
        pricing_version="test-pricing",
        recovery_bounded=True,
        models={
            alias: ModelHealth(state=state, account_access="verified")
            for alias, state in models.items()
        },
    )


def _context(
    failure_type: FailureType,
    *,
    decision: RouteDecision | None = None,
    counters: Counters | None = None,
    environment: EnvironmentSnapshot | None = None,
    remaining: str = "10",
    elapsed_ms: int = 100,
    retry_after_ms: int | None = None,
    tool_call: ToolCall | None = None,
    tool_retryable: bool = False,
    alternate_authorized: bool = False,
    validated: bool = False,
) -> RecoveryContext:
    return RecoveryContext(
        decision=decision or _decision(),
        failure=Failure(
            failure_type=failure_type,
            source="tool" if failure_type == FailureType.TOOL_FAILURE else "provider",
            stage="test",
            cause_code="scripted_failure",
            retryable=tool_retryable if failure_type == FailureType.TOOL_FAILURE else True,
            retry_after_ms=retry_after_ms,
        ),
        counters=counters or Counters(generation_attempts=1),
        limits=ExecutionLimits(
            max_total_generation_attempts=3,
            max_quality_escalations=2,
            max_infrastructure_retries=1,
            max_tool_recoveries=1,
            max_elapsed_ms=30_000,
            initial_backoff_ms=250,
            max_backoff_ms=1_000,
            task_cost_ceiling_usd="20",
        ),
        environment=environment or _environment(),
        remaining_usd=remaining,
        elapsed_ms=elapsed_ms,
        validated=validated,
        tool_call=tool_call,
        tool_retryable=tool_retryable,
        alternate_authorized=alternate_authorized,
    )


def test_quality_uses_prior_effort_then_new_tier_preference(bundle):
    effort_action = choose_recovery(
        _context(FailureType.QUALITY_FAILURE, validated=True), bundle
    )
    assert effort_action.action == "increase_effort"
    assert effort_action.route.model == "terra"
    assert effort_action.route.effort == Effort.HIGH
    assert effort_action.rationale_codes == ("QUALITY_ESCALATION",)
    assert effort_action.validated is True

    tier_action = choose_recovery(
        _context(
            FailureType.QUALITY_FAILURE,
            decision=_decision(effort=Effort.HIGH),
            counters=Counters(generation_attempts=2, quality_escalations=1),
            validated=True,
        ),
        bundle,
    )
    assert tier_action.action == "increase_tier"
    assert tier_action.route.model == "sol"
    assert tier_action.route.effort == Effort.MEDIUM


def test_quality_does_not_walk_into_unlisted_xhigh_or_max(bundle):
    action = choose_recovery(
        _context(
            FailureType.QUALITY_FAILURE,
            decision=_decision(effort=Effort.HIGH),
            counters=Counters(generation_attempts=2, quality_escalations=1),
        ),
        bundle,
    )
    assert action.action == "increase_tier"
    assert action.route.effort == Effort.MEDIUM


def test_quality_attempt_and_budget_bounds_preserve_original_failure(bundle):
    exhausted = choose_recovery(
        _context(
            FailureType.QUALITY_FAILURE,
            counters=Counters(generation_attempts=3, quality_escalations=2),
            validated=True,
        ),
        bundle,
    )
    assert exhausted.action == "stop_attempts"
    assert exhausted.failure == FailureType.BUDGET_FAILURE
    assert exhausted.original_failure == FailureType.QUALITY_FAILURE

    unfunded = choose_recovery(
        _context(FailureType.QUALITY_FAILURE, remaining="0", validated=True), bundle
    )
    assert unfunded.action == "stop_budget"
    assert unfunded.failure == FailureType.BUDGET_FAILURE
    assert unfunded.original_failure == FailureType.QUALITY_FAILURE


def test_infrastructure_retry_honors_retry_after_and_never_promotes(bundle):
    action = choose_recovery(
        _context(FailureType.RATE_LIMIT, retry_after_ms=500), bundle
    )
    assert action.action == "retry_backoff"
    assert action.route.model == "terra"
    assert action.route.effort == Effort.MEDIUM
    assert action.backoff_ms == 500
    assert "QUALITY_ESCALATION" not in action.rationale_codes

    over_bound = choose_recovery(
        _context(FailureType.RATE_LIMIT, retry_after_ms=1_500), bundle
    )
    assert over_bound.action == "recoverable_failure"
    assert over_bound.backoff_ms == 0

    deadline = choose_recovery(
        _context(
            FailureType.RATE_LIMIT,
            retry_after_ms=500,
            elapsed_ms=29_600,
        ),
        bundle,
    )
    assert deadline.action == "stop_deadline"
    assert deadline.original_failure == FailureType.RATE_LIMIT


def test_unhealthy_route_falls_back_only_to_safe_same_or_lower_tier(bundle):
    action = choose_recovery(
        _context(
            FailureType.PROVIDER_FAILURE,
            environment=_environment(terra="UNHEALTHY", luna="HEALTHY"),
        ),
        bundle,
    )
    assert action.action == "health_aware_fallback"
    assert action.route.model == "luna"
    assert action.route.effort == Effort.MEDIUM

    degraded = choose_recovery(
        _context(
            FailureType.PROVIDER_FAILURE,
            environment=_environment(terra="DEGRADED", luna="HEALTHY"),
        ),
        bundle,
    )
    assert degraded.action == "health_aware_fallback"
    assert degraded.route.model == "luna"

    blocked = choose_recovery(
        _context(
            FailureType.PROVIDER_FAILURE,
            decision=_decision(hard_floor=1),
            environment=_environment(
                terra="UNHEALTHY", luna="HEALTHY", sol="UNHEALTHY", astra="UNHEALTHY"
            ),
        ),
        bundle,
    )
    assert blocked.action == "recoverable_failure"
    assert blocked.route is None


def test_tool_recovery_is_tool_only_and_side_effects_require_reconciliation(bundle):
    safe_call = ToolCall(tool="reader", operation="get")
    retry = choose_recovery(
        _context(
            FailureType.TOOL_FAILURE,
            tool_call=safe_call,
            tool_retryable=True,
        ),
        bundle,
    )
    assert retry.action == "retry_tool"
    assert retry.route.model == "terra"

    alternate_call = ToolCall(
        tool="reader", operation="get", alternate_tool="backup_reader"
    )
    alternate = choose_recovery(
        _context(
            FailureType.TOOL_FAILURE,
            tool_call=alternate_call,
            alternate_authorized=True,
        ),
        bundle,
    )
    assert alternate.action == "alternate_tool"

    unsafe_call = ToolCall(tool="writer", operation="create", side_effecting=True)
    reconcile = choose_recovery(
        _context(
            FailureType.TOOL_FAILURE,
            tool_call=unsafe_call,
            tool_retryable=True,
        ),
        bundle,
    )
    assert reconcile.action == "stop_reconcile"
    assert reconcile.route is None


@pytest.mark.parametrize(
    "failure_type",
    [
        FailureType.VALIDATION_FAILURE,
        FailureType.MALFORMED_OUTPUT,
        FailureType.UNKNOWN_FAILURE,
    ],
)
def test_diagnostic_failures_do_not_escalate(failure_type, bundle):
    action = choose_recovery(_context(failure_type), bundle)
    assert action.action == "diagnose"
    assert action.route.model == "terra"
    assert "QUALITY_ESCALATION" not in action.rationale_codes


@pytest.mark.parametrize(
    "failure_type", [FailureType.BUDGET_FAILURE, FailureType.CAPABILITY_FAILURE]
)
def test_terminal_failures_stop(failure_type, bundle):
    action = choose_recovery(_context(failure_type), bundle)
    assert action.action == "stop"
    assert action.failure == failure_type
    assert action.route is None


def test_nonretryable_infrastructure_does_not_backoff(bundle):
    context=_context(FailureType.PROVIDER_FAILURE)
    context=context.model_copy(update={'failure':context.failure.model_copy(update={'retryable':False})})
    action=choose_recovery(context,bundle)
    assert action.action=='recoverable_failure'
    assert action.backoff_ms==0 and action.route is None
