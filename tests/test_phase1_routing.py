"""Embedded routing behavior beyond acceptable-envelope grading."""

from copy import deepcopy
from decimal import Decimal, Inexact, ROUND_DOWN, localcontext
from pathlib import Path

import pytest
import yaml

from model_router.core.contracts import (
    Classification, EnvironmentSnapshot, InputError, Request,
    RouteDecision, RouteRejection,
)
from model_router.policy.loader import bundle_from_documents, load_bundle
from model_router.router import route


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bundle():
    return load_bundle(ROOT / "config")


def request(**updates):
    data = dict(task_id="example", trace_id="trace", input="input-content-sentinel", consequence="low",
                requirements=("text_input", "text_output"),
                context={"input_tokens": 1000, "expected_output_tokens": 1000})
    data.update(updates)
    return Request(**data)


def classification(**updates):
    data = dict(task_family="analysis", components=dict(reasoning_depth=13, step_dependency=11,
        context_synthesis=8, technical_precision=10, ambiguity=5, tool_orchestration=0,
        reliability_requirement=3), confidence=0.95, provenance="integration-v1")
    data.update(updates)
    return Classification(**data)


def environment(bundle, **updates):
    data = dict(snapshot_id="mock-v1", synthetic=True, clock="2026-09-06T20:00:00Z",
        pricing_version="mock-price-v1", health_snapshot_id="health-v1",
        health_observed_at="2026-09-06T19:59:00Z", health_valid_until="2026-09-06T20:05:00Z",
        models={alias: {"state": "HEALTHY", "account_access": "verified"} for alias in bundle.catalog["models"]},
        budget={"live_execution_enabled": True, "task_cost_ceiling_usd": "10", "task_deadline_ms": 30000},
        remaining_usd="10", validation={"V0": "configured_mock"}, recovery_bounded=True, durable_retention=True)
    data.update(updates)
    return EnvironmentSnapshot(**data)


def test_deterministic_route_has_correlated_pinned_evidence(bundle):
    req, cl, env = request(), classification(), environment(bundle)
    result = route(req, cl, env, bundle)
    assert isinstance(result, RouteDecision)
    assert (result.selected_model_alias, result.reasoning_effort) == ("terra", "medium")
    assert result.executable
    assert result == route(req, cl, env, bundle)
    assert result.model_dump_json() == route(req, cl, env, bundle).model_dump_json()
    assert result.complexity_score == 50
    assert result.task_id == req.task_id and result.trace_id == req.trace_id
    assert result.catalog_version == bundle.catalog["catalog_version"]
    assert result.pricing_version == result.estimated_cost.pricing_version
    assert result.rationale_details["environment_pricing_reference"] == env.pricing_version
    assert result.estimated_cost.model_pricing_version == bundle.catalog["models"][result.selected_model_alias]["pricing"]["version"]
    assert result.estimated_cost.token_assumptions == req.context
    assert "input-content-sentinel" not in result.model_dump_json()
    with pytest.raises(TypeError):
        result.rationale_details["matched_rules"] = ()


def test_changed_health_snapshot_changes_decision_identifier(bundle):
    first = route(request(), classification(), environment(bundle), bundle)
    second = route(request(), classification(), environment(bundle, health_snapshot_id="health-v2"), bundle)
    assert first.decision_id != second.decision_id


def test_unknown_policy_or_snapshot_model_is_typed_input_error(bundle):
    with pytest.raises(InputError):
        route(request(policy_version="unknown-version"), classification(), environment(bundle), bundle)
    with pytest.raises(InputError):
        route(request(), classification(), environment(bundle, models={"unknown-alias": {"state": "HEALTHY"}}), bundle)
    with pytest.raises(InputError):
        route(request(), None, environment(bundle), bundle)


