"""Canonical deterministic, embedded route-only entry point. No network I/O."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json

from model_router.core.configuration import PolicyBundle
from model_router.core.contracts import (
    Candidate, Classification, ConfigurationError, EnvironmentSnapshot, FailureType,
    Feasibility, InputError, Request, RouteDecision, RouteRejection,
)
from model_router.policy.budgets import check_budget, resolve_limits
from model_router.policy.capabilities import check_capabilities
from model_router.policy.costs import estimate_cost
from model_router.policy.modifiers import build_candidates
from model_router.policy.validation import determine_validation


def _unique(values):
    return tuple(dict.fromkeys(values))


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                            default=lambda item: dict(item) if isinstance(item, Mapping) else str(item)).encode()).hexdigest()


def route(request: Request, classification: Classification,
          environment_snapshot: EnvironmentSnapshot, policy_bundle: PolicyBundle,
          *, recovery_candidates: tuple[Candidate, ...] | None = None
          ) -> RouteDecision | RouteRejection:
    """Select using supplied facts and immutable snapshots, never execute.

    Invalid contracts/configuration raise typed validation errors; expected
    capability/budget/availability impossibility returns RouteRejection. A valid
    preview can retain unresolved execution prerequisites and a null cost total.
    """
    if not isinstance(request, Request) or not isinstance(classification, Classification):
        raise InputError("route requires normalized Request and supplied Classification")
    if not isinstance(environment_snapshot, EnvironmentSnapshot):
        raise InputError("route requires an EnvironmentSnapshot")
    if not isinstance(policy_bundle, PolicyBundle):
        raise ConfigurationError("route requires a validated PolicyBundle")
    env, bundle = environment_snapshot, policy_bundle
    policy, catalog = bundle.policy, bundle.catalog
    if request.policy_version is not None and request.policy_version != policy["version"]:
        raise InputError("requested policy version differs from pinned bundle")
    if policy["selection"]["calibration_version"] is not None:
        raise ConfigurationError("calibrated selection is not implemented in Phase 1")
    unknown_models = set(env.models) - set(catalog["models"])
    if unknown_models:
        raise InputError("health snapshot refers to unknown model aliases")

    limits = resolve_limits(request, env, bundle)
    plan = build_candidates(classification, bundle, limits)
    if recovery_candidates is not None:
        if not recovery_candidates:
            raise InputError("recovery candidates cannot be empty")
        if any(c.model not in catalog["models"] or c.effort not in catalog["models"][c.model]["reasoning_efforts"]
               for c in recovery_candidates):
            raise InputError("unsupported recovery candidate")
        existing = {(c.model, c.effort) for c in plan.candidates}
        extras = tuple(c for c in recovery_candidates if (c.model, c.effort) not in existing)
        plan = plan.model_copy(update={"candidates": (*plan.candidates, *extras)})
    validation = determine_validation(request, env, bundle)
    codes = list(plan.rationale_codes)
    # There is no approved operational confidence cutoff. Record non-certainty
    # transparently without changing candidate order, effort, or model tier.
    if classification.confidence < 1:
        codes.append("LOW_CLASSIFIER_CONFIDENCE")
    if validation.level != bundle.validation["default_profile"] or validation.evaluator_required:
        codes.append("VALIDATION_REQUIRED")
    overlay_version = env.application_overlay_version
    if overlay_version is None and env.trusted_application_id in bundle.budgets["applications"]:
        overlay_version = f'{bundle.budgets["version"]}/{env.trusted_application_id}'
    config_hash = _digest([bundle.content_hash, overlay_version, limits.model_dump(mode="json")])
    decision_id = _digest([request.model_dump(mode="json"),
                           sha256(request.input.encode()).hexdigest(),
                           classification.model_dump(mode="json"),
                           env.model_dump(mode="json"), config_hash])
    if recovery_candidates is not None:
        decision_id = _digest([decision_id, [c.model_dump(mode="json") for c in recovery_candidates]])
    details = {
        "required_capabilities": request.requirements,
        "matched_rules": plan.matched_rules,
        "floors": tuple(f.model_dump(mode="json") for f in plan.floors),
        "floor_waiver_rules": (), "floor_waiver_constraints": (),
        "removed_candidates": (),
        "selection_method": policy["selection"]["cold_start"],
        "confidence_threshold": None,
        "latency_estimate": "unavailable" if env.minimum_next_action_ms is None else "supplied_bound",
    }

    bundle_pricing_version = "pricing-bundle-sha256:" + _digest({
        "currency": catalog["currency"],
        "models": {alias: model["pricing"] for alias, model in catalog["models"].items()},
        "evaluator_charge": env.required_evaluator_cost_usd,
        "domain_validator_charge": env.required_domain_validator_cost_usd,
        "tool_charge_required": env.required_tool_charge,
        "tool_charge": env.required_tool_charge_usd,
    })
    details["environment_pricing_reference"] = env.pricing_version

    def common(blockers=(), pricing_version=bundle_pricing_version):
        if set(codes) - set(policy["rationale_codes"]):
            raise ConfigurationError("emitted rationale code is absent from the pinned registry")
        return dict(
            task_id=request.task_id, trace_id=request.trace_id, decision_id=decision_id,
            policy_version=policy["version"], catalog_version=catalog["catalog_version"],
            pricing_version=pricing_version, budget_version=bundle.budgets["version"],
            validation_version=bundle.validation["version"], application_overlay_version=overlay_version,
            effective_configuration_hash=config_hash, classification=classification,
            complexity_score=classification.components.total, rationale_codes=_unique(codes),
            rationale_details=details, effective_limits=limits,
            environment_snapshot_id=env.snapshot_id, synthetic=env.synthetic,
            health_snapshot_id=env.health_snapshot_id, readiness_blockers=_unique(blockers),
        )

    def reject(failure, violations, retryable=False):
        codes[:] = [code for code in codes if code != "BASELINE_PRIOR"]
        if failure == FailureType.BUDGET_FAILURE:
            codes.append("APPLICATION_BUDGET_CAP")
        elif failure == FailureType.PROVIDER_FAILURE:
            codes.append("MODEL_DEGRADED")
        return RouteRejection(**common(), failure_type=failure,
                              violated_constraints=_unique(violations), retryable=retryable)

    # Capabilities precede budget admission. Cheap incapable models never count
    # as a way to fund a task, including when tier bounds also conflict.
    capability_results = {alias: check_capabilities(request, model)
                          for alias, model in catalog["models"].items()}
    for result in capability_results.values():
        codes.extend(result.rationale_codes)
    if not any(not result.violations for result in capability_results.values()):
        return reject(FailureType.CAPABILITY_FAILURE,
                      [v for result in capability_results.values() for v in result.violations])
    if (limits.model_tier_floor is not None and limits.model_tier_ceiling is not None
            and limits.model_tier_floor > limits.model_tier_ceiling):
        return reject(FailureType.BUDGET_FAILURE, ("floor_vs_ceiling",))
    if limits.model_tier_ceiling is not None and plan.hard_floor > limits.model_tier_ceiling:
        return reject(FailureType.BUDGET_FAILURE, ("hard_floor_vs_ceiling",))

    feasible, removed = [], []
    cache_miss_quotes = {}
    for candidate in plan.candidates:
        model = catalog["models"][candidate.model]
        violations = list(capability_results[candidate.model].violations)
        if model["tier_rank"] < max(plan.hard_floor, limits.model_tier_floor or 0):
            violations.append("model_tier_floor")
        if limits.model_tier_ceiling is not None and model["tier_rank"] > limits.model_tier_ceiling:
            violations.append("model_tier_ceiling")
        if candidate.effort not in model["reasoning_efforts"]:
            raise ConfigurationError("candidate uses unsupported model/effort pair")
        health = env.models.get(candidate.model)
        if (not model["availability"]["configured_enabled"] or
                health is not None and (health.state in policy["health"]["exclude_states"] or not health.usable
                                        or health.account_access == "unavailable")):
            violations.append("no_healthy_permitted_path")
        if health and (health.state != "HEALTHY" or not health.usable):
            if candidate.source != "fallback":
                codes.append("MODEL_DEGRADED")
        cost = estimate_cost(request, model, env, validation, currency=catalog["currency"])
        budget = check_budget(cost, limits, env)
        if cost.cache_read_tokens:
            # Evidence supports the expected quote; it does not guarantee a
            # future cache hit. Both outcomes must fit hard admission bounds.
            miss_context = request.context.model_copy(update={"cache_evidence": False})
            miss_request = request.model_copy(update={"context": miss_context})
            miss_cost = estimate_cost(miss_request, model, env, validation, currency=catalog["currency"])
            cache_miss_quotes[candidate.model] = miss_cost
            miss_budget = check_budget(miss_cost, limits, env)
            budget = Feasibility(
                violations=_unique((*budget.violations, *miss_budget.violations)),
                blockers=_unique((*budget.blockers, *miss_budget.blockers,
                                 *(("cache_miss_estimate_unavailable",) if miss_cost.status != "known" else ()))),
                rationale_codes=_unique((*budget.rationale_codes, *miss_budget.rationale_codes)),
            )
        violations.extend(budget.violations)
        if violations:
            removed.append({"model": candidate.model, "effort": candidate.effort.value,
                            "source": candidate.source, "constraints": _unique(violations)})
        else:
            feasible.append((candidate, cost, budget, health))
    details["removed_candidates"] = tuple(removed)
    details["cache_miss_budget_estimates"] = {
        alias: quote.model_dump(mode="json") for alias, quote in cache_miss_quotes.items()
    }
    if any(any(v in row["constraints"] for v in
               ("model_tier_ceiling", "model_tier_floor", "task_cost_ceiling_usd", "remaining_budget"))
           for row in removed):
        codes.append("APPLICATION_BUDGET_CAP")
    if not feasible:
        violations = _unique(v for row in removed for v in row["constraints"])
        # Availability takes precedence only when there is otherwise a permitted
        # path. This never disguises a capability or budget impossibility.
        if any(set(row["constraints"]) == {"no_healthy_permitted_path"} for row in removed):
            return reject(FailureType.PROVIDER_FAILURE, violations, retryable=True)
        budget_keys = {"task_cost_ceiling_usd", "remaining_budget", "model_tier_floor", "model_tier_ceiling"}
        if set(violations) & budget_keys:
            return reject(FailureType.BUDGET_FAILURE, violations)
        return reject(FailureType.CAPABILITY_FAILURE, violations or ("no_permitted_candidate",))

    # Prefer candidates that can certify their own price, funding, and account
    # access. Shared prerequisites (approval/evaluator bindings/deadline) never
    # cause a generation-tier jump. Keep a blocked preview if no certified path
    # remains, rather than pretending unknown charges or access are verified.
    funding_blockers = {"required_evaluator_budget", "required_domain_validator_budget", "required_tool_budget"}

    def candidate_blockers(item):
        candidate, cost, budget, health = item
        specific = [blocker for blocker in budget.blockers if blocker in funding_blockers]
        if "cache_miss_estimate_unavailable" in budget.blockers:
            specific.append("cache_miss_estimate_unavailable")
        if cost.status != "known":
            specific.extend(cost.unknown_charges or ("unknown_cost",))
        if health is None or health.account_access != "verified":
            specific.append("account_unknown")
        return _unique(specific)

    certified = [item for item in feasible if not candidate_blockers(item)]
    if certified:
        for candidate, cost, budget, health in feasible:
            specific = candidate_blockers((candidate, cost, budget, health))
            if specific:
                removed.append({"model": candidate.model, "effort": candidate.effort.value,
                                "source": candidate.source, "constraints": specific})
        if any(funding_blockers.intersection(item[2].blockers) for item in feasible):
            codes.append("APPLICATION_BUDGET_CAP")
        feasible = certified
        details["removed_candidates"] = tuple(removed)

    attainable_floor = max((f.min_tier for f in plan.floors if f.strength == "preferred"
                            and any(catalog["models"][item[0].model]["tier_rank"] >= f.min_tier
                                    for item in feasible)), default=plan.hard_floor)
    feasible = [item for item in feasible if catalog["models"][item[0].model]["tier_rank"] >= attainable_floor]
    waived = [f for f in plan.floors if f.strength == "preferred" and f.min_tier > attainable_floor]
    if waived:
        codes.append("FLOOR_RELAXED")
        details["floor_waiver_rules"] = tuple(f.rule_id for f in waived)
        # Include tier-ceiling evidence even when construction omitted
        # out-of-limit fallback pairs. Every preferred model is examined.
        blocked = [v for row in removed
                   if catalog["models"][row["model"]]["tier_rank"] > attainable_floor
                   for v in row["constraints"]]
        if limits.model_tier_ceiling is not None and plan.preferred_floor > limits.model_tier_ceiling:
            blocked.append("model_tier_ceiling")
        details["floor_waiver_constraints"] = _unique(blocked)
        if not blocked:
            raise ConfigurationError("preferred floor cannot be waived without blocking evidence")

    if recovery_candidates is not None:
        ordered = []
        for wanted in recovery_candidates:
            ordered.extend(item for item in feasible if
                           (item[0].model, item[0].effort) == (wanted.model, wanted.effort))
        if not ordered:
            wanted_pairs = {(c.model, c.effort.value) for c in recovery_candidates}
            violations = tuple(v for row in removed if (row["model"], row["effort"]) in wanted_pairs
                               for v in row["constraints"])
            if set(violations) & {"remaining_budget", "task_cost_ceiling_usd", "model_tier_ceiling"}:
                return reject(FailureType.BUDGET_FAILURE, violations)
            return reject(FailureType.PROVIDER_FAILURE if "no_healthy_permitted_path" in violations
                          else FailureType.CAPABILITY_FAILURE,
                          violations or ("recovery_candidate_not_permitted",), retryable=True)
        feasible = ordered

    # Non-prior traversal is a last resort. Degraded-but-usable prior candidates
    # may remain usable; prefer a healthy candidate within that same group.
    primary = [] if recovery_candidates is not None else [item for item in feasible if item[0].source != "fallback"]
    pool = primary or feasible
    healthy = [item for item in pool if item[3] is not None and item[3].state == "HEALTHY"]
    candidate, cost, budget, health = (healthy or pool)[0]
    model = catalog["models"][candidate.model]
    if health is not None and health.state == "DEGRADED":
        codes.append("MODEL_DEGRADED")
    if candidate.source != "prior":
        codes[:] = [code for code in codes if code != "BASELINE_PRIOR"]
        codes.append("CONSTRAINED_FALLBACK")
    if cost.long_context:
        codes.append("LONG_CONTEXT")
    if cost.status != "known":
        codes.append("ESTIMATE_UNAVAILABLE")
    codes.extend(budget.rationale_codes)
    blockers = list(validation.blockers) + list(budget.blockers)
    if health is None or health.account_access != "verified":
        blockers.append("account_unknown")
    if (env.health_valid_until is None or env.health_observed_at is None
            or env.health_observed_at > env.clock or env.health_valid_until <= env.clock):
        blockers.append("stale_snapshot")
    if not env.recovery_bounded:
        blockers.append("recovery_unconfigured")
    if not env.durable_retention:
        blockers.append("durable_retention_unavailable")
    if env.health_snapshot_id is None:
        blockers.append("health_snapshot_unversioned")
    if request.side_effecting_tool:
        blockers.append("side_effect_execution_unconfigured")
    if limits.period_spend_ceiling_usd is not None:
        blockers.append("period_budget_unverified")
    details["selected_source"] = candidate.source
    details["model_pricing_version"] = model["pricing"]["version"]
    return RouteDecision(
        **common(blockers, pricing_version=cost.pricing_version), selected_model_alias=candidate.model,
        provider_model_id=model["provider_model_id"], model_tier=model["tier_rank"],
        reasoning_effort=candidate.effort, validation_level=validation.level,
        validation_requirements=validation, estimated_cost=cost, executable=not blockers,
    )
