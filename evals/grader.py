"""Compare supplied observations to independent envelopes. Never select a route."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from evals.schema import Case, Observation


def check_value(actual, op, expected):
    if op == "eq":
        # JSON boolean must never satisfy a numeric expectation.
        return type(actual) is type(expected) and actual == expected
    if op in ("contains", "excludes"):
        if not isinstance(actual, list):
            return False
        contained = any(type(item) is type(expected) and item == expected for item in actual)
        return contained if op == "contains" else not contained
    if isinstance(actual, bool) or not isinstance(actual, (int, float, str)):
        return False
    try:
        value, low, high = map(Decimal, map(str, [actual, *expected]))
        return value.is_finite() and low <= value <= high
    except (InvalidOperation, ValueError, TypeError):
        return False


def grade(case: Case, result: Observation, catalog: dict, policy_version: str,
          vocabulary: dict) -> list[str]:
    """Return all violations; an empty list is a pass. Catalog supplies facts only."""
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    exp = case.expected
    require(result.case_id == case.id, "case_id mismatch")
    require(result.policy_version == policy_version, "unpinned policy_version")
    require(set(result.rationale_codes) <= set(vocabulary["rationale_codes"]), "unknown rationale code")
    if result.classification:
        classified = result.classification
        require(classified.task_family in vocabulary["families"], "unknown task family")
        require(set(classified.flags) <= set(vocabulary["flags"]), "unknown classification flag")
        require(set(classified.components) == set(vocabulary["components"]), "component vocabulary")
        for name, value in classified.components.items():
            require(name in vocabulary["components"] and 0 <= value <= vocabulary["components"][name],
                    "component range")
    require(result.routing_result == exp.routing_result, "routing_result")
    require(result.execution_readiness == exp.execution_readiness, "execution_readiness")
    require(result.failure_type in exp.acceptable_failure_types if exp.acceptable_failure_types
            else result.failure_type == exp.expected_failure, "failure_type")
    require(set(exp.required_rationale_codes) <= set(result.rationale_codes), "required rationale missing")
    require(not set(exp.forbidden_rationale_codes) & set(result.rationale_codes), "forbidden rationale")

    if result.routing_result == "valid":
        model = catalog.get(result.selected_model_alias)
        require(model is not None, "unknown model")
        require(result.selected_model_alias not in exp.forbidden_models, "forbidden model")
        require(any(p.model == result.selected_model_alias and p.effort == result.reasoning_effort
                    for p in exp.acceptable_model_efforts), "model/effort outside envelope")
        require(result.validation_level == exp.validation_profile, "validation_profile")
        require(bool(result.rationale_codes), "empty rationale")
        require(result.estimated_cost is not None, "missing estimated_cost")
        if result.estimated_cost:
            require(result.estimated_cost.status == exp.cost_status, "cost_status")
            if result.estimated_cost.status != "known":
                require(result.execution_readiness == "blocked", "unknown cost cannot certify execution")
        if model:
            rank = model["tier_rank"]
            require(result.model_tier == rank, "model tier spoofing")
            require(result.reasoning_effort in model["reasoning_efforts"], "unsupported effort")
            require(exp.minimum_tier is None or rank >= exp.minimum_tier, "minimum_tier")
            require(exp.maximum_tier is None or rank <= exp.maximum_tier, "maximum_tier")
            require(all(model["capabilities"].get(c) is True for c in case.request.requirements),
                    "hard capability violation")
            ctx = case.request.context
            require(ctx.expected_output_tokens <= model["max_output_tokens"], "hard output limit")
            require(ctx.input_tokens + ctx.expected_output_tokens <= model["context_window_tokens"],
                    "hard combined context limit")
            # Check each independently supplied hard limit; no candidate selection or
            # floor matching is performed here. Looser caller limits cannot erase a bound.
            for limit in [case.request.constraints, case.environment.application_overlay]:
                if limit is None:
                    continue
                require(limit.model_tier_floor is None or rank >= limit.model_tier_floor,
                        "hard supplied tier floor")
                require(limit.model_tier_ceiling is None or rank <= limit.model_tier_ceiling,
                        "hard supplied tier ceiling")
                if result.execution_readiness == "ready":
                    require(limit.live_execution_enabled is not False, "disabled execution")
                    if limit.task_cost_ceiling_usd is not None and result.estimated_cost:
                        amount = result.estimated_cost.amount
                        require(amount is not None and Decimal(amount) <= Decimal(limit.task_cost_ceiling_usd),
                                "hard cost ceiling")
        require(result.classification == case.classification, "supplied classification changed")
    else:
        require(all(v is None for v in [result.selected_model_alias, result.model_tier,
                                       result.reasoning_effort, result.validation_level,
                                       result.estimated_cost]), "non-route fabricated route fields")

    if case.category == "classification":
        classified = result.classification
        require(classified is not None, "missing classification")
        if classified:
            require(set(classified.components) == set(exp.component_envelopes), "classification component keys")
            require(classified.task_family in exp.acceptable_task_families, "classification family")
            require(classified.task_family not in exp.forbidden_task_families, "forbidden family")
            for flag, value in exp.flags.items():
                require(classified.flags.get(flag) is value, f"classification flag {flag}")
            for name, (low, high) in exp.component_envelopes.items():
                value = classified.components.get(name)
                require(type(value) is int and low <= value <= high, f"classification component {name}")

    require(result.recovery == exp.expected_recovery, "ordered recovery trace")
    data = result.model_dump(mode="json")
    for check in exp.checks:
        current = data
        found = True
        for key in check.path.split("."):
            if not isinstance(current, dict) or key not in current:
                found = False
                break
            current = current[key]
        require(found and check_value(current, check.op, check.value), f"{check.path}: {check.why}")
    return errors