@pytest.mark.parametrize("update", [
    {"task_family": "unknown-family"}, {"flags": {"choose_model": True}}, {"task_subclass": "unconfigured-subclass"},
    {"components": dict(reasoning_depth=26, step_dependency=0, context_synthesis=0, technical_precision=0,
                        ambiguity=0, tool_orchestration=0, reliability_requirement=0)},
])
def test_classification_vocabulary_and_policy_ranges_are_checked(bundle, update):
    with pytest.raises(InputError):
        route(request(), classification(**update), environment(bundle), bundle)


def test_required_validation_strengthening_preserves_independent_profiles(bundle):
    result = route(request(consequence="high", requested_validation="V3"), classification(), environment(bundle), bundle)
    assert result.validation_level == "V3"
    assert {"V0", "V2", "V3"} <= set(result.validation_requirements.profiles)
    assert "evaluator_unconfigured" in result.readiness_blockers
    assert "domain_validator_unconfigured" in result.readiness_blockers
    assert result.selected_model_alias == "terra"
    assert not result.executable and result.estimated_cost.amount is None


def test_consequence_and_confidence_never_change_generation_choice(bundle):
    env = environment(bundle)
    baseline = route(request(), classification(confidence=1.0), env, bundle)
    uncertain = route(request(), classification(confidence=0.01), env, bundle)
    consequential = route(request(consequence="critical"), classification(confidence=1.0), env, bundle)
    assert {(r.selected_model_alias, r.reasoning_effort) for r in (baseline, uncertain, consequential)} == {("terra", "medium")}
    assert "LOW_CLASSIFIER_CONFIDENCE" in uncertain.rationale_codes
    assert consequential.validation_level == "V3" and not consequential.executable


def test_known_validation_funding_reselects_a_complete_affordable_path(bundle):
    env = environment(bundle, remaining_usd="0.02", validation={"V0": "configured_mock", "V1": "configured_mock"},
                      required_evaluator_cost_usd="0.01")
    result = route(request(consequence="moderate"), classification(), env, bundle)
    assert result.selected_model_alias == "luna"
    assert result.executable
    assert "CONSTRAINED_FALLBACK" in result.rationale_codes
    assert str(result.estimated_cost.amount) == "0.0114"


def test_quotes_do_not_inherit_callers_decimal_arithmetic(bundle):
    req, cl, env = request(), classification(), environment(bundle)
    expected = route(req, cl, env, bundle)
    with localcontext() as caller_context:
        caller_context.prec = 2
        caller_context.Emax = 2
        caller_context.rounding = ROUND_DOWN
        caller_context.traps[Inexact] = True
        actual = route(req, cl, env, bundle)
    assert actual == expected


def test_verified_primary_is_preferred_to_unknown_account_preview(bundle):
    cl = classification(components=dict(reasoning_depth=5, step_dependency=5, context_synthesis=5,
                        technical_precision=5, ambiguity=1, tool_orchestration=0, reliability_requirement=0))
    models = environment(bundle).model_dump()["models"]
    models["luna"]["account_access"] = "unknown"
    result = route(request(), cl, environment(bundle, models=models), bundle)
    assert (result.selected_model_alias, result.reasoning_effort) == ("terra", "low")
    assert result.executable
    assert "CONSTRAINED_FALLBACK" not in result.rationale_codes
    assert any("account_unknown" in row["constraints"] for row in result.rationale_details["removed_candidates"])


def test_fully_priced_alternative_precedes_unknown_cache_preview(bundle):
    req = request(context={"input_tokens": 300000, "expected_output_tokens": 1000,
                           "cached_input_tokens": 10000, "cache_evidence": True})
    cl = classification(components=dict(reasoning_depth=5, step_dependency=5, context_synthesis=5,
                        technical_precision=5, ambiguity=1, tool_orchestration=0, reliability_requirement=0))
    result = route(req, cl, environment(bundle), bundle)
    assert result.selected_model_alias == "astra"
    assert result.executable and result.estimated_cost.status == "known"
    assert "BASELINE_PRIOR" not in result.rationale_codes
    assert "CONSTRAINED_FALLBACK" in result.rationale_codes
    assert any("long_context_cache_read" in row["constraints"]
               for row in result.rationale_details["removed_candidates"])


