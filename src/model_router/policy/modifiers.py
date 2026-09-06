"""Deterministic policy matching and ordered candidate construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from model_router.core.contracts import (
    Candidate,
    CandidatePlan,
    Classification,
    Effort,
    FloorEvidence,
    InputError,
    Limits,
)


def build_candidates(
    classification: Classification,
    bundle: Any,
    limits: Limits,
) -> CandidatePlan:
    """Match the pinned policy and return its finite, ordered candidate plan.

    The plan deliberately retains candidates that final feasibility checks may
    remove.  Only constrained fallback generation observes effective tier
    bounds, since those candidates exist specifically to explore permitted
    alternatives outside the baseline prior.
    """

    policy: Mapping[str, Any] = bundle.policy
    catalog: Mapping[str, Any] = bundle.catalog
    models: Mapping[str, Mapping[str, Any]] = catalog["models"]

    components = _validated_classification(classification, policy)
    model_order = tuple(models)
    tier_ranks = {name: _integer(models[name]["tier_rank"], "model tier rank") for name in model_order}
    enabled_models = tuple(
        name
        for name in model_order
        if models[name].get("availability", {}).get("configured_enabled", True)
    )
    minimum_rank = min(tier_ranks.values())

    band = _complexity_band(policy, sum(components.values()))
    prior_entries = tuple(band["candidates"])
    prior_models = {entry["model"] for entry in prior_entries}
    prior_ranks = tuple(tier_ranks[entry["model"]] for entry in prior_entries)
    prior_efforts = _stable_unique(
        effort for entry in prior_entries for effort in entry["efforts"]
    )

    candidates: list[Candidate] = []
    seen_pairs: set[tuple[str, Effort]] = set()
    floors: list[FloorEvidence] = []
    rationales: list[str] = ["BASELINE_PRIOR"]
    matched_rules: list[str] = []
    hard_floor = minimum_rank
    preferred_floor = minimum_rank

    def add_candidates(entries: Iterable[Mapping[str, Any]], source: str) -> None:
        for entry in entries:
            model_name = entry["model"]
            for effort_value in entry["efforts"]:
                effort = Effort(effort_value)
                key = (model_name, effort)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                candidates.append(Candidate(model=model_name, effort=effort, source=source))

    add_candidates(prior_entries, "prior")

    for rule in policy.get("task_family_floors", ()):
        if not _matches(rule["match"], classification, components):
            continue
        rule_id = rule["id"]
        strength = rule["strength"]
        rank = _tier_rank(rule["min_tier"], models)
        floors.append(FloorEvidence(rule_id=rule_id, strength=strength, min_tier=rank))
        matched_rules.append(rule_id)
        _extend_unique(rationales, rule.get("rationale_codes", ()))
        if strength == "hard":
            hard_floor = max(hard_floor, rank)
        else:
            preferred_floor = max(preferred_floor, rank)

    modifier_entries: list[Mapping[str, Any]] = []
    for rule in policy.get("modifiers", ()):
        if not _matches(rule["match"], classification, components):
            continue
        rule_id = rule["id"]
        matched_rules.append(rule_id)
        _extend_unique(rationales, rule.get("rationale_codes", ()))
        effect = rule["effect"]
        modifier_entries.extend(effect.get("add_candidates", ()))
        if effect.get("preferred_min_tier") is not None:
            rank = _tier_rank(effect["preferred_min_tier"], models)
            preferred_floor = max(preferred_floor, rank)
            floors.append(FloorEvidence(rule_id=rule_id, strength="preferred", min_tier=rank))

    add_candidates(modifier_entries, "modifier")

    limit_floor = limits.model_tier_floor
    applicable_floor = max(
        hard_floor,
        preferred_floor,
        minimum_rank if limit_floor is None else limit_floor,
    )
    floor_applies = bool(floors) or (limit_floor is not None and limit_floor > minimum_rank)
    effort_preference = tuple(policy["selection"]["floor_candidate_effort_preference"])
    if floor_applies:
        existing_models = {candidate.model for candidate in candidates}
        floor_entries = (
            {
                "model": name,
                "efforts": _supported_in_order(models[name], effort_preference),
            }
            for name in sorted(enabled_models, key=tier_ranks.__getitem__)
            if tier_ranks[name] >= applicable_floor and name not in existing_models
        )
        add_candidates(floor_entries, "floor")

    # A constrained alternative should stay as close as possible to the prior
    # tier.  Equidistant models retain the configured lower-to-higher rank order.
    fallback_models = (
        name
        for name in sorted(
            enabled_models,
            key=lambda item: (
                min(abs(tier_ranks[item] - prior_rank) for prior_rank in prior_ranks),
                tier_ranks[item],
            ),
        )
        if name not in prior_models and _within_limits(tier_ranks[name], limits)
    )
    fallback_entries = []
    for name in fallback_models:
        efforts = _supported_in_order(models[name], prior_efforts)
        if not efforts:
            efforts = _supported_in_order(models[name], effort_preference)
        fallback_entries.append({"model": name, "efforts": efforts})
    add_candidates(fallback_entries, "fallback")

    return CandidatePlan(
        candidates=tuple(candidates),
        floors=tuple(floors),
        rationale_codes=tuple(rationales),
        matched_rules=tuple(matched_rules),
        hard_floor=hard_floor,
        preferred_floor=preferred_floor,
    )


def _validated_classification(
    classification: Classification,
    policy: Mapping[str, Any],
) -> dict[str, int]:
    families = set(policy["task_families"])
    if classification.task_family not in families:
        raise InputError(f"unsupported task family: {classification.task_family}")
    if classification.task_subclass is not None:
        raise InputError(
            "task_subclass is unsupported because the pinned policy defines no subclass vocabulary"
        )

    configured_components: Mapping[str, Mapping[str, Any]] = policy["complexity"]["components"]
    supplied_names = tuple(type(classification.components).model_fields)
    if set(supplied_names) != set(configured_components):
        unsupported = sorted(set(supplied_names) - set(configured_components))
        missing = sorted(set(configured_components) - set(supplied_names))
        raise InputError(
            f"complexity component vocabulary mismatch: unsupported={unsupported}, missing={missing}"
        )

    values: dict[str, int] = {}
    for name in supplied_names:
        value = getattr(classification.components, name)
        bounds = configured_components[name]
        if value < bounds["min"] or value > bounds["max"]:
            raise InputError(
                f"complexity component {name}={value} outside configured range "
                f"[{bounds['min']}, {bounds['max']}]"
            )
        values[name] = value

    total = sum(values.values())
    complexity = policy["complexity"]
    if total < complexity["total_min"] or total > complexity["total_max"]:
        raise InputError(
            f"complexity total {total} outside configured range "
            f"[{complexity['total_min']}, {complexity['total_max']}]"
        )
    if classification.supplied_total is not None and classification.supplied_total != total:
        raise InputError("supplied complexity total does not equal independently calculated total")

    known_flags = {
        flag
        for rules in (policy.get("task_family_floors", ()), policy.get("modifiers", ()))
        for rule in rules
        for flag in rule["match"].get("flags_all", ())
    }
    unknown_flags = sorted(set(classification.flags) - known_flags)
    if unknown_flags:
        raise InputError(f"unsupported classification flags: {unknown_flags}")
    return values


def _complexity_band(policy: Mapping[str, Any], total: int) -> Mapping[str, Any]:
    for band in policy["complexity_bands"]:
        if band["min"] <= total <= band["max"]:
            return band
    raise InputError(f"complexity total {total} does not match a configured band")


def _matches(
    predicates: Mapping[str, Any],
    classification: Classification,
    components: Mapping[str, int],
) -> bool:
    if predicates.get("families") and classification.task_family not in predicates["families"]:
        return False
    if "flags_all" in predicates and not all(
        classification.flags.get(flag) is True for flag in predicates["flags_all"]
    ):
        return False
    if (
        predicates.get("complexity_min") is not None
        and sum(components.values()) < predicates["complexity_min"]
    ):
        return False
    if "component_min" in predicates and not all(
        components.get(name, -1) >= minimum
        for name, minimum in predicates["component_min"].items()
    ):
        return False
    return True


def _tier_rank(tier: str, models: Mapping[str, Mapping[str, Any]]) -> int:
    for model in models.values():
        if model["tier"] == tier:
            return _integer(model["tier_rank"], "model tier rank")
    raise InputError(f"policy references an unknown model tier: {tier}")


def _supported_in_order(model: Mapping[str, Any], ordered_efforts: Iterable[str]) -> tuple[str, ...]:
    supported = set(model["reasoning_efforts"])
    return tuple(effort for effort in ordered_efforts if effort in supported)


def _within_limits(rank: int, limits: Limits) -> bool:
    return (
        (limits.model_tier_floor is None or rank >= limits.model_tier_floor)
        and (limits.model_tier_ceiling is None or rank <= limits.model_tier_ceiling)
    )


def _stable_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _extend_unique(target: list[str], values: Iterable[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"{label} must be an integer")
    return value
