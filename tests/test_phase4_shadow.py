"""Bounded shadow execution stays synthetic, private and budget-isolated."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import replace
from pathlib import Path

import yaml
import pytest
from model_router.core.configuration import bundle_from_documents
from model_router.core.contracts import Candidate, Classification, EnvironmentSnapshot, Request, ValidationLevel
from model_router.core.execution_contracts import Attempt, AttemptStatus, ExecutionControls
from model_router.core.execution_contracts import TaskStatus, ValidationOutcome
from model_router.core.provider_contracts import ProviderFailure, ProviderResult, ProviderUsage
from model_router.execution.admission import MemoryBudgetAuthority
from model_router.execution.clock import MockClock
from model_router.execution.provider import MockProvider, request_evidence
from model_router.execution.orchestrator import execute
from model_router.policy.loader import load_bundle
from model_router.policy.phase4 import load_phase4
from model_router.router import route
from model_router.shadow import ShadowService
from model_router.validation import DeterministicCheck, V0Validator
from model_router.validation.semantic import EvaluatorScore, MockEvaluator, ValidationService
from phase3_support import setup


NOW = datetime(2026, 9, 6, 20, tzinfo=timezone.utc)


def enabled_bundle(*, rate=1.0, task_cap="1", period_cap="10"):
    config = Path("config")
    with (config / "routing-policy.yaml").open() as stream:
        policy = yaml.safe_load(stream)
    with (config / "models.yaml").open() as stream:
        catalog = yaml.safe_load(stream)
    with (config / "budgets.yaml").open() as stream:
        budgets = yaml.safe_load(stream)
    with (config / "validation.yaml").open() as stream:
        validation = yaml.safe_load(stream)
    validation["version"] = "validation-shadow-test-v1"
    policy["version"] = "routing-shadow-test-v1"
    policy["validation_version"] = validation["version"]
    shadow = validation["shadow_evaluation"]
    shadow["enabled"] = True
    shadow["sampling"]["rate"] = rate
    shadow["budget"]["task_cost_ceiling_usd"] = task_cap
    shadow["budget"]["period_spend_ceiling_usd"] = period_cap
    return bundle_from_documents(policy, catalog, budgets, validation)


def fixture(bundle, *, task_id="task", requirements=("text_input", "text_output")):
    request = Request(
        task_id=task_id,
        trace_id=f"trace-{task_id}",
        input="private prompt sentinel",
        requirements=requirements,
        consequence="low",
        context={"input_tokens": 100, "expected_output_tokens": 100},
    )
    classification = Classification(
        task_family="analysis",
        confidence=1.0,
        provenance="fixture",
        components={
            "reasoning_depth": 12,
            "step_dependency": 11,
            "context_synthesis": 7,
            "technical_precision": 11,
            "ambiguity": 5,
            "tool_orchestration": 0,
            "reliability_requirement": 3,
        },
    )
    environment = EnvironmentSnapshot(
        snapshot_id="synthetic",
        synthetic=True,
        clock=NOW,
        pricing_version="synthetic",
        health_snapshot_id="health",
        health_observed_at="2026-09-06T19:59:00Z",
        health_valid_until="2026-09-06T21:00:00Z",
        models={alias: {"state": "HEALTHY", "account_access": "verified"} for alias in bundle.catalog["models"]},
        budget={"task_cost_ceiling_usd": "10", "task_deadline_ms": 30000, "live_execution_enabled": True},
        remaining_usd="10",
        validation={"V0": "configured_mock"},
        recovery_bounded=True,
        durable_retention=True,
    )
    decision = route(request, classification, environment, bundle)
    attempt = Attempt(
        attempt_id=f"production-{task_id}",
        task_id=task_id,
        trace_id=request.trace_id,
        sequence=1,
        status=AttemptStatus.SUCCEEDED,
        started_at=NOW,
        completed_at=NOW,
        decision=decision,
        pricing_version=decision.pricing_version,
    )
    return request, environment, attempt


def production_for(request, environment, bundle):
    classification = fixture(bundle)[2].decision.classification
    decision = route(request, classification, environment, bundle)
    return Attempt(attempt_id=f"production-{request.task_id}", task_id=request.task_id,
        trace_id=request.trace_id, sequence=1, status=AttemptStatus.SUCCEEDED,
        started_at=NOW, completed_at=NOW, decision=decision,
        pricing_version=decision.pricing_version)


def success(request):
    return ProviderResult(
        **request_evidence(request),
        response_status="completed",
        text="shadow result must remain hidden",
        usage=ProviderUsage(
            input_tokens=10,
            cached_input_tokens=0,
            cache_write_input_tokens=0,
            output_tokens=10,
            reasoning_tokens=0,
            total_tokens=20,
        ),
    )


def service(bundle, outcomes, *, privacy=True, budget="10", validator=None):
    provider = MockProvider(outcomes)
    authority = MemoryBudgetAuthority(default_ceiling=budget)
    instance = ShadowService(
        bundle,
        provider,
        authority,
        MockClock(NOW),
        validator,
        privacy_allowed=privacy,
    )
    return instance, provider, authority


def test_disabled_and_nonselected_sampling_do_not_execute():
    disabled = load_bundle("config")
    request, environment, production = fixture(disabled)
    instance, provider, _ = service(disabled, [success])
    result = instance.run(request, production, environment=environment, controls=ExecutionControls())
    assert (result.selected, result.status, result.reason) == (False, "skipped", "shadow_disabled")
    assert provider.call_count == 0

    bundle = enabled_bundle(rate=0.0)
    request, environment, production = fixture(bundle)
    instance, provider, _ = service(bundle, [success])
    result = instance.run(request, production, environment=environment, controls=ExecutionControls())
    assert (result.selected, result.reason) == (False, "not_sampled")
    assert provider.call_count == 0


def test_selected_comparison_records_pair_and_hides_output():
    bundle = enabled_bundle()
    request, environment, production = fixture(bundle)
    instance, provider, _ = service(bundle, [success])
    observed = []
    result = instance.run(
        request,
        production,
        environment=environment,
        controls=ExecutionControls(),
        before_attempt=observed.append,
        after_attempt=observed.append,
    )
    assert result.status == "succeeded" and result.selected
    assert provider.call_count == 1
    assert result.attempts[0].role == "shadow"
    assert (result.attempts[0].decision.selected_model_alias, result.attempts[0].decision.reasoning_effort) == ("sol", "medium")
    assert observed[0].status == "started" and observed[0].attempts[0].status == AttemptStatus.STARTED
    assert observed[-1] == result
    assert observed[1].attempts[0].provider_outcome is not None
    assert result.generation_cost_usd > 0
    assert "shadow result must remain hidden" not in result.model_dump_json()
    assert "private prompt sentinel" not in result.model_dump_json()


def test_cheaper_comparison_preserves_production_route():
    bundle = enabled_bundle()
    request, environment, production = fixture(bundle)
    sol = route(
        request,
        production.decision.classification,
        environment,
        bundle,
        recovery_candidates=(Candidate(model="sol", effort="high", source="fallback"),),
    )
    production = production.model_copy(update={"decision": sol})
    original = production.model_dump_json()
    instance, provider, _ = service(bundle, [success])
    result = instance.run(request, production, environment=environment, controls=ExecutionControls())
    assert result.status == "succeeded" and provider.call_count == 1
    assert (result.attempts[0].decision.selected_model_alias, result.attempts[0].decision.reasoning_effort) == ("terra", "medium")
    assert production.model_dump_json() == original


def test_privacy_and_tools_fail_closed_before_dispatch():
    bundle = enabled_bundle()
    request, environment, production = fixture(bundle)
    instance, provider, _ = service(bundle, [success], privacy=False)
    denied = instance.run(request, production, environment=environment, controls=ExecutionControls())
    assert denied.reason == "shadow_privacy_not_allowed"

    instance, provider, _ = service(bundle, [success])
    tool_request = request.model_copy(update={"side_effecting_tool": True})
    denied = instance.run(tool_request, production, environment=environment, controls=ExecutionControls())
    assert denied.reason == "shadow_tools_not_allowed"
    assert provider.call_count == 0


def test_task_and_period_budgets_are_finite_and_separate():
    bundle = enabled_bundle(task_cap="0", period_cap="0")
    request, environment, production = fixture(bundle)
    instance, provider, authority = service(bundle, [success])
    result = instance.run(request, production, environment=environment, controls=ExecutionControls())
    assert result.reason == "shadow_task_budget_exhausted"
    assert provider.call_count == 0
    # Shadow admission never uses the production task ledger key.
    assert authority.remaining(request.task_id) == 10

    bundle = enabled_bundle(task_cap="1", period_cap="0")
    request, environment, production = fixture(bundle)
    instance, provider, _ = service(bundle, [success])
    result = instance.run(request, production, environment=environment, controls=ExecutionControls())
    assert result.reason == "shadow_period_budget_exhausted"
    assert provider.call_count == 0


def test_provider_failure_is_one_attempt_and_does_not_escape():
    bundle = enabled_bundle()
    request, environment, production = fixture(bundle)

    def fail(provider_request):
        return ProviderFailure(
            **request_evidence(provider_request),
            failure_type="PROVIDER_FAILURE",
            source="provider",
            stage="invocation",
            cause_code="synthetic_outage",
        )

    instance, provider, _ = service(bundle, [fail, success])
    result = instance.run(request, production, environment=environment, controls=ExecutionControls())
    assert result.status == "failed" and result.reason == "shadow_provider_failed"
    assert len(result.attempts) == 1 and provider.call_count == 1
    assert result.attempts[0].failure.cause_code == "synthetic_outage"


def test_optional_validation_has_its_own_bounded_cost():
    bundle = enabled_bundle()
    request, environment, production = fixture(bundle)
    validator = V0Validator(
        checks={
            "calculation": DeterministicCheck(
                run=lambda _request, _result: ValidationOutcome(
                    evaluation_id="shadow-check",
                    check="calculation",
                    status="passed",
                    cost_usd="0.02",
                ),
                cost_upper_bound_usd=Decimal("0.05"),
            )
        }
    )
    instance, _, _ = service(bundle, [success], validator=validator)
    result = instance.run(
        request,
        production,
        environment=environment,
        controls=ExecutionControls(required_checks=("calculation",)),
    )
    assert result.status == "succeeded"
    assert result.validation_cost_usd == result.attempts[0].validations[-1].cost_usd == Decimal("0.02")
    assert result.generation_cost_usd > 0


def test_callback_failure_retains_completed_spend_evidence():
    bundle = enabled_bundle()
    request, environment, production = fixture(bundle)
    instance, provider, _ = service(bundle, [success])

    def broken(_run):
        raise RuntimeError("storage unavailable")

    result = instance.run(
        request,
        production,
        environment=environment,
        controls=ExecutionControls(),
        after_attempt=broken,
    )
    assert result.status == "failed" and result.reason == "after_attempt_callback_failed"
    assert result.attempts[0].provider_outcome is not None
    assert result.generation_cost_usd > 0
    assert provider.call_count == 1


def test_default_v0_rejects_refusal_and_missing_required_check():
    bundle = enabled_bundle()
    request, environment, production = fixture(bundle)

    def refused(provider_request):
        return ProviderResult(**request_evidence(provider_request), response_status="completed", refused=True,
            usage=ProviderUsage(input_tokens=1, cached_input_tokens=0, cache_write_input_tokens=0,
                                output_tokens=1, reasoning_tokens=0, total_tokens=2))

    instance, provider, _ = service(bundle, [refused])
    result = instance.run(request, production, environment=environment, controls=ExecutionControls())
    assert result.status == "failed" and result.reason == "shadow_v0_validation_failed"
    assert result.attempts[0].validations[0].check == "provider_success"

    instance, provider, _ = service(bundle, [success])
    result = instance.run(request, production, environment=environment,
        controls=ExecutionControls(required_checks=("missing",)))
    assert result.reason == "shadow_required_v0_check_unavailable"
    assert provider.call_count == 0


@pytest.mark.parametrize("level,ref", [("V1", "lightweight"), ("V2", "strong_independent")])
def test_required_semantic_validation_is_one_persisted_shadow_attempt(level, ref):
    bundle = enabled_bundle()
    request, environment, _ = fixture(bundle)
    level_value = ValidationLevel(level)
    request = request.model_copy(update={"requested_validation": level_value})
    environment = environment.model_copy(update={"validation": {
        ValidationLevel.V0: "configured_mock", level_value: "configured_mock"}})
    production = production_for(request, environment, bundle)

    def scored(provider_request):
        return ProviderResult(**request_evidence(provider_request), response_status="completed",
            structured_output=EvaluatorScore(score=1.0), usage=ProviderUsage(input_tokens=20,
            cached_input_tokens=0, cache_write_input_tokens=0, output_tokens=2,
            reasoning_tokens=0, total_tokens=22))

    evaluator = MockEvaluator([scored])
    semantic = ValidationService(load_phase4("config/phase4.yaml", bundle), evaluator, bundle)
    generator = MockProvider([success])
    instance = ShadowService(bundle, generator, MemoryBudgetAuthority(default_ceiling="10"),
        MockClock(NOW), semantic, privacy_allowed=True)
    intents = []
    result = instance.run(request, production, environment=environment, controls=ExecutionControls(),
        before_attempt=intents.append)
    assert result.status == "succeeded"
    assert generator.call_count == evaluator.call_count == 1
    assert len(result.attempts) == 2
    generation, evaluation = result.attempts
    assert evaluation.purpose == "evaluation" and evaluation.role == "shadow"
    assert evaluation.parent_attempt_id == generation.attempt_id and evaluation.evaluator_ref == ref
    assert evaluation.validations[0].target_attempt_id == generation.attempt_id
    assert result.validation_cost_usd > 0
    assert intents[-1].attempts[-1].status == AttemptStatus.STARTED


def test_v3_and_missing_semantic_service_reject_before_generation():
    bundle = enabled_bundle()
    request, environment, _ = fixture(bundle)
    for level, expected in (("V1", "shadow_semantic_validator_required"),
                            ("V3", "shadow_domain_validation_unsupported")):
        level_value = ValidationLevel(level)
        changed = request.model_copy(update={"requested_validation": level_value})
        env = environment.model_copy(update={"validation": {
            ValidationLevel.V0: "configured_mock", level_value: "configured_mock"}})
        production = production_for(changed, env, bundle)
        instance, provider, _ = service(bundle, [success])
        result = instance.run(changed, production, environment=env, controls=ExecutionControls())
        assert result.reason == expected and provider.call_count == 0


def test_unresolved_route_readiness_blocker_rejects_before_dispatch():
    bundle = enabled_bundle()
    request, environment, _ = fixture(bundle)
    environment = environment.model_copy(update={"durable_retention": False})
    production = production_for(request, environment, bundle)
    instance, provider, _ = service(bundle, [success])
    result = instance.run(request, production, environment=environment, controls=ExecutionControls())
    assert result.reason == "shadow_route_not_ready_durable_retention_unavailable"
    assert provider.call_count == 0


def test_semantic_input_bound_stops_before_evaluator_dispatch():
    bundle = enabled_bundle()
    request, environment, _ = fixture(bundle)
    request = request.model_copy(update={"requested_validation": ValidationLevel.V1})
    environment = environment.model_copy(update={"validation": {
        ValidationLevel.V0: "configured_mock", ValidationLevel.V1: "configured_mock"}})
    production = production_for(request, environment, bundle)
    config = load_phase4("config/phase4.yaml", bundle)
    bindings = tuple(binding.model_copy(update={"max_input_tokens": 1})
                     if binding.ref == "lightweight" else binding for binding in config.evaluators)
    evaluator = MockEvaluator([1.0])
    semantic = ValidationService(config.model_copy(update={"evaluators": bindings}), evaluator, bundle)
    generator = MockProvider([success])
    instance = ShadowService(bundle, generator, MemoryBudgetAuthority(default_ceiling="10"),
        MockClock(NOW), semantic, privacy_allowed=True)
    result = instance.run(request, production, environment=environment, controls=ExecutionControls())
    assert result.status == "failed" and result.reason == "shadow_evaluator_input_bound_exceeded"
    assert generator.call_count == 1 and evaluator.call_count == 0
    assert result.attempts[-1].status == AttemptStatus.CANCELLED


def test_callback_time_advance_rechecks_deadline_and_health_before_dispatch():
    bundle = enabled_bundle()
    request, environment, production = fixture(bundle)
    instance, provider, _ = service(bundle, [success])
    result = instance.run(request, production, environment=environment, controls=ExecutionControls(),
        before_attempt=lambda _run: instance.clock.advance(30000))
    assert result.reason == "shadow_deadline_exhausted" and provider.call_count == 0

    environment = environment.model_copy(update={"health_valid_until": NOW + timedelta(milliseconds=10)})
    production = production_for(request, environment, bundle)
    instance, provider, _ = service(bundle, [success])
    result = instance.run(request, production, environment=environment, controls=ExecutionControls(),
        before_attempt=lambda _run: instance.clock.advance(20))
    assert result.reason == "shadow_health_snapshot_stale" and provider.call_count == 0


def test_v0_rechecks_deadline_between_required_checks():
    bundle = enabled_bundle()
    request, environment, production = fixture(bundle)
    calls = []
    clock = MockClock(NOW)

    def first(_request, _result):
        calls.append("first")
        clock.advance(30000)
        return ValidationOutcome(evaluation_id="first", check="first", status="passed")

    def second(_request, _result):
        calls.append("second")
        return ValidationOutcome(evaluation_id="second", check="second", status="passed")

    validator = V0Validator(checks={
        "first": DeterministicCheck(first),
        "second": DeterministicCheck(second),
    })
    provider = MockProvider([success])
    instance = ShadowService(bundle, provider, MemoryBudgetAuthority(default_ceiling="10"),
        clock, validator, privacy_allowed=True)
    result = instance.run(request, production, environment=environment,
        controls=ExecutionControls(required_checks=("first", "second")))
    assert result.status == "failed" and result.reason == "shadow_deadline_exhausted"
    assert calls == ["first"]
    assert [item.check for item in result.attempts[0].validations] == [
        "provider_success", "first", "second"]
    assert result.attempts[0].validations[-1].status == "error"


def test_provider_evidence_callback_precedes_failed_ledger_settlement():
    class BrokenSettlementBudget(MemoryBudgetAuthority):
        def __init__(self):
            super().__init__(default_ceiling="10")
            self.settle_calls = 0

        def settle(self, task_id, action_id, actual):
            self.settle_calls += 1
            raise RuntimeError("ledger unavailable")

    bundle = enabled_bundle()
    request, environment, production = fixture(bundle)
    budget = BrokenSettlementBudget()
    provider = MockProvider([success])
    instance = ShadowService(bundle, provider, budget, MockClock(NOW), privacy_allowed=True)
    observed = []

    def persist(run):
        if run.reason == "shadow_provider_observed":
            assert budget.settle_calls == 0
            assert run.attempts[0].provider_outcome is not None
        observed.append(run)

    result = instance.run(request, production, environment=environment, controls=ExecutionControls(),
        after_attempt=persist)
    assert result.reason == "shadow_budget_settlement_failed"
    assert any(run.reason == "shadow_provider_observed" for run in observed)


def test_cache_evidence_reserves_cache_miss_generation_bound():
    bundle = enabled_bundle()
    request, environment, _ = fixture(bundle)
    request = request.model_copy(update={"context": request.context.model_copy(update={
        "cached_input_tokens": 90, "cache_evidence": True})})
    production = production_for(request, environment, bundle)
    intents = []
    instance, _, _ = service(bundle, [success])
    result = instance.run(request, production, environment=environment, controls=ExecutionControls(),
        before_attempt=intents.append)
    miss = result.attempts[0].decision.rationale_details["cache_miss_budget_estimates"]["sol"]
    assert intents[0].attempts[0].estimated_cost_usd == Decimal(miss["generation_subtotal"])


def test_execute_persists_semantic_shadow_attempts_without_changing_production(tmp_path):
    bundle = enabled_bundle()
    request, classification, deps = setup(tmp_path, bundle=bundle)
    request = request.model_copy(update={"requested_validation": ValidationLevel.V1})
    config = load_phase4("config/phase4.yaml", bundle)
    production_semantic = ValidationService(config, MockEvaluator([1.0]), bundle)
    shadow_evaluator = MockEvaluator([1.0])
    shadow_semantic = ValidationService(config, shadow_evaluator, bundle)
    shadow_provider = MockProvider([success])
    shadow = ShadowService(bundle, shadow_provider, MemoryBudgetAuthority(default_ceiling="10"),
        deps.clock, shadow_semantic, privacy_allowed=True)
    dependencies = replace(deps, semantic=production_semantic, shadow=shadow)

    result = execute(request, dependencies, supplied_classification=classification)
    assert result.status == TaskStatus.SUCCEEDED
    assert result.output == "private output"
    assert len(result.shadow_runs) == 1 and result.shadow_runs[0].status == "succeeded"
    assert len(result.shadow_runs[0].attempts) == 2
    assert shadow_provider.call_count == shadow_evaluator.call_count == 1
    persisted = dependencies.repository.get(request.task_id)
    assert persisted.shadow_runs[0].shadow_id == result.shadow_runs[0].shadow_id
    assert persisted.shadow_runs[0].status == "succeeded"
    assert len(persisted.shadow_runs[0].attempts) == 2
    assert persisted.output is None
