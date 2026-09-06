from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from model_router.core.contracts import Classification, ComplexityComponents, InputError, Limits
from model_router.policy.modifiers import build_candidates


ROOT = Path(__file__).resolve().parents[1]


def _bundle():
    with (ROOT / "config" / "routing-policy.yaml").open() as stream:
        policy = yaml.safe_load(stream)
    with (ROOT / "config" / "models.yaml").open() as stream:
        catalog = yaml.safe_load(stream)
    return SimpleNamespace(policy=policy, catalog=catalog)


def _classification(
    *,
    family: str = "analysis",
    subclass: str | None = None,
    values: tuple[int, ...] = (5, 4, 3, 3, 2, 1, 2),
    confidence: float = 0.95,
    flags: dict[str, bool] | None = None,
) -> Classification:
    return Classification(
        task_family=family,
        task_subclass=subclass,
        components=ComplexityComponents(
            reasoning_depth=values[0],
            step_dependency=values[1],
            context_synthesis=values[2],
            technical_precision=values[3],
            ambiguity=values[4],
            tool_orchestration=values[5],
            reliability_requirement=values[6],
        ),
        confidence=confidence,
        flags=flags or {},
        provenance="candidate-test",
        supplied_total=sum(values),
    )


def _routes(plan):
    return [(candidate.model, candidate.effort.value, candidate.source) for candidate in plan.candidates]


def test_high_prior_fallback_starts_at_nearest_permitted_tier():
    classification = _classification(
        family="agentic",
        values=(24, 19, 14, 15, 9, 3, 5),
    )

    plan = build_candidates(classification, _bundle(), Limits(model_tier_ceiling=2))

    assert _routes(plan) == [
        ("astra", "high", "prior"),
        ("astra", "xhigh", "prior"),
        ("sol", "high", "fallback"),
        ("sol", "xhigh", "fallback"),
        ("terra", "high", "fallback"),
        ("terra", "xhigh", "fallback"),
        ("luna", "high", "fallback"),
        ("luna", "xhigh", "fallback"),
    ]
    assert plan.matched_rules == ("precision", "multistep")
    assert plan.rationale_codes == (
        "BASELINE_PRIOR",
        "TECHNICAL_PRECISION_HIGH",
        "MULTISTEP",
    )


def test_fallback_reuses_prior_efforts_and_distance_ties_use_lower_rank():
    classification = _classification(
        values=(13, 11, 8, 10, 5, 0, 3),
    )

    plan = build_candidates(classification, _bundle(), Limits())

    assert _routes(plan) == [
        ("terra", "medium", "prior"),
        ("terra", "high", "prior"),
        ("luna", "medium", "fallback"),
        ("luna", "high", "fallback"),
        ("sol", "medium", "fallback"),
        ("sol", "high", "fallback"),
        ("astra", "medium", "fallback"),
        ("astra", "high", "fallback"),
    ]


def test_hard_and_preferred_floors_combine_and_preserve_rule_evidence():
    classification = _classification(
        family="coding",
        values=(8, 6, 4, 7, 2, 0, 3),
        flags={"substantive_implementation": True, "repository_wide": True},
    )

    plan = build_candidates(classification, _bundle(), Limits(model_tier_ceiling=1))

    assert plan.hard_floor == 1
    assert plan.preferred_floor == 2
    assert [(floor.rule_id, floor.strength, floor.min_tier) for floor in plan.floors] == [
        ("substantive_coding", "hard", 1),
        ("repository_wide_work", "preferred", 2),
    ]
    assert plan.matched_rules == ("substantive_coding", "repository_wide_work")
    assert plan.rationale_codes == ("BASELINE_PRIOR", "TASK_FAMILY_FLOOR")
    assert _routes(plan) == [
        ("luna", "low", "prior"),
        ("luna", "medium", "prior"),
        ("terra", "low", "prior"),
        ("terra", "medium", "prior"),
        ("sol", "medium", "floor"),
        ("sol", "high", "floor"),
        ("sol", "low", "floor"),
        ("sol", "xhigh", "floor"),
        ("sol", "max", "floor"),
        ("sol", "none", "floor"),
        ("astra", "medium", "floor"),
        ("astra", "high", "floor"),
        ("astra", "low", "floor"),
        ("astra", "xhigh", "floor"),
        ("astra", "max", "floor"),
    ]