def test_quote_identifier_tracks_actual_rates_and_not_an_environment_label(bundle):
    req, cl = request(), classification()
    first = route(req, cl, environment(bundle, pricing_version="unverified-label-A"), bundle)
    relabeled = route(req, cl, environment(bundle, pricing_version="unverified-label-Z"), bundle)
    assert first.pricing_version == relabeled.pricing_version
    assert first.pricing_version == first.estimated_cost.pricing_version
    assert first.pricing_version.startswith("quote-sha256:")
    documents = [yaml.safe_load((ROOT / "config" / name).read_text()) for name in
                 ("routing-policy.yaml", "models.yaml", "budgets.yaml", "validation.yaml")]
    documents[1]["models"]["terra"]["pricing"]["input_usd"] = "3.00"
    changed = bundle_from_documents(*documents)
    requoted = route(req, cl, environment(changed), changed)
    assert first.estimated_cost.model_pricing_version == requoted.estimated_cost.model_pricing_version
    assert first.pricing_version != requoted.pricing_version
    assert first.estimated_cost.amount != requoted.estimated_cost.amount


def test_domain_cost_requires_its_own_explicit_fact(bundle):
    req = request(consequence="critical", approval_evidence=True, domain_clearance_evidence=True)
    env = environment(bundle, validation={"V0": "configured_mock", "V3": "configured_mock"},
                      required_evaluator_cost_usd="0")
    result = route(req, classification(), env, bundle)
    assert "required_domain_validator" in result.estimated_cost.unknown_charges
    assert result.estimated_cost.amount is None and not result.executable
    env = EnvironmentSnapshot(**{**env.model_dump(), "required_domain_validator_cost_usd": "0"})
    funded = route(req, classification(), env, bundle)
    assert funded.executable and funded.estimated_cost.status == "known"
    assert funded.synthetic


def test_side_effects_never_claim_ready_before_execution_authorization_exists(bundle):
    result = route(request(side_effecting_tool=True), classification(), environment(bundle), bundle)
    assert "side_effect_execution_unconfigured" in result.readiness_blockers
    assert "required_tool" in result.estimated_cost.unknown_charges
    assert not result.executable


def test_partial_quote_still_reports_known_required_funding_shortfall(bundle):
    env = environment(bundle, required_evaluator_cost_usd="0.05", required_tool_charge=True,
                      remaining_usd="0.02", validation={"V0": "configured_mock", "V1": "configured_mock"})
    result = route(request(consequence="moderate"), classification(), env, bundle)
    assert result.estimated_cost.status == "partial"
    assert "required_evaluator_budget" in result.readiness_blockers
    assert "required_tool" in result.estimated_cost.unknown_charges
    assert not result.executable


def test_required_funding_identifies_the_charge_that_exceeds_remaining(bundle):
    env = environment(bundle, required_evaluator_cost_usd="0.001",
                      required_domain_validator_cost_usd="0.010", remaining_usd="0.012",
                      validation={"V0": "configured_mock", "V2": "configured_mock", "V3": "configured_mock"})
    req = request(consequence="critical", requested_validation="V2",
                  approval_evidence=True, domain_clearance_evidence=True)
    cl = classification(components=dict(reasoning_depth=5, step_dependency=5, context_synthesis=1,
                        technical_precision=0, ambiguity=0, tool_orchestration=0, reliability_requirement=0))
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = True
        result = route(req, cl, env, bundle)
    assert result.selected_model_alias == "luna"
    assert "required_domain_validator_budget" in result.readiness_blockers
    assert "required_evaluator_budget" not in result.readiness_blockers
    assert not result.executable


