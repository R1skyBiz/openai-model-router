"""Side-effect-free conservative cost planning for calibration runs."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Iterable, Mapping

from model_router.calibration.contracts import (
    BudgetPlan,
    CalibrationCase,
    EvaluatorConfig,
    ExperimentConfig,
)


class CalibrationPlanningError(ValueError):
    """The experiment cannot be assigned a complete finite cost bound."""


def _money_sum(*values: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 80
        return sum(values, Decimal("0"))


def _money_scale(value: Decimal, count: int) -> Decimal:
    with localcontext() as context:
        context.prec = 80
        return value * count


def _call_bound(
    model: Mapping,
    *,
    input_tokens: int,
    output_tokens: int,
) -> Decimal | None:
    """Return the worst standard-text tariff for one bounded invocation."""

    pricing = model.get("pricing", {})
    required = (
        pricing.get("unit_tokens"),
        pricing.get("input_usd"),
        pricing.get("cached_input_usd"),
        pricing.get("output_usd"),
        pricing.get("cache_write_input_multiplier"),
    )
    if any(value is None for value in required) or pricing.get("service_tier") != "standard":
        return None
    if (
        input_tokens > model.get("context_window_tokens", 0)
        or output_tokens > model.get("max_output_tokens", 0)
        or input_tokens + output_tokens > model.get("context_window_tokens", 0)
    ):
        return None
    long = pricing.get("long_context") or {}
    threshold = long.get("input_tokens_gt")
    long_request = isinstance(threshold, int) and input_tokens > threshold
    input_multipliers = [Decimal("1")]
    output_multiplier = Decimal("1")
    if long_request:
        values = (
            long.get("input_multiplier"),
            long.get("cached_input_multiplier"),
            long.get("cache_write_multiplier"),
            long.get("output_multiplier"),
        )
        if any(value is None for value in values):
            return None
        input_multipliers = [Decimal(str(value)) for value in values[:3]]
        output_multiplier = Decimal(str(values[3]))
    with localcontext() as context:
        context.prec = 80
        ordinary = Decimal(str(pricing["input_usd"]))
        cached = Decimal(str(pricing["cached_input_usd"]))
        write = ordinary * Decimal(str(pricing["cache_write_input_multiplier"]))
        input_rate = max(
            ordinary * input_multipliers[0],
            cached * input_multipliers[min(1, len(input_multipliers) - 1)],
            write * input_multipliers[min(2, len(input_multipliers) - 1)],
        )
        return (
            Decimal(input_tokens) * input_rate
            + Decimal(output_tokens) * Decimal(str(pricing["output_usd"])) * output_multiplier
        ) / Decimal(pricing["unit_tokens"])


def _evaluator_bound(binding: EvaluatorConfig | None, models: Mapping) -> Decimal | None:
    if binding is None:
        return Decimal("0")
    model = models.get(binding.model)
    if (
        model is None
        or not model.get("availability", {}).get("configured_enabled", False)
        or binding.effort.value not in model.get("reasoning_efforts", ())
        or model.get("capabilities", {}).get("text_input") is not True
        or model.get("capabilities", {}).get("text_output") is not True
        or model.get("capabilities", {}).get("structured_outputs") is not True
    ):
        return None
    return _call_bound(
        model,
        input_tokens=binding.max_input_tokens,
        output_tokens=binding.max_output_tokens,
    )


def plan_budget(
    cases: Iterable[CalibrationCase],
    config: ExperimentConfig,
    bundle,
    classifier_config=None,
) -> BudgetPlan:
    """Compute a conservative run-wide bound without invoking any provider."""

    materialized = tuple(cases)
    models = bundle.catalog["models"]
    blockers: list[str] = []
    maximum_generation_calls = 0
    maximum_classifier_calls = 0
    generation_total = Decimal("0")

    # input_overhead_tokens is consumed inside this exact serialized-input cap.
    max_input = config.max_input_tokens
    enabled = {
        alias: model
        for alias, model in models.items()
        if model.get("availability", {}).get("configured_enabled", False)
    }
    worst_router = [
        amount
        for model in enabled.values()
        if (amount := _call_bound(
            model, input_tokens=max_input, output_tokens=config.max_output_tokens
        )) is not None
    ]
    if enabled and len(worst_router) != len(enabled):
        blockers.append("generation_cost_unknown")
    router_bound = max(worst_router) if worst_router else None

    classifier_model = models.get(classifier_config.model_alias) if classifier_config is not None else None
    classifier_bound = None
    if (
        classifier_config is not None
        and classifier_model is not None
        and classifier_model.get("availability", {}).get("configured_enabled", False)
        and classifier_config.reasoning_effort.value in classifier_model.get("reasoning_efforts", ())
        and classifier_model.get("capabilities", {}).get("text_input") is True
        and classifier_model.get("capabilities", {}).get("structured_outputs") is True
    ):
        classifier_bound = _call_bound(
            classifier_model,
            input_tokens=max_input,
            output_tokens=classifier_config.max_output_tokens,
        )

    for strategy in config.strategies:
        attempts = config.max_generation_attempts if (
            strategy.kind == "router" and strategy.recovery_enabled
        ) else 1
        maximum_generation_calls += len(materialized) * attempts
        if strategy.kind == "router":
            maximum_classifier_calls += len(materialized)
            if router_bound is None:
                blockers.append("router_cost_unknown")
            else:
                generation_total = _money_sum(
                    generation_total, _money_scale(router_bound, len(materialized) * attempts)
                )
            if classifier_config is None or classifier_bound is None:
                blockers.append("classifier_cost_unknown")
            else:
                generation_total = _money_sum(
                    generation_total, _money_scale(classifier_bound, len(materialized))
                )
        else:
            model = models.get(strategy.model)
            bound = None if model is None else _call_bound(
                model, input_tokens=max_input, output_tokens=config.max_output_tokens
            )
            needs_structured = any(
                case.output_contract.format == "json" for case in materialized
            )
            if (model is None
                    or not model.get("availability", {}).get("configured_enabled", False)
                    or strategy.effort.value not in model.get("reasoning_efforts", ())
                    or model.get("capabilities", {}).get("text_input") is not True
                    or model.get("capabilities", {}).get("text_output") is not True
                    or (needs_structured and model.get("capabilities", {}).get("structured_outputs") is not True)):
                blockers.append("fixed_route_unsupported")
            elif bound is None:
                blockers.append("fixed_route_cost_unknown")
            else:
                generation_total = _money_sum(
                    generation_total, _money_scale(bound, len(materialized))
                )

    candidate_count = len(materialized) * len(config.strategies)
    primary_calls = (
        candidate_count * (config.evaluator.retries + 1)
        if config.evaluator is not None else 0
    )
    adjudications = 0
    if (config.adjudicator is not None and config.max_adjudications
            and config.adjudication_sample_rate > 0):
        # Bernoulli sampling can select every candidate; max_adjudications is
        # the only deterministic upper bound.
        adjudications = min(config.max_adjudications, candidate_count) * (
            config.adjudicator.retries + 1
        )
    evaluator_total = Decimal("0")
    primary_bound = _evaluator_bound(config.evaluator, models)
    adjudicator_bound = _evaluator_bound(config.adjudicator, models)
    if primary_calls and primary_bound is None:
        blockers.append("evaluator_cost_unknown")
    elif primary_bound is not None:
        evaluator_total = _money_sum(
            evaluator_total, _money_scale(primary_bound, primary_calls)
        )
    if adjudications and adjudicator_bound is None:
        blockers.append("adjudicator_cost_unknown")
    elif adjudicator_bound is not None:
        evaluator_total = _money_sum(
            evaluator_total, _money_scale(adjudicator_bound, adjudications)
        )

    blockers = list(dict.fromkeys(blockers))
    upper = None if blockers else _money_sum(generation_total, evaluator_total)
    admissible = upper is not None and upper <= config.aggregate_cap_usd
    if upper is not None and upper > config.aggregate_cap_usd:
        blockers.append("aggregate_cap_exceeded")
    return BudgetPlan(
        cases=len(materialized),
        strategies=len(config.strategies),
        maximum_generation_calls=maximum_generation_calls,
        maximum_classifier_calls=maximum_classifier_calls,
        maximum_evaluator_calls=primary_calls + adjudications,
        estimated_upper_bound_usd=upper,
        configured_cap_usd=config.aggregate_cap_usd,
        admissible=admissible,
        blockers=tuple(blockers),
    )


def plan_budget_with_classifier(cases, config, bundle, classifier_config) -> BudgetPlan:
    """Compatibility spelling for callers that emphasize classifier costs."""
    return plan_budget(cases, config, bundle, classifier_config)


__all__ = [
    "CalibrationPlanningError",
    "plan_budget",
    "plan_budget_with_classifier",
]
