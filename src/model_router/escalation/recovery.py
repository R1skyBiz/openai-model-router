"""Pure recovery policy selection for the Phase 3 execution orchestrator.

This module proposes one next action.  It does not execute work, reserve budget,
or bypass the router: generation targets must be routed and admitted again by
the orchestrator.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from model_router.core.configuration import PolicyBundle
from model_router.core.contracts import Effort, FailureType
from model_router.core.execution_contracts import (
    RecoveryAction,
    RecoveryContext,
    RouteTarget,
)


def choose_recovery(context: RecoveryContext, bundle: PolicyBundle) -> RecoveryAction:
    """Return the next bounded recovery proposal for a normalized failure.

    The bundle determines failure programs, model ranks, supported efforts, and
    effort preferences.  Runtime limits in ``context`` are authoritative for
    this task.  The returned target is only a proposal; the caller must route it
    through normal feasibility and budget admission.
    """

    failure_type = context.failure.failure_type
    original_failure = context.original_failure or failure_type
    escalation = bundle.policy["escalation"]

    if failure_type.value in escalation["terminal"]["failure_types"]:
        return _action(
            context,
            action="stop",
            failure=failure_type,
            original_failure=context.original_failure,
            reason="terminal_failure",
        )

    bounded = _bounded_stop(context, original_failure)
    if bounded is not None:
        return bounded

    if failure_type.value in escalation["quality"]["failure_types"]:
        return _quality_recovery(context, bundle)
    if failure_type.value in escalation["infrastructure"]["failure_types"]:
        return _infrastructure_recovery(context, bundle)
    if failure_type.value in escalation["tool"]["failure_types"]:
        return _tool_recovery(context)
    if failure_type.value in escalation["diagnostic"]["failure_types"]:
        return _action(
            context,
            action="diagnose",
            route=_current_route(context),
            reason="diagnosis_required",
        )

    # PolicyBundle validation makes the failure vocabulary exhaustive.  Keep a
    # fail-closed result for constructed test doubles or a future port mismatch.
    return _action(
        context,
        action="stop",
        failure=FailureType.UNKNOWN_FAILURE,
        original_failure=original_failure,
        reason="unsupported_failure_program",
    )


def _bounded_stop(
    context: RecoveryContext, original_failure: FailureType
) -> RecoveryAction | None:
    if context.remaining_usd <= 0:
        return _action(
            context,
            action="stop_budget",
            failure=FailureType.BUDGET_FAILURE,
            original_failure=original_failure,
            reason="remaining_budget_exhausted",
        )
    if context.elapsed_ms >= context.limits.max_elapsed_ms:
        return _action(
            context,
            action="stop_deadline",
            failure=FailureType.BUDGET_FAILURE,
            original_failure=original_failure,
            reason="recovery_deadline_exhausted",
        )
    return None


def _quality_recovery(context: RecoveryContext, bundle: PolicyBundle) -> RecoveryAction:
    if (
        context.counters.generation_attempts >= context.limits.max_total_generation_attempts
        or context.counters.quality_escalations >= context.limits.max_quality_escalations
    ):
        return _attempts_exhausted(context)

    current_model = context.decision.selected_model_alias
    model = _model(bundle, current_model)
    effort = _next_prior_effort(context, bundle, model)
    if effort is not None:
        return _action(
            context,
            action="increase_effort",
            route=RouteTarget(model=current_model, effort=effort),
            rationale_codes=("QUALITY_ESCALATION",),
            reason="configured_effort_step",
        )

    target = _next_tier_target(current_model, bundle)
    if target is not None:
        return _action(
            context,
            action="increase_tier",
            route=target,
            rationale_codes=("QUALITY_ESCALATION",),
            reason="configured_tier_step",
        )

    return _action(
        context,
        action="stop",
        failure=FailureType.CAPABILITY_FAILURE,
        original_failure=context.original_failure or FailureType.QUALITY_FAILURE,
        reason="no_higher_configured_tier",
    )


def _infrastructure_recovery(
    context: RecoveryContext, bundle: PolicyBundle
) -> RecoveryAction:
    if (
        context.counters.generation_attempts >= context.limits.max_total_generation_attempts
        or context.counters.infrastructure_retries
        >= context.limits.max_infrastructure_retries
    ):
        return _attempts_exhausted(context)

    current = context.decision.selected_model_alias
    health = context.environment.models.get(current)
    if health is not None and (
        not health.usable or health.state in {"DEGRADED", "UNHEALTHY"}
    ):
        fallback = _healthy_fallback(context, bundle)
        if fallback is None and (not health.usable or health.state == "UNHEALTHY"):
            return _action(
                context,
                action="recoverable_failure",
                reason="no_safe_infrastructure_fallback",
                rationale_codes=("INFRASTRUCTURE_RECOVERY",),
            )
        if fallback is not None:
            return _action(
                context,
                action="health_aware_fallback",
                route=fallback,
                reason="current_route_not_healthy",
                rationale_codes=("INFRASTRUCTURE_RECOVERY", "MODEL_DEGRADED"),
            )

    if not context.failure.retryable:
        return _action(context, action="recoverable_failure", reason="infrastructure_not_retryable",
                       rationale_codes=("INFRASTRUCTURE_RECOVERY",))
    if (
        context.failure.retry_after_ms is not None
        and context.failure.retry_after_ms > context.limits.max_backoff_ms
    ):
        return _action(
            context,
            action="recoverable_failure",
            reason="retry_after_exceeds_backoff_bound",
            rationale_codes=("INFRASTRUCTURE_RECOVERY",),
        )
    backoff_ms = _backoff_ms(context)
    if context.elapsed_ms + backoff_ms >= context.limits.max_elapsed_ms:
        return _action(
            context,
            action="stop_deadline",
            failure=FailureType.BUDGET_FAILURE,
            original_failure=context.original_failure or context.failure.failure_type,
            reason="backoff_exceeds_deadline",
        )
    return _action(
        context,
        action="retry_backoff",
        route=_current_route(context),
        backoff_ms=backoff_ms,
        reason="bounded_infrastructure_retry",
        rationale_codes=("INFRASTRUCTURE_RECOVERY",),
    )


def _tool_recovery(context: RecoveryContext) -> RecoveryAction:
    if context.counters.tool_recoveries >= context.limits.max_tool_recoveries:
        return _attempts_exhausted(context)

    call = context.tool_call
    if call is not None and call.side_effecting and not (
        call.idempotency_key or call.reconciliation_evidence
    ):
        return _action(
            context,
            action="stop_reconcile",
            reason="unsafe_side_effect_replay",
            rationale_codes=("TOOL_RECOVERY",),
        )
    if context.tool_retryable and call is not None:
        return _action(
            context,
            action="retry_tool",
            route=_current_route(context),
            original_failure=context.original_failure or FailureType.TOOL_FAILURE,
            reason="safe_tool_retry",
            rationale_codes=("TOOL_RECOVERY",),
        )
    if (
        context.alternate_authorized
        and call is not None
        and call.alternate_tool is not None
    ):
        return _action(
            context,
            action="alternate_tool",
            route=_current_route(context),
            reason="authorized_alternate_tool",
            rationale_codes=("TOOL_RECOVERY",),
        )
    return _action(
        context,
        action="recoverable_failure",
        reason="tool_recovery_unavailable",
        rationale_codes=("TOOL_RECOVERY",),
    )


def _next_prior_effort(
    context: RecoveryContext,
    bundle: PolicyBundle,
    model: Mapping[str, Any],
) -> Effort | None:
    score = context.decision.complexity_score
    configured: Sequence[str] = ()
    for band in bundle.policy["complexity_bands"]:
        if band["min"] <= score <= band["max"]:
            for candidate in band["candidates"]:
                if candidate["model"] == context.decision.selected_model_alias:
                    configured = candidate["efforts"]
                    break
            break

    catalog_order = tuple(Effort(value) for value in model["reasoning_efforts"])
    current = context.decision.reasoning_effort
    if current not in catalog_order:
        return None
    configured_efforts = {Effort(value) for value in configured}
    current_index = catalog_order.index(current)
    return next(
        (effort for effort in catalog_order[current_index + 1 :] if effort in configured_efforts),
        None,
    )


def _next_tier_target(current: str, bundle: PolicyBundle) -> RouteTarget | None:
    models = bundle.catalog["models"]
    current_rank = _model(bundle, current)["tier_rank"]
    candidates = sorted(
        (
            (alias, model)
            for alias, model in models.items()
            if model["tier_rank"] > current_rank
            and model["availability"].get("configured_enabled", True)
        ),
        key=lambda item: item[1]["tier_rank"],
    )
    for alias, model in candidates:
        effort = _preferred_effort(model, bundle)
        if effort is not None:
            return RouteTarget(model=alias, effort=effort)
    return None


def _healthy_fallback(
    context: RecoveryContext, bundle: PolicyBundle
) -> RouteTarget | None:
    models = bundle.catalog["models"]
    current = context.decision.selected_model_alias
    current_rank = _model(bundle, current)["tier_rank"]
    minimum_rank = _minimum_permitted_rank(context)
    excluded_states = set(bundle.policy["health"]["exclude_states"])
    candidates = sorted(
        (
            (alias, model)
            for alias, model in models.items()
            if alias != current
            and minimum_rank <= model["tier_rank"] <= current_rank
            and model["availability"].get("configured_enabled", True)
        ),
        key=lambda item: item[1]["tier_rank"],
        reverse=True,
    )
    for alias, model in candidates:
        health = context.environment.models.get(alias)
        if health is None or not health.usable or health.state in excluded_states:
            continue
        supported = {Effort(value) for value in model["reasoning_efforts"]}
        effort = context.decision.reasoning_effort
        if effort not in supported:
            effort = _preferred_effort(model, bundle)
        if effort is not None:
            return RouteTarget(model=alias, effort=effort)
    return None


def _minimum_permitted_rank(context: RecoveryContext) -> int:
    floor = context.decision.effective_limits.model_tier_floor or 0
    details = context.decision.rationale_details
    for evidence in details.get("floors", ()):
        if evidence.get("strength") == "hard":
            floor = max(floor, int(evidence["min_tier"]))
    return floor


def _preferred_effort(
    model: Mapping[str, Any], bundle: PolicyBundle
) -> Effort | None:
    supported = set(model["reasoning_efforts"])
    for value in bundle.policy["selection"]["floor_candidate_effort_preference"]:
        if value in supported:
            return Effort(value)
    return None


def _backoff_ms(context: RecoveryContext) -> int:
    exponent = context.counters.infrastructure_retries
    initial = context.limits.initial_backoff_ms
    maximum = context.limits.max_backoff_ms
    if initial == 0 or maximum == 0:
        computed = 0
    else:
        saturation_exponent = (maximum // initial).bit_length()
        computed = (
            maximum
            if exponent >= saturation_exponent
            else min(initial * (2**exponent), maximum)
        )
    retry_after = context.failure.retry_after_ms
    if retry_after is not None:
        computed = max(computed, retry_after)
    return computed


def _attempts_exhausted(context: RecoveryContext) -> RecoveryAction:
    return _action(
        context,
        action="stop_attempts",
        failure=FailureType.BUDGET_FAILURE,
        original_failure=context.original_failure or context.failure.failure_type,
        reason="recovery_attempts_exhausted",
    )


def _current_route(context: RecoveryContext) -> RouteTarget:
    return RouteTarget(
        model=context.decision.selected_model_alias,
        effort=context.decision.reasoning_effort,
    )


def _model(bundle: PolicyBundle, alias: str) -> Mapping[str, Any]:
    try:
        return bundle.catalog["models"][alias]
    except KeyError as exc:
        raise ValueError(f"route refers to unknown model alias: {alias}") from exc


def _action(
    context: RecoveryContext,
    *,
    action: str,
    reason: str,
    failure: FailureType | None = None,
    original_failure: FailureType | None = None,
    route: RouteTarget | None = None,
    rationale_codes: tuple[str, ...] = (),
    backoff_ms: int = 0,
) -> RecoveryAction:
    return RecoveryAction(
        action=action,
        failure=context.failure.failure_type if failure is None else failure,
        original_failure=(
            context.original_failure if original_failure is None else original_failure
        ),
        route=route,
        validated=context.validated,
        backoff_ms=backoff_ms,
        rationale_codes=rationale_codes,
        reason=reason,
    )