def test_selected_degraded_fallback_carries_health_rationale():
    docs = [yaml.safe_load((ROOT / "config" / name).read_text()) for name in
            ("routing-policy.yaml", "models.yaml", "budgets.yaml", "validation.yaml")]
    docs[1]["models"]["astra"]["capabilities"]["audio_input"] = True
    changed = bundle_from_documents(*docs)
    states = {alias: {"state": "HEALTHY", "account_access": "verified"}
              for alias in changed.catalog["models"]}
    states["astra"]["state"] = "DEGRADED"
    result = route(request(requirements=("audio_input", "text_output")), classification(),
                   environment(changed, models=states), changed)
    assert result.selected_model_alias == "astra"
    assert result.executable
    assert "MODEL_DEGRADED" in result.rationale_codes


@pytest.mark.parametrize("limits", [
    {"constraints": {"task_cost_ceiling_usd": "0.005"}},
    {},
])
def test_cache_evidence_does_not_guarantee_a_hit_for_hard_budget_admission(bundle, limits):
    req = request(context={"input_tokens": 100000, "expected_output_tokens": 0,
                           "cached_input_tokens": 100000, "cache_evidence": True}, **limits)
    cl = classification(components=dict(reasoning_depth=5, step_dependency=5, context_synthesis=1,
                        technical_precision=0, ambiguity=0, tool_orchestration=0, reliability_requirement=0))
    env = environment(bundle, remaining_usd="10" if limits else "0.005")
    result = route(req, cl, env, bundle)
    assert isinstance(result, RouteRejection)
    assert result.failure_type == "BUDGET_FAILURE"
    quote = result.rationale_details["cache_miss_budget_estimates"]["luna"]
    assert Decimal(quote["amount"]) == Decimal("0.020")


def test_production_preview_cannot_enable_draft_execution(bundle):
    env = EnvironmentSnapshot(snapshot_id="preview", clock="2026-09-06T20:00:00Z", pricing_version="quote",
                              budget={"live_execution_enabled": True, "task_cost_ceiling_usd": "10"})
    result = route(request(constraints={"live_execution_enabled": True}), classification(), env, bundle)
    assert result.routing_result == "valid" and not result.executable
    assert result.effective_limits.live_execution_enabled is False


def test_health_exhaustion_is_recoverable_infrastructure_rejection(bundle):
    env = environment(bundle, models={alias: {"state": "UNHEALTHY", "usable": False} for alias in bundle.catalog["models"]})
    result = route(request(), classification(), env, bundle)
    assert isinstance(result, RouteRejection)
    assert result.failure_type == "PROVIDER_FAILURE" and result.retryable
    assert "no_healthy_permitted_path" in result.violated_constraints
    assert "selected_model_alias" not in result.model_dump()


def test_catalog_model_names_and_provider_ids_are_not_baked_into_engine():
    docs = [yaml.safe_load((ROOT / "config" / name).read_text()) for name in
            ("routing-policy.yaml", "models.yaml", "budgets.yaml", "validation.yaml")]
    policy, catalog, budgets, validation = deepcopy(docs)
    aliases = {name: f"renamed-{index}" for index, name in enumerate(catalog["models"])}
    catalog["models"] = {aliases[name]: model for name, model in catalog["models"].items()}
    for name, model in catalog["models"].items():
        model["provider_model_id"] = f"provider-{name}"
    for band in policy["complexity_bands"]:
        for candidate in band["candidates"]:
            candidate["model"] = aliases[candidate["model"]]
    for modifier in policy["modifiers"]:
        for candidate in modifier["effect"].get("add_candidates", []):
            candidate["model"] = aliases[candidate["model"]]
    for comparison in validation["shadow_evaluation"]["comparisons"]:
        for pair in comparison.values():
            pair["model"] = aliases[pair["model"]]
    changed = bundle_from_documents(policy, catalog, budgets, validation)
    result = route(request(), classification(), environment(changed), changed)
    assert result.selected_model_alias == aliases["terra"]
    assert result.provider_model_id == f'provider-{aliases["terra"]}'
