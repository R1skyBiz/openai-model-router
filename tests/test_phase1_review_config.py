from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from model_router.core.contracts import ConfigurationError, RationaleCode
from model_router.policy.loader import bundle_from_documents


ROOT = Path(__file__).parents[1]


def documents():
    return {
        "policy": yaml.safe_load((ROOT / "config/routing-policy.yaml").read_text()),
        "catalog": yaml.safe_load((ROOT / "config/models.yaml").read_text()),
        "budgets": yaml.safe_load((ROOT / "config/budgets.yaml").read_text()),
        "validation": yaml.safe_load((ROOT / "config/validation.yaml").read_text()),
    }


def build(change=None):
    docs = documents()
    if change is not None:
        change(docs)
    return bundle_from_documents(**docs)


def test_registry_must_describe_every_runtime_rationale_code():
    code = next(iter(RationaleCode)).value

    with pytest.raises(ConfigurationError, match="registry is missing runtime codes"):
        build(lambda docs: docs["policy"]["rationale_codes"].pop(code))


def test_derived_effort_order_must_support_every_enabled_model():
    with pytest.raises(ConfigurationError, match="no supported effort for enabled model astra"):
        build(lambda docs: docs["policy"]["selection"].update(floor_candidate_effort_preference=["none"]))


@pytest.mark.parametrize(
    "section,field",
    [
        ("policy", "include_in_estimate"),
        ("budgets", "include_costs"),
    ],
)
def test_required_cost_accounting_vocabularies_cannot_be_subsets(section, field):
    def remove_bucket(docs):
        target = docs[section]["context"] if section == "policy" else docs[section]["defaults"]
        target[field] = target[field][:-1]

    with pytest.raises(ConfigurationError, match="every required v1"):
        build(remove_bucket)


def test_domain_validator_reference_requires_later_phase_registry():
    with pytest.raises(ConfigurationError, match="domain validator bindings require later-phase registry"):
        build(lambda docs: docs["validation"]["profiles"]["V3"].update(validator_ref="domain-checker-v1"))


@pytest.mark.parametrize("field", ["evaluator_error_is_quality_failure", "always_evaluate_every_task"])
@pytest.mark.parametrize("value", [True, 0])
def test_evaluator_boundary_safety_flags_require_boolean_false(field, value):
    def mutate(docs):
        docs["validation"]["evaluator_boundary"][field] = value

    with pytest.raises(ConfigurationError):
        build(mutate)


def test_bundle_mapping_blocks_dict_bypass_without_changing_deterministic_hash():
    first = build()

    with pytest.raises(TypeError):
        dict.__setitem__(first.policy, "version", "mutated")
    assert first.policy["version"] == "router-v1.0.0"
    assert first.content_hash == build().content_hash


def test_bundle_hash_is_independent_of_mapping_insertion_order():
    docs = documents()
    docs["catalog"]["models"] = dict(reversed(tuple(docs["catalog"]["models"].items())))
    docs["policy"]["rationale_codes"] = dict(
        reversed(tuple(docs["policy"]["rationale_codes"].items()))
    )

    assert bundle_from_documents(**docs).content_hash == build().content_hash


def activate_documents(docs):
    docs["policy"]["status"] = "active"
    docs["catalog"]["status"] = "active"
    docs["budgets"]["status"] = "active"
    docs["validation"]["status"] = "active"
    docs["budgets"]["defaults"]["live_execution_enabled"] = True


def test_active_live_bundle_requires_static_task_bounds_then_bounded_recovery():
    with pytest.raises(ConfigurationError, match="finite task cost ceiling and deadline"):
        build(activate_documents)

    def task_bounds_only(docs):
        activate_documents(docs)
        docs["budgets"]["defaults"]["task_cost_ceiling_usd"] = "1.00"
        docs["budgets"]["defaults"]["task_deadline_ms"] = 30_000

    with pytest.raises(ConfigurationError, match="bounded recovery counters and backoff"):
        build(task_bounds_only)

    def fully_bounded(docs):
        task_bounds_only(docs)
        limits = docs["policy"]["escalation"]["limits"]
        limits.update(
            max_total_generation_attempts=3,
            max_quality_escalations=1,
            max_infrastructure_retries=1,
            max_tool_recoveries=0,
            max_elapsed_ms=30_000,
        )
        docs["policy"]["escalation"]["infrastructure"]["backoff"].update(
            initial_ms=100,
            max_ms=1_000,
            jitter=0.1,
        )

    assert build(fully_bounded).budgets["defaults"]["live_execution_enabled"] is True


def test_application_cannot_enable_globally_disabled_execution():
    def enabled_application(docs):
        activate_documents(docs)
        docs["budgets"]["defaults"]["live_execution_enabled"] = False
        docs["budgets"]["applications"]["live-app"] = {"live_execution_enabled": True}

    assert build(enabled_application).budgets["defaults"]["live_execution_enabled"] is False


def test_active_live_model_requires_known_base_prices():
    def unpriced(docs):
        activate_documents(docs)
        docs["budgets"]["defaults"].update(task_cost_ceiling_usd="10", task_deadline_ms=30000)
        docs["catalog"]["models"]["luna"]["pricing"]["input_usd"] = None

    with pytest.raises(ConfigurationError, match="known base input/output prices"):
        build(unpriced)


def test_active_policy_cannot_reference_unactivated_documents():
    with pytest.raises(ConfigurationError, match="active referenced snapshots"):
        build(lambda docs: docs["policy"].update(status="active"))


def test_profile_cannot_understate_its_inherited_validation_level():
    with pytest.raises(ConfigurationError, match="cannot inherit a stronger level"):
        build(lambda docs: docs["validation"]["profiles"]["V1"].update(base_profile="V2"))
