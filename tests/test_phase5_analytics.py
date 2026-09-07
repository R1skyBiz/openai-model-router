"""Phase 5 KPI arithmetic, cohort semantics, and attribution regressions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext

import pytest

from model_router.core.contracts import Classification, FailureType, RouteDecision
from model_router.core.execution_contracts import (
    Attempt,
    Counters,
    ExecutionEvent,
    Failure,
    RecoveryAction,
    ShadowRun,
    TaskResult,
    ToolOutcome,
    ValidationOutcome,
)
from model_router.core.provider_contracts import ProviderFailure, ProviderResult, ProviderUsage
from model_router.telemetry.analytics import Analytics
from model_router.telemetry.schemas import Efficacy, Policies, Routing, Spend, Summary


NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)


def classification(family="analysis", complexity=20):
    return Classification(
        task_family=family,
        confidence=1.0,
        provenance="phase5-test",
        components={
            "reasoning_depth": complexity,
            "step_dependency": 0,
            "context_synthesis": 0,
            "technical_precision": 0,
            "ambiguity": 0,
            "tool_orchestration": 0,
            "reliability_requirement": 0,
        },
    )


def decision(
    task_id: str,
    *,
    model="luna",
    effort="low",
    family="analysis",
    policy="policy-a",
    synthetic=False,
    rationale=(),
    validation="V1",
    complexity=20,
):
    classified = classification(family, complexity)
    return RouteDecision(
        task_id=task_id,
        trace_id=f"trace-{task_id}",
        decision_id=f"decision-{task_id}-{model}-{effort}",
        policy_version=policy,
        catalog_version="catalog-v1",
        pricing_version="pricing-at-execution",
        budget_version="budget-v1",
        validation_version="validation-v1",
        application_overlay_version=None,
        effective_configuration_hash="hash",
        classification=classified,
        complexity_score=complexity,
        rationale_codes=rationale,
        rationale_details={},
        effective_limits={},
        environment_snapshot_id="environment",
        synthetic=synthetic,
        health_snapshot_id=None,
        readiness_blockers=(),
        selected_model_alias=model,
        provider_model_id=f"provider-{model}",
        model_tier=1,
        reasoning_effort=effort,
        validation_level=validation,
        validation_requirements={
            "level": validation,
            "profiles": (validation,),
            "checks": (),
            "evidence": "phase5-test",
        },
        estimated_cost={
            "status": "known",
            "amount": "0.10",
            "currency": "USD",
            "pricing_version": "pricing-at-execution",
            "model_pricing_version": "model-pricing-v1",
            "token_assumptions": {"input_tokens": 10, "expected_output_tokens": 10},
            "known_subtotal": "0.10",
            "generation_subtotal": "0.10",
            "breakdown": {"generation": "0.10"},
        },
        executable=True,
    )


def failure(kind=FailureType.QUALITY_FAILURE, source="validation"):
    return Failure(
        failure_type=kind,
        source=source,
        stage="execution",
        cause_code="test_failure",
        retryable=kind in {FailureType.TIMEOUT, FailureType.RATE_LIMIT, FailureType.PROVIDER_FAILURE},
    )


def attempt(
    task_id: str,
    sequence: int,
    route: RouteDecision,
    *,
    cost="0.10",
    started=None,
    completed=None,
    status="succeeded",
    purpose="generation",
    role="production",
    failed=None,
    validations=(),
    parent=None,
    evaluator_ref=None,
):
    started = started or NOW - timedelta(hours=1)
    completed = completed if completed is not None else started + timedelta(milliseconds=100)
    return Attempt(
        attempt_id=f"attempt-{task_id}-{purpose}-{sequence}-{role}",
        task_id=task_id,
        trace_id=f"trace-{task_id}",
        sequence=sequence,
        purpose=purpose,
        role=role,
        evaluator_ref=evaluator_ref,
        parent_attempt_id=parent,
        decision=route,
        status=status,
        started_at=started,
        completed_at=completed,
        actual_cost_usd=cost,
        pricing_version="pricing-at-execution",
        failure=failed,
        validations=validations,
    )


def task(
    task_id: str,
    *,
    status="succeeded",
    created=None,
    updated=None,
    cost="0.10",
    known=None,
    model="luna",
    effort="low",
    family="analysis",
    policy="policy-a",
    synthetic=False,
    attempts=None,
    evaluator_attempts=(),
    domain_validations=(),
    shadow_runs=(),
    tool_events=(),
    actions=(),
    counters=None,
    rationale=(),
):
    created = created or NOW - timedelta(days=1)
    updated = updated or created + timedelta(milliseconds=100)
    route = decision(
        task_id,
        model=model,
        effort=effort,
        family=family,
        policy=policy,
        synthetic=synthetic,
        rationale=rationale,
    )
    if attempts is None:
        attempts = (attempt(task_id, 1, route, cost=cost, started=created, completed=updated),)
    return TaskResult(
        application_id="app-a",
        task_id=task_id,
        trace_id=f"trace-{task_id}",
        status=status,
        policy_version=policy,
        created_at=created,
        updated_at=updated,
        classification=route.classification,
        initial_decision=route,
        decisions=(route,),
        attempts=attempts,
        evaluator_attempts=evaluator_attempts,
        domain_validations=domain_validations,
        shadow_runs=shadow_runs,
        tool_events=tool_events,
        recovery_actions=actions,
        counters=counters or Counters(),
        total_cost_usd=cost,
        known_cost_usd=known if known is not None else (cost if cost is not None else "0"),
    )


def event(task_id, kind, occurred_at, *, attempt_id=None, tool_id=None, evaluation_id=None):
    return ExecutionEvent(
        event_id=f"event-{task_id}-{kind}-{attempt_id or tool_id or evaluation_id or 'task'}",
        task_id=task_id,
        trace_id=f"trace-{task_id}",
        kind=kind,
        occurred_at=occurred_at,
        policy_version="policy-a",
        attempt_id=attempt_id,
        tool_event_id=tool_id,
        evaluation_id=evaluation_id,
    )


def analytics(tasks, events=(), **filters):
    return Analytics(tuple(tasks), tuple(events), now=NOW, filters=filters, synthetic=False)


def test_terminal_cancelled_blocked_pending_and_task_denominators_are_explicit():
    succeeded = task("success", cost="0.10", updated=NOW - timedelta(days=1, microseconds=-100_000))
    succeeded = succeeded.model_copy(update={"recovery_actions": (
        RecoveryAction(action="stop_success", validated=True, reason="validated_success"),
    )})
    failed_route = decision("failed")
    escalation = RecoveryAction(
        action="increase_effort",
        failure="QUALITY_FAILURE",
        route={"model": "luna", "effort": "medium"},
        reason="quality",
    )
    failed = task(
        "failed",
        status="failed",
        cost="0.40",
        attempts=(
            attempt("failed", 1, failed_route, cost="0.15", failed=failure()),
            attempt("failed", 2, failed_route, cost="0.25", status="failed", failed=failure()),
        ),
        actions=(escalation,),
        counters=Counters(generation_attempts=2, quality_escalations=1),
    )
    cancelled = task("cancelled", status="cancelled", cost="0")
    blocked = task("blocked", status="blocked", cost="0", attempts=())
    running = task("running", status="running", cost=None, known="0.20")

    metrics = analytics([succeeded, failed, cancelled, blocked, running]).summary()["metrics"]

    assert (metrics["total_tasks"], metrics["terminal_tasks"], metrics["pending_tasks"]) == (5, 3, 2)
    assert (metrics["cancelled_tasks"], metrics["blocked_tasks"], metrics["successful_tasks"]) == (1, 1, 1)
    assert metrics["first_pass_success"] == {"value": 1 / 3, "numerator": 1, "denominator": 3}
    assert metrics["final_success"] == {"value": 1 / 3, "numerator": 1, "denominator": 3}
    assert metrics["escalation_rate"] == {"value": 1 / 3, "numerator": 1, "denominator": 3}
    assert metrics["cost"] == {
        "amount": "0.5", "known_subtotal": "0.5", "missing_count": 0, "status": "known"
    }
    assert metrics["cost_per_task"]["amount"].startswith("0.1666666666666666")
    assert metrics["effective_cost_per_success"]["amount"] == "0.5"


def test_unknown_partial_and_empty_costs_never_become_zero():
    known = task("known", cost="0.20")
    unknown = task("unknown", cost=None, known="0.10")
    zero = task("zero", cost="0", attempts=())
    result = analytics([known, unknown, zero]).summary()["metrics"]

    assert result["cost"] == {
        "amount": None, "known_subtotal": "0.3", "missing_count": 1, "status": "partial"
    }
    assert result["cost_per_task"]["amount"] is None
    assert result["cost_per_task"]["known_subtotal"] == "0.1"
    empty = analytics([known], start=NOW - timedelta(days=10), end=NOW - timedelta(days=9)).summary()["metrics"]
    assert empty["cost"] == {
        "amount": None, "known_subtotal": "0", "missing_count": 0, "status": "unavailable"
    }
    assert empty["final_success"] == {"value": None, "numerator": 0, "denominator": 0}

    only_unknown = analytics([unknown]).summary()["metrics"]["cost"]
    assert only_unknown == {
        "amount": None, "known_subtotal": "0.1", "missing_count": 1, "status": "partial"
    }


def test_cancelled_predispatch_attempt_is_not_a_provider_call_or_spend_charge():
    route = decision("predispatch")
    cancelled = attempt(
        "predispatch", 1, route, cost="0", status="cancelled",
        started=NOW - timedelta(hours=1), completed=NOW - timedelta(hours=1),
    )
    record = task("predispatch", status="cancelled", cost="0", attempts=(cancelled,))
    service = analytics([record])
    assert service.summary()["metrics"]["infrastructure_retry_rate"]["denominator"] == 0
    assert service.spend()["production"]["status"] == "unavailable"


def test_direct_tool_charge_without_any_attempt_is_safe_and_unallocated():
    tool = ToolOutcome(
        tool_event_id="tool-only", tool="billing", operation="read", status="succeeded", cost_usd="0.07"
    )
    record = task("tool-only", cost="0.07", attempts=(), tool_events=(tool,))
    spend = analytics([record]).spend()
    assert spend["production"]["status"] == "unavailable"
    assert spend["unallocated"]["amount"] == "0.07"


@pytest.mark.parametrize("status", ["succeeded", "failed", "unknown"])
def test_completed_tool_with_missing_fee_remains_partial_spend(status):
    tool = ToolOutcome(
        tool_event_id=f"unknown-fee-{status}", tool="metered", operation="read",
        status=status, cost_usd=None, estimated_cost_usd=None,
        failure=failure(FailureType.TOOL_FAILURE, "tool") if status == "failed" else None,
    )
    record = task(f"unknown-fee-{status}", cost=None, attempts=(), tool_events=(tool,))
    occurred = NOW - timedelta(minutes=5)
    completed = event(record.task_id, "TOOL_COMPLETED", occurred, tool_id=tool.tool_event_id)
    spend = analytics([record], (completed,)).spend()
    assert spend["production"] == {
        "amount": None, "known_subtotal": "0", "missing_count": 1, "status": "partial"
    }


def test_spend_reconciles_occurrence_charges_and_keeps_shadow_and_unallocated_separate():
    task_id = "spend"
    route = decision(task_id)
    start = datetime(2026, 9, 2, 1, tzinfo=UTC)
    v0 = ValidationOutcome(evaluation_id="v0", check="shape", status="passed", cost_usd="0.03")
    evaluator_result = ValidationOutcome(
        evaluation_id="eval", check="quality", status="passed", cost_usd="0",
        evaluator_attempt_id="eval-attempt", target_attempt_id="generation", rubric_version="r1",
        score=0.8, score_min=0.0, score_max=1.0,
    )
    generation = attempt(task_id, 1, route, cost="0.10", started=start, completed=start, validations=(v0,))
    evaluator = attempt(
        task_id, 2, route, cost="0.02", started=start + timedelta(hours=1),
        completed=start + timedelta(hours=1), purpose="evaluation", evaluator_ref="judge",
        parent=generation.attempt_id, validations=(evaluator_result,),
    )
    placed_tool = ToolOutcome(
        tool_event_id="placed-tool", tool="search", operation="query", status="succeeded", cost_usd="0.04"
    )
    unplaced_tool = ToolOutcome(
        tool_event_id="unplaced-tool", tool="storage", operation="put", status="succeeded", cost_usd="0.06"
    )
    shadow_attempt = attempt(
        task_id, 1, decision(task_id, model="terra", effort="high", synthetic=True),
        cost="0.05", started=start + timedelta(hours=2), completed=start + timedelta(hours=2), role="shadow",
    )
    shadow = ShadowRun(
        shadow_id="shadow", production_attempt_id=generation.attempt_id, config_version="shadow-v1",
        sampling_seed="seed", sampling_rate=1.0, selected=True, status="succeeded", reason="shadow_succeeded",
        attempts=(shadow_attempt,), generation_cost_usd="0.05", validation_cost_usd="0",
    )
    record = task(
        task_id, created=NOW - timedelta(days=90), cost="0.25", attempts=(generation,),
        evaluator_attempts=(evaluator,), shadow_runs=(shadow,), tool_events=(placed_tool, unplaced_tool),
    )
    events = (
        event(task_id, "VALIDATION_COMPLETED", start + timedelta(minutes=10), evaluation_id="v0"),
        event(task_id, "TOOL_COMPLETED", start + timedelta(minutes=20), tool_id="placed-tool"),
    )

    result = analytics(
        [record], events, start=datetime(2026, 9, 2, tzinfo=UTC), end=datetime(2026, 9, 3, tzinfo=UTC)
    ).spend()

    assert result["production"] == {
        "amount": "0.19", "known_subtotal": "0.19", "missing_count": 0, "status": "known"
    }
    assert result["shadow"]["amount"] == "0.05"
    assert result["all_spend"]["amount"] == "0.24"
    assert result["unallocated"]["amount"] == "0.06"
    assert sum(Decimal(group["cost"]["amount"]) for group in result["by_contribution"]) == Decimal("0.19")
    assert {group["key"] for group in result["by_purpose"]} == {"generation", "evaluation", "validation", "tool"}
    # The evaluator result cost is a reference to its attempt and is not counted again.
    assert sum(group["count"] for group in result["by_purpose"]) == 4


def test_summary_calendar_spend_and_linear_projection_ignore_selected_time_window():
    month_start = datetime(2026, 9, 1, tzinfo=UTC)
    early = task(
        "early", created=NOW - timedelta(days=90), cost="0.10",
        attempts=(attempt("early", 1, decision("early"), cost="0.10", started=month_start, completed=month_start),),
    )
    today = task(
        "today", created=NOW - timedelta(days=90), cost="0.20",
        attempts=(attempt("today", 1, decision("today"), cost="0.20", started=NOW - timedelta(hours=1), completed=NOW - timedelta(hours=1)),),
    )
    result = analytics(
        [early, today], start=NOW - timedelta(minutes=30), end=NOW
    ).summary()

    assert result["metrics"]["total_tasks"] == 0
    assert result["spend_today"]["amount"] == "0.2"
    assert result["spend_mtd"]["amount"] == "0.3"
    assert result["projected_month"]["amount"].startswith("1.6363636363636363")
    assert result["forecast_method"] == "linear_mtd_run_rate"


def test_initial_route_owns_task_kpis_while_invoked_route_owns_spend():
    task_id = "attribution"
    initial = decision(task_id, model="luna", effort="low", rationale=("FLOOR_RELAXED",))
    recovered = decision(task_id, model="terra", effort="high")
    action = RecoveryAction(
        action="increase_tier", failure="QUALITY_FAILURE",
        route={"model": "terra", "effort": "high"}, reason="quality",
    )
    record = task(
        task_id, model="luna", effort="low", cost="0.30",
        attempts=(
            attempt(task_id, 1, initial, cost="0.10", failed=failure()),
            attempt(task_id, 2, recovered, cost="0.20"),
        ),
        actions=(action,), counters=Counters(generation_attempts=2, quality_escalations=1),
        rationale=("FLOOR_RELAXED",),
    )
    service = analytics([record], model="luna")
    routing = service.routing()
    spend = analytics([record]).spend()

    assert routing["models"] == [{"key": "luna", "count": 1, "share": 1.0}]
    assert routing["preferred_floor_relaxation"] == {"value": 1.0, "numerator": 1, "denominator": 1}
    assert routing["escalation_flow"] == [{"source": "luna/low", "target": "terra/high", "count": 1}]
    assert {group["key"]: group["cost"]["amount"] for group in spend["by_model"]} == {
        "luna": "0.1", "terra": "0.2"
    }
    assert {group["key"]: group["cost"]["amount"] for group in spend["by_contribution"]} == {
        "generation": "0.1", "retry": "0.2"
    }
    assert analytics([record], model="terra").summary()["metrics"]["total_tasks"] == 0
    assert analytics([record], model="terra").spend()["production"]["amount"] == "0.2"


def test_provider_evidence_owns_actual_evaluator_model_and_effort_spend():
    task_id = "evaluator-attribution"
    route = decision(task_id, model="luna", effort="low")
    evidence = ProviderResult(
        task_id=task_id, trace_id=f"trace-{task_id}", invocation_id="evaluator-call",
        policy_version="policy-a", catalog_version="catalog-v1", model_alias="sol",
        provider_model_id="provider-sol", reasoning_effort="xhigh", purpose="evaluation",
        response_status="completed", latency_ms=20.0,
        usage=ProviderUsage(input_tokens=10, cached_input_tokens=0, cache_write_input_tokens=0,
                            output_tokens=10, reasoning_tokens=5, total_tokens=20),
    )
    evaluator = Attempt(
        attempt_id="evaluator-call", task_id=task_id, trace_id=f"trace-{task_id}", sequence=1,
        purpose="evaluation", evaluator_ref="judge", parent_attempt_id="generation",
        decision=route, status="succeeded", started_at=NOW - timedelta(hours=1),
        completed_at=NOW - timedelta(hours=1), actual_cost_usd="0.08",
        pricing_version="pricing-at-execution", provider_outcome=evidence,
    )
    record = task(
        task_id, cost="0.18", attempts=(attempt(task_id, 1, route, cost="0.10"),),
        evaluator_attempts=(evaluator,),
    )
    spend = analytics([record]).spend()
    assert {group["key"]: group["cost"]["amount"] for group in spend["by_model"]} == {
        "luna": "0.1", "sol": "0.08"
    }
    assert {group["key"]: group["cost"]["amount"] for group in spend["by_effort"]} == {
        "low": "0.1", "xhigh": "0.08"
    }
    assert analytics([record], model="sol", effort="xhigh").spend()["production"]["amount"] == "0.08"


def test_spend_groups_sort_by_known_subtotal_and_disclose_partial_ranking():
    luna = task("sort-luna", cost="0.10", model="luna")
    terra = task("sort-terra", cost="0.20", model="terra")
    sol_route = decision("sort-sol", model="sol")
    sol = task(
        "sort-sol", model="sol", cost=None, known="0.15",
        attempts=(
            attempt("sort-sol", 1, sol_route, cost="0.15"),
            attempt(
                "sort-sol", 2, sol_route, cost=None, status="started",
                started=NOW - timedelta(minutes=2), completed=NOW - timedelta(minutes=1),
            ),
        ),
    )
    spend = analytics([luna, terra, sol]).spend()
    assert [group["key"] for group in spend["by_model"]] == ["terra", "sol", "luna"]
    assert spend["by_model"][1]["cost"] == {
        "amount": None, "known_subtotal": "0.15", "missing_count": 1, "status": "partial"
    }
    assert any("ranked by known subtotal" in note for note in spend["meta"]["notes"])


def test_incomplete_evaluator_uses_pinned_binding_for_unknown_spend_attribution():
    task_id = "pending-evaluator"
    route = decision(task_id)
    pending = Attempt(
        attempt_id="pending-evaluator-call", task_id=task_id, trace_id=f"trace-{task_id}", sequence=1,
        purpose="evaluation", evaluator_ref="judge", parent_attempt_id="generation", decision=route,
        status="started", started_at=NOW - timedelta(minutes=10), actual_cost_usd=None,
        pricing_version="pricing-at-execution",
    )
    record = task(task_id, status="validating", cost=None, attempts=(), evaluator_attempts=(pending,))
    record = record.model_copy(update={"phase4_config": {
        "evaluators": ({"ref": "judge", "model_alias": "sol", "reasoning_effort": "high"},)
    }})
    spend = analytics([record], model="sol", effort="high").spend()
    assert spend["production"] == {
        "amount": None, "known_subtotal": "0", "missing_count": 1, "status": "partial"
    }
    assert spend["by_model"][0]["key"] == "sol"


def test_infrastructure_retry_uses_attempt_denominator_and_includes_evaluator_retries():
    task_id = "retry"
    route = decision(task_id)
    generation_one = attempt(
        task_id, 1, route, cost="0.01", status="failed",
        failed=failure(FailureType.TIMEOUT, "provider"),
    )
    generation_two = attempt(task_id, 2, route, cost="0.02")
    evaluator_one = attempt(
        task_id, 3, route, cost="0.03", purpose="evaluation", status="failed",
        failed=failure(FailureType.RATE_LIMIT, "evaluator"), parent=generation_two.attempt_id,
        evaluator_ref="judge",
    )
    evaluator_two = attempt(
        task_id, 4, route, cost="0.04", purpose="evaluation", parent=generation_two.attempt_id,
        evaluator_ref="judge",
    )
    retry = RecoveryAction(
        action="retry_backoff", failure="TIMEOUT", reason="provider retry", backoff_ms=10
    )
    evaluator_retry = RecoveryAction(
        action="retry_evaluator", failure="RATE_LIMIT", reason="evaluator retry", backoff_ms=10
    )
    record = task(
        task_id, cost="0.10", attempts=(generation_one, generation_two),
        evaluator_attempts=(evaluator_one, evaluator_two), actions=(retry, evaluator_retry),
        counters=Counters(generation_attempts=2, infrastructure_retries=1),
    )
    rate = analytics([record]).summary()["metrics"]["infrastructure_retry_rate"]
    assert rate == {"value": 0.5, "numerator": 2, "denominator": 4}


def test_infrastructure_retry_falls_back_to_provider_failure_evidence():
    task_id = "provider-evidence-retry"
    route = decision(task_id)
    provider_failure = ProviderFailure(
        task_id=task_id, trace_id=f"trace-{task_id}", invocation_id="provider-only-failure",
        policy_version="policy-a", catalog_version="catalog-v1", model_alias="luna",
        provider_model_id="provider-luna", reasoning_effort="low", purpose="generation",
        latency_ms=25.0, failure_type="TIMEOUT", source="provider", stage="invocation",
        cause_code="provider_timeout", retryable=True,
    )
    first = attempt(task_id, 1, route, cost="0.01", status="failed", failed=None)
    first = first.model_copy(update={"attempt_id": "provider-only-failure", "provider_outcome": provider_failure})
    second = attempt(task_id, 2, route, cost="0.02")
    record = task(task_id, cost="0.03", attempts=(first, second), actions=())
    retry_rate = analytics([record]).summary()["metrics"]["infrastructure_retry_rate"]
    assert retry_rate == {"value": 0.5, "numerator": 1, "denominator": 2}


def test_retry_metrics_and_first_pass_exclude_legacy_shadow_role_attempts():
    task_id = "legacy-shadow-attempts"
    route = decision(task_id)
    production = attempt(task_id, 1, route, cost="0.10")
    shadow_failure = attempt(
        task_id, 2, route, cost="0.01", role="shadow", status="failed",
        failed=failure(FailureType.TIMEOUT, "provider"),
    )
    shadow_retry = attempt(task_id, 3, route, cost="0.02", role="shadow")
    shadow_evaluator = attempt(
        task_id, 4, route, cost="0.01", purpose="evaluation", role="shadow",
        evaluator_ref="judge", parent=production.attempt_id,
    )
    record = task(
        task_id, cost="0.10", attempts=(production, shadow_failure, shadow_retry),
        evaluator_attempts=(shadow_evaluator,), actions=(),
    )
    metrics = analytics([record]).summary()["metrics"]
    assert metrics["infrastructure_retry_rate"] == {
        "value": 0.0, "numerator": 0, "denominator": 1
    }
    assert metrics["first_pass_success"] == {"value": 1.0, "numerator": 1, "denominator": 1}


def test_first_pass_uses_retained_evaluator_tool_and_classifier_retry_evidence():
    evaluator_task_id = "first-pass-evaluator-retry"
    route = decision(evaluator_task_id)
    generation = attempt(evaluator_task_id, 1, route)
    first_evaluator = attempt(
        evaluator_task_id, 1, route, purpose="evaluation", parent=generation.attempt_id,
        evaluator_ref="judge", status="failed", failed=failure(FailureType.TIMEOUT, "evaluator"),
    )
    second_evaluator = attempt(
        evaluator_task_id, 2, route, purpose="evaluation", parent=generation.attempt_id,
        evaluator_ref="judge",
    )
    evaluator_retry = task(
        evaluator_task_id, attempts=(generation,),
        evaluator_attempts=(first_evaluator, second_evaluator), actions=(),
    )

    tool_task_id = "first-pass-tool-retry"
    tools = (
        ToolOutcome(
            tool_event_id="tool-first", tool="search", operation="read", status="failed",
            cost_usd="0", failure=failure(FailureType.TOOL_FAILURE, "tool"),
        ),
        ToolOutcome(
            tool_event_id="tool-second", tool="search", operation="read", status="succeeded",
            cost_usd="0",
        ),
    )
    tool_retry = task(tool_task_id, tool_events=tools, actions=())

    classifier_task_id = "first-pass-classifier-retry"
    classifier_route = decision(classifier_task_id)
    classifier_retry = task(
        classifier_task_id,
        attempts=(
            attempt(
                classifier_task_id, 1, classifier_route, purpose="classification", status="failed",
                failed=failure(FailureType.RATE_LIMIT, "provider"),
            ),
            attempt(classifier_task_id, 2, classifier_route, purpose="classification"),
            attempt(classifier_task_id, 3, classifier_route, purpose="generation"),
        ),
        actions=(),
    )

    metrics = analytics([evaluator_retry, tool_retry, classifier_retry]).summary()["metrics"]
    assert metrics["first_pass_success"] == {"value": 0.0, "numerator": 0, "denominator": 3}


def test_distinct_required_evaluators_are_not_misclassified_as_retry():
    task_id = "two-required-evaluators"
    route = decision(task_id)
    generation = attempt(task_id, 1, route)
    evaluators = (
        attempt(
            task_id, 1, route, purpose="evaluation", parent=generation.attempt_id,
            evaluator_ref="judge-a",
        ),
        attempt(
            task_id, 2, route, purpose="evaluation", parent=generation.attempt_id,
            evaluator_ref="judge-b",
        ),
    )
    record = task(task_id, attempts=(generation,), evaluator_attempts=evaluators, actions=())
    first_pass = analytics([record]).summary()["metrics"]["first_pass_success"]
    assert first_pass == {"value": 1.0, "numerator": 1, "denominator": 1}


def test_tool_recovery_is_a_task_rate_and_does_not_inflate_infrastructure_retry():
    recovered = RecoveryAction(
        action="alternate_tool", failure="TOOL_FAILURE", reason="alternate succeeded"
    )
    a = task("tool-a", actions=(recovered,), counters=Counters(tool_recoveries=1))
    b = task("tool-b")
    metrics = analytics([a, b]).summary()["metrics"]
    assert metrics["tool_recovery_rate"] == {"value": 0.5, "numerator": 1, "denominator": 2}
    assert metrics["infrastructure_retry_rate"]["numerator"] == 0


def scored(task_id, sequence, route, target, score, *, rubric="rubric-v1", check="quality"):
    outcome = ValidationOutcome(
        evaluation_id=f"score-{task_id}-{sequence}", check=check, status="passed", applicable=True,
        evaluator_attempt_id=f"attempt-{task_id}-evaluation-{sequence}-production",
        target_attempt_id=target, rubric_version=rubric, score=score, score_min=0.0, score_max=1.0,
    )
    return attempt(
        task_id, sequence, route, cost="0.01", purpose="evaluation", parent=target,
        evaluator_ref="judge", validations=(outcome,),
    )


def test_quality_uses_final_score_per_target_and_never_mixes_rubrics():
    route_a = decision("qa")
    gen_a = attempt("qa", 1, route_a)
    first = scored("qa", 2, route_a, gen_a.attempt_id, 0.2)
    final = scored("qa", 3, route_a, gen_a.attempt_id, 0.8)
    a = task("qa", attempts=(gen_a,), evaluator_attempts=(first, final))
    route_b = decision("qb")
    gen_b = attempt("qb", 1, route_b)
    b = task("qb", attempts=(gen_b,), evaluator_attempts=(scored("qb", 2, route_b, gen_b.attempt_id, 0.6),))

    quality = analytics([a, b]).efficacy()["cohorts"][0]["quality"]
    assert quality["comparable"] is True
    assert quality["groups"][0]["sample_size"] == 2
    assert quality["groups"][0]["mean"] == pytest.approx(0.7)

    route_c = decision("qc")
    gen_c = attempt("qc", 1, route_c)
    c = task(
        "qc", attempts=(gen_c,),
        evaluator_attempts=(scored("qc", 2, route_c, gen_c.attempt_id, 0.9, rubric="rubric-v2"),),
    )
    mixed = analytics([a, b, c]).efficacy()["cohorts"][0]["quality"]
    assert mixed["comparable"] is False
    assert mixed["reason"] == "mixed_rubric_check_scale_or_role"
    assert len(mixed["groups"]) == 2


def test_quality_target_ids_are_scoped_by_task_and_final_error_supersedes_prior_score():
    records = []
    for task_id, score in (("scoped-a", 0.2), ("scoped-b", 0.8)):
        route = decision(task_id)
        generation = attempt(task_id, 1, route)
        records.append(task(
            task_id, attempts=(generation,),
            evaluator_attempts=(scored(task_id, 2, route, "local-attempt-1", score),),
        ))
    quality = analytics(records).efficacy()["cohorts"][0]["quality"]
    assert quality["groups"][0]["sample_size"] == 2
    assert quality["groups"][0]["mean"] == pytest.approx(0.5)

    task_id = "final-error"
    route = decision(task_id)
    generation = attempt(task_id, 1, route)
    valid = scored(task_id, 2, route, generation.attempt_id, 0.9)
    error_outcome = ValidationOutcome(
        evaluation_id="final-error-result", check="quality", status="error", applicable=True,
        evaluator_attempt_id="final-error-attempt", target_attempt_id=generation.attempt_id,
        rubric_version="rubric-v1", score=None, score_min=0.0, score_max=1.0,
    )
    errored = attempt(
        task_id, 3, route, cost="0.01", purpose="evaluation", parent=generation.attempt_id,
        evaluator_ref="judge", status="failed", validations=(error_outcome,),
    )
    record = task(task_id, attempts=(generation,), evaluator_attempts=(valid, errored))
    final_quality = analytics([record]).efficacy()["cohorts"][0]["quality"]
    assert final_quality == {
        "comparable": False, "reason": "no_comparable_evaluator_scores", "groups": []
    }


def test_quality_same_rubric_with_different_scale_is_not_comparable():
    records = []
    for task_id, maximum, score in (("scale-a", 1.0, 0.8), ("scale-b", 100.0, 80.0)):
        route = decision(task_id)
        generation = attempt(task_id, 1, route)
        outcome = ValidationOutcome(
            evaluation_id=f"{task_id}-result", check="quality", status="passed", applicable=True,
            evaluator_attempt_id=f"{task_id}-evaluator", target_attempt_id="local-target",
            rubric_version="same-version", score=score, score_min=0.0, score_max=maximum,
        )
        evaluator = attempt(
            task_id, 2, route, purpose="evaluation", parent="local-target",
            evaluator_ref="judge", validations=(outcome,),
        )
        records.append(task(task_id, attempts=(generation,), evaluator_attempts=(evaluator,)))
    quality = analytics(records).efficacy()["cohorts"][0]["quality"]
    assert quality["comparable"] is False
    assert quality["reason"] == "mixed_rubric_check_scale_or_role"
    assert len(quality["groups"]) == 2


def test_policy_model_and_family_cohorts_are_typed_and_small_samples_are_guarded():
    records = [
        task("a", policy="policy-a", model="luna", family="analysis"),
        task("b", policy="policy-b", model="terra", effort="high", family="coding"),
    ]
    service = analytics(records)
    assert [cohort["key"] for cohort in service.policies()["cohorts"]] == ["policy-a", "policy-b"]
    assert all(cohort["insufficient_sample"] for cohort in service.policies()["cohorts"])
    assert [cohort["key"] for cohort in service.models()["cohorts"]] == ["luna", "terra"]
    assert [cohort["key"] for cohort in service.task_families()["cohorts"]] == ["analysis", "coding"]


def test_synthetic_composition_is_isolated_and_meta_is_marked():
    production = task("production")
    demo = task("synthetic-demo-one", synthetic=True, policy="synthetic-demo-policy-a")
    demo_event = event("synthetic-demo-one", "TASK_SUCCEEDED", NOW - timedelta(minutes=1))
    production_view = Analytics((production, demo), (demo_event,), now=NOW, filters={}, synthetic=False).summary()
    assert production_view["metrics"]["total_tasks"] == 1
    assert production_view["meta"]["freshness"] is None
    synthetic = Analytics((production, demo), (demo_event,), now=NOW, filters={}, synthetic=True).summary()
    assert synthetic["metrics"]["total_tasks"] == 1
    assert synthetic["meta"]["synthetic"] is True
    assert synthetic["meta"]["freshness"] == "2026-09-06T11:59:00Z"
    assert synthetic["policy_versions"] == ["synthetic-demo-policy-a"]


def test_synthetic_provenance_falls_back_to_production_generation_attempt_route():
    task_id = "legacy-synthetic"
    route = decision(task_id, synthetic=True, policy="synthetic-demo-policy-a")
    record = task(task_id, synthetic=False, policy="synthetic-demo-policy-a")
    record = record.model_copy(update={
        "initial_decision": None,
        "decisions": (),
        "attempts": (attempt(task_id, 1, route),),
    })
    production = Analytics((record,), (), now=NOW, filters={}, synthetic=False)
    demo = Analytics((record,), (), now=NOW, filters={}, synthetic=True)
    assert production.summary()["metrics"]["total_tasks"] == 0
    assert demo.summary()["metrics"]["total_tasks"] == 1
    assert demo.routing()["models"] == [{"key": "luna", "count": 1, "share": 1.0}]


def test_utc_half_open_windows_nearest_rank_and_invalid_windows():
    eastern = timezone(timedelta(hours=-4))
    records = [
        task("one", created=datetime(2026, 9, 1, 20, tzinfo=eastern), updated=datetime(2026, 9, 1, 20, 0, 0, 10_000, tzinfo=eastern)),
        task("two", created=datetime(2026, 9, 2, tzinfo=UTC), updated=datetime(2026, 9, 2, 0, 0, 0, 20_000, tzinfo=UTC)),
        task("three", created=datetime(2026, 9, 3, tzinfo=UTC), updated=datetime(2026, 9, 3, 0, 0, 0, 30_000, tzinfo=UTC)),
    ]
    metrics = analytics(
        records, start=datetime(2026, 9, 2, tzinfo=UTC), end=datetime(2026, 9, 3, tzinfo=UTC)
    ).summary()["metrics"]
    # The first timestamp normalizes exactly to the inclusive UTC start; the third is at exclusive end.
    assert metrics["total_tasks"] == 2
    assert metrics["p50_latency_ms"] == 10.0
    assert metrics["p95_latency_ms"] == 20.0

    with pytest.raises(ValueError, match="timezone-aware"):
        Analytics((), (), now=NOW.replace(tzinfo=None), filters={})
    with pytest.raises(ValueError, match="start must be before end"):
        Analytics((), (), now=NOW, filters={"start": NOW, "end": NOW})
    with pytest.raises(ValueError, match="unsupported analytics filters"):
        Analytics((), (), now=NOW, filters={"role": "shadow"})


def test_money_aggregation_and_ratios_ignore_hostile_ambient_decimal_context():
    records = [task("large", cost="12345678901234567890.123456789"), task("tiny", cost="0.000000001")]
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.traps[Inexact] = True
        result = analytics(records).summary()["metrics"]

    assert result["cost"]["amount"] == "12345678901234567890.12345679"
    assert result["cost_per_task"]["amount"] == "6172839450617283945.061728395"


def test_every_analytics_envelope_validates_against_the_frozen_wire_models():
    service = analytics([task("wire")])
    Summary.model_validate(service.summary())
    Spend.model_validate(service.spend())
    Routing.model_validate(service.routing())
    Efficacy.model_validate(service.efficacy())
    Efficacy.model_validate(service.models())
    Efficacy.model_validate(service.task_families())
    Policies.model_validate(service.policies())