def test_modifier_candidates_precede_fallback_and_duplicate_pairs_keep_first_source():
    classification = _classification(
        family="agentic",
        values=(20, 10, 10, 8, 5, 4, 4),
        flags={"exceptional_end_to_end": True},
    )

    plan = build_candidates(classification, _bundle(), Limits())

    assert _routes(plan) == [
        ("terra", "high", "prior"),
        ("sol", "medium", "prior"),
        ("astra", "high", "modifier"),
        ("astra", "xhigh", "modifier"),
        ("luna", "high", "fallback"),
        ("luna", "medium", "fallback"),
        ("astra", "medium", "fallback"),
    ]
    assert plan.matched_rules == ("exceptional_agentic",)
    assert plan.rationale_codes == ("BASELINE_PRIOR", "EXCEPTIONAL_AGENTIC")


def test_all_supplied_predicates_must_match_and_modifier_floor_is_evidence():
    classification = _classification(
        family="engineering",
        values=(13, 14, 6, 12, 4, 8, 3),
        flags={"multivariable": True, "repository_wide": True},
    )

    plan = build_candidates(classification, _bundle(), Limits())

    # repository_wide does not match because its family predicate also fails.
    assert plan.matched_rules == (
        "engineering_multivariable",
        "engineering_complex",
        "tools_heavy",
        "precision",
        "multistep",
    )
    assert [(item.rule_id, item.strength, item.min_tier) for item in plan.floors] == [
        ("engineering_multivariable", "preferred", 1),
        ("engineering_complex", "preferred", 2),
        ("tools_heavy", "preferred", 1),
    ]
    assert plan.preferred_floor == 2


def test_policy_values_drive_prior_and_floor_effort_order():
    bundle = _bundle()
    policy = deepcopy(bundle.policy)
    policy["complexity_bands"][0]["candidates"] = [{"model": "terra", "efforts": ["max"]}]
    policy["selection"]["floor_candidate_effort_preference"] = [
        "low",
        "none",
        "medium",
        "high",
        "xhigh",
        "max",
    ]
    configured = SimpleNamespace(policy=policy, catalog=bundle.catalog)

    prior_plan = build_candidates(_classification(), configured, Limits())
    floor_plan = build_candidates(
        _classification(
            family="coding",
            flags={"substantive_implementation": True},
        ),
        configured,
        Limits(),
    )

    assert _routes(prior_plan)[0] == ("terra", "max", "prior")
    floor_routes = _routes(floor_plan)
    assert floor_routes[:1] == [("terra", "max", "prior")]
    assert floor_routes[1:3] == [("sol", "low", "floor"), ("sol", "none", "floor")]


def test_default_minimum_limit_does_not_insert_floor_candidates():
    plan = build_candidates(_classification(), _bundle(), Limits(model_tier_floor=0))

    assert all(candidate.source != "floor" for candidate in plan.candidates)


def test_low_confidence_does_not_change_candidates_or_invent_a_rationale():
    normal = build_candidates(_classification(confidence=0.95), _bundle(), Limits())
    uncertain = build_candidates(_classification(confidence=0.0), _bundle(), Limits())

    assert uncertain.candidates == normal.candidates
    assert "LOW_CLASSIFIER_CONFIDENCE" not in uncertain.rationale_codes


@pytest.mark.parametrize(
    ("classification", "message"),
    [
        (_classification(family="unconfigured"), "unsupported task family"),
        (_classification(subclass="unconfigured"), "defines no subclass vocabulary"),
        (_classification(flags={"unconfigured": True}), "unsupported classification flags"),
        (
            _classification(values=(5, 4, 3, 16, 2, 1, 2)),
            "technical_precision=16 outside configured range",
        ),
    ],
)
def test_invalid_policy_vocabulary_and_ranges_raise_input_error(classification, message):
    with pytest.raises(InputError, match=message):
        build_candidates(classification, _bundle(), Limits())


def test_component_names_must_equal_the_configured_vocabulary():
    bundle = _bundle()
    policy = deepcopy(bundle.policy)
    policy["complexity"]["components"]["new_signal"] = {"min": 0, "max": 0}

    with pytest.raises(InputError, match="complexity component vocabulary mismatch"):
        build_candidates(
            _classification(),
            SimpleNamespace(policy=policy, catalog=bundle.catalog),
            Limits(),
        )
