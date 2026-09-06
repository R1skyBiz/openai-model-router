"""Trusted budget overlay resolution and route budget feasibility."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Context, Decimal, MAX_EMAX, MIN_EMIN, localcontext
from typing import Any

from model_router.core.contracts import (
    CostEstimate,
    EnvironmentSnapshot,
    InputError,
    Limits,
    Request,
)


_LIMIT_FIELDS = tuple(Limits.model_fields)
_MIN_FIELDS = (
    "model_tier_ceiling",
    "task_cost_ceiling_usd",
    "task_deadline_ms",
    "period_spend_ceiling_usd",
)


def resolve_limits(request: Request, environment: EnvironmentSnapshot, bundle: Any) -> Limits:
    """Resolve configured defaults, trusted application policy, and caller bounds."""

    defaults = _normalize_limits(bundle.budgets.get("defaults", {}), bundle.catalog)

    if environment.synthetic:
        # Synthetic snapshots are the eval fixture's trusted deployment defaults.
        effective = _replace_present(defaults, environment.budget)
    else:
        effective = _tighten(defaults, environment.budget)

    configured_applications = bundle.budgets.get("applications", {})
    trusted_application_id = environment.trusted_application_id
    if trusted_application_id is not None and trusted_application_id in configured_applications:
        configured_overlay = _normalize_limits(
            configured_applications[trusted_application_id], bundle.catalog
        )
        effective = _tighten(effective, configured_overlay)

    if environment.application_overlay is not None:
        effective = _tighten(effective, environment.application_overlay)

    effective = _tighten(effective, request.constraints)
    _validate_period(effective)
    return effective


def check_budget(
    cost: CostEstimate, limits: Limits, environment: EnvironmentSnapshot
) -> "Feasibility":
    """Return hard budget exclusions separately from readiness blockers."""

    # Local import keeps this module's public input contract easy to inspect.
    from model_router.core.contracts import Feasibility

    violations: list[str] = []
    blockers: list[str] = []
    rationale_codes: list[str] = []

    if (
        limits.model_tier_floor is not None
        and limits.model_tier_ceiling is not None
        and limits.model_tier_floor > limits.model_tier_ceiling
    ):
        violations.append("floor_vs_ceiling")

    if cost.status == "known":
        assert cost.amount is not None
        if (
            limits.task_cost_ceiling_usd is not None
            and cost.amount > limits.task_cost_ceiling_usd
        ):
            violations.append("task_cost_ceiling_usd")
    else:
        blockers.extend(cost.unknown_charges or ("unknown_cost",))
        rationale_codes.append("ESTIMATE_UNAVAILABLE")
        if (
            limits.task_cost_ceiling_usd is not None
            and cost.known_subtotal > limits.task_cost_ceiling_usd
        ):
            violations.append("task_cost_ceiling_usd")

    remaining = environment.remaining_usd
    if remaining is not None:
        if cost.generation_subtotal > remaining:
            _append_once(violations, "remaining_budget")
        elif cost.known_subtotal > remaining:
            unfunded = _first_unfunded_charge(cost, remaining)
            if unfunded:
                _append_once(blockers, unfunded + "_budget")
            else:
                _append_once(violations, "remaining_budget")

    if limits.live_execution_enabled is not True:
        _append_once(blockers, "live_execution_disabled")

    if limits.task_cost_ceiling_usd is None:
        _append_once(blockers, "finite_task_cost_ceiling_required")

    deadline = limits.task_deadline_ms
    minimum_action = environment.minimum_next_action_ms
    if deadline is None:
        _append_once(blockers, "task_deadline_required")
    elif minimum_action is not None and minimum_action > deadline:
        _append_once(blockers, "deadline")

    return Feasibility(
        violations=tuple(violations),
        blockers=tuple(blockers),
        rationale_codes=tuple(rationale_codes),
    )


def _normalize_limits(values: Mapping[str, Any], catalog: Mapping[str, Any]) -> Limits:
    normalized = {name: values.get(name) for name in _LIMIT_FIELDS}
    for field in ("model_tier_floor", "model_tier_ceiling"):
        value = normalized[field]
        if isinstance(value, str):
            normalized[field] = _tier_rank(value, catalog)
    return Limits(**normalized)


def _tier_rank(tier: str, catalog: Mapping[str, Any]) -> int:
    ranks = {
        model["tier"]: model["tier_rank"]
        for model in catalog.get("models", {}).values()
    }
    try:
        return ranks[tier]
    except KeyError as error:
        raise InputError(f"unknown model tier {tier!r}") from error


def _replace_present(base: Limits, overlay: Limits) -> Limits:
    result = base.model_dump()
    for name in _LIMIT_FIELDS:
        value = getattr(overlay, name)
        if value is not None:
            result[name] = value
    return Limits(**result)


def _tighten(base: Limits, overlay: Limits) -> Limits:
    result = base.model_dump()

    floor = overlay.model_tier_floor
    if floor is not None:
        current = base.model_tier_floor
        result["model_tier_floor"] = floor if current is None else max(current, floor)

    for name in _MIN_FIELDS:
        incoming = getattr(overlay, name)
        if incoming is not None:
            current = getattr(base, name)
            result[name] = incoming if current is None else min(current, incoming)

    if overlay.period is not None:
        if base.period is not None and base.period != overlay.period:
            raise InputError("period changes require a versioned policy, not a tightening overlay")
        result["period"] = overlay.period

    if overlay.live_execution_enabled is not None:
        current = base.live_execution_enabled
        result["live_execution_enabled"] = (
            overlay.live_execution_enabled
            if current is None
            else current and overlay.live_execution_enabled
        )

    return Limits(**result)


def _validate_period(limits: Limits) -> None:
    if (limits.period_spend_ceiling_usd is None) != (limits.period is None):
        raise InputError("period spend ceiling and period must accompany each other")


def _first_unfunded_charge(cost: CostEstimate, remaining: Decimal) -> str | None:
    """Attribute the first crossing in generation/evaluator/domain/tool order.

    Use an independent, sufficiently wide context so a caller's Decimal
    precision and traps cannot change funding evidence.
    """
    names = ("required_evaluator", "required_domain_validator", "required_tool")
    values = [cost.generation_subtotal, remaining] + [
        cost.breakdown[name] for name in names if cost.breakdown.get(name) is not None
    ]
    precision = max(value.adjusted() for value in values) - min(
        value.as_tuple().exponent for value in values
    ) + len(values) + 2
    with localcontext(Context(prec=max(1, precision), Emin=MIN_EMIN, Emax=MAX_EMAX)):
        subtotal = cost.generation_subtotal
        for name in names:
            value = cost.breakdown.get(name)
            if value is not None:
                subtotal += value
                if subtotal > remaining:
                    return name
    return None


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
