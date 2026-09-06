from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import shutil

import pytest
import yaml

from model_router.core.configuration import PolicyBundle
from model_router.core.contracts import ConfigurationError
from model_router.policy.loader import bundle_from_documents, load_bundle


ROOT = Path(__file__).parents[1]


def documents():
    return {
        "policy": yaml.safe_load((ROOT / "config/routing-policy.yaml").read_text()),
        "catalog": yaml.safe_load((ROOT / "config/models.yaml").read_text()),
        "budgets": yaml.safe_load((ROOT / "config/budgets.yaml").read_text()),
        "validation": yaml.safe_load((ROOT / "config/validation.yaml").read_text()),
    }


def build(changes=None):
    docs = documents()
    if changes is not None:
        changes(docs)
    return bundle_from_documents(**docs)


def test_approved_bundle_is_deeply_immutable_and_uses_exact_money():
    bundle = load_bundle(ROOT / "config")

    assert isinstance(bundle.catalog["models"]["luna"]["pricing"]["input_usd"], Decimal)
    assert isinstance(bundle.policy["complexity_bands"], tuple)
    assert len(bundle.content_hash) == 64
    assert load_bundle(ROOT / "config").content_hash == bundle.content_hash
    with pytest.raises(TypeError):
        bundle.catalog["models"]["luna"] = {}
    with pytest.raises(TypeError):
        PolicyBundle({}, {}, {}, {}, "unvalidated")


def test_duplicate_yaml_key_is_rejected(tmp_path):
    for source in (ROOT / "config").glob("*.yaml"):
        shutil.copy(source, tmp_path / source.name)
    policy_path = tmp_path / "routing-policy.yaml"
    policy_path.write_text(policy_path.read_text() + "\nversion: duplicate\n")

    with pytest.raises(ConfigurationError, match="duplicate key"):
        load_bundle(tmp_path)


@pytest.mark.parametrize(
    "change",
    [
        lambda docs: docs["catalog"]["models"]["luna"].update(tier_rank=True),
        lambda docs: docs["policy"].update(schema_version=True),
        lambda docs: docs["policy"].update(autonomous_policy_updates=0),
        lambda docs: docs["catalog"]["models"]["luna"]["pricing"].update(input_usd=0.2),
        lambda docs: docs["catalog"]["models"]["luna"]["capabilities"].update(text_input=1),
    ],
)
def test_strict_scalars_reject_bool_integer_and_float_coercion(change):
    with pytest.raises(ConfigurationError):
        build(change)


def test_unknown_nested_fields_are_rejected():
    with pytest.raises(ConfigurationError, match="extra_forbidden"):
        build(lambda docs: docs["catalog"]["models"]["luna"]["pricing"].update(free_tokens=10))


def test_version_model_effort_and_rationale_references_are_checked():
    mutations = (
        lambda docs: docs["policy"].update(catalog_version="other"),
        lambda docs: docs["policy"]["complexity_bands"][0]["candidates"][0].update(model="missing"),
        lambda docs: docs["policy"]["complexity_bands"][0]["candidates"][0].update(efforts=["none", "none"]),
        lambda docs: docs["policy"]["task_family_floors"][0].update(rationale_codes=["NOT_REGISTERED"]),
    )
    for mutation in mutations:
        with pytest.raises(ConfigurationError):
            build(mutation)


def test_components_and_bands_must_match_contract_and_partition_total():
    with pytest.raises(ConfigurationError, match="complexity components must be exactly"):
        build(lambda docs: docs["policy"]["complexity"]["components"].update(extra={"min": 0, "max": 0}))
    with pytest.raises(ConfigurationError, match="partition"):
        build(lambda docs: docs["policy"]["complexity_bands"][1].update(min=22))


def test_budget_effective_floor_ceiling_and_period_pair_are_checked():
    def conflict(docs):
        docs["budgets"]["defaults"]["model_tier_floor"] = "L2"
        docs["budgets"]["applications"]["app"] = {"model_tier_ceiling": "L1"}

    with pytest.raises(ConfigurationError, match="floor exceeds ceiling"):
        build(conflict)
    with pytest.raises(ConfigurationError, match="incomplete aggregate period"):
        build(lambda docs: docs["budgets"]["applications"].update(app={"period": "day"}))


def test_validation_inheritance_cycles_and_profile_kinds_are_rejected():
    def cycle(docs):
        docs["validation"]["profiles"]["V1"]["base_profile"] = "V2"
        docs["validation"]["profiles"]["V2"]["base_profile"] = "V1"

    with pytest.raises(ConfigurationError, match="cycle"):
        build(cycle)
    with pytest.raises(ConfigurationError, match="V1 must be"):
        build(lambda docs: docs["validation"]["profiles"]["V1"].update(kind="strong_independent"))


def test_enabled_evaluator_requires_complete_supported_binding_and_scale():
    def configure(docs):
        docs["validation"]["evaluators"]["lightweight"].update(
            enabled=True,
            model_alias="luna",
            reasoning_effort="low",
            rubric_version="rubric-v1",
            score_scale={"min": 0, "max": 10},
            pass_threshold=8,
        )

    configured = build(configure)
    assert configured.validation["evaluators"]["lightweight"]["pass_threshold"] == 8.0

    with pytest.raises(ConfigurationError, match="complete binding"):
        build(lambda docs: docs["validation"]["evaluators"]["lightweight"].update(enabled=True))

    def unsupported(docs):
        configure(docs)
        docs["validation"]["evaluators"]["lightweight"]["model_alias"] = "astra"
        docs["validation"]["evaluators"]["lightweight"]["reasoning_effort"] = "none"

    with pytest.raises(ConfigurationError, match="unsupported reasoning effort"):
        build(unsupported)


def test_bundle_constructor_does_not_mutate_input_documents():
    docs = documents()
    before = deepcopy(docs)
    bundle_from_documents(**docs)
    assert docs == before
