from types import SimpleNamespace

from pydantic import BaseModel

from model_router.core.contracts import FailureType, Request
from model_router.core.execution_contracts import Failure, ValidationOutcome
from model_router.core.provider_contracts import ProviderFailure, ProviderRequest, ProviderResult
from model_router.execution.provider import request_evidence
from model_router.policy.loader import load_bundle
from model_router.policy.phase4 import load_phase4
from model_router.validation.semantic import (
    EvaluatorScore,
    MockDomainValidator,
    MockEvaluator,
    ValidationService,
)


def setup_service(outcomes, *, domain_ref=None, registry=None):
    bundle = load_bundle("config")
    config = load_phase4("config/phase4.yaml", bundle)
    if domain_ref is not None:
        config = config.model_copy(update={"domain_validator_ref": domain_ref})
    evaluator = MockEvaluator(outcomes)
    return ValidationService(config, evaluator, bundle, registry), evaluator


def provider_request(**changes):
    values = dict(
        task_id="task",
        trace_id="trace",
        invocation_id="evaluation-1",
        policy_version="routing-policy-v1.0.0",
        catalog_version="models-v1.0.0",
        model_alias="terra",
        provider_model_id="gpt-5.6-terra",
        reasoning_effort="medium",
        input="untrusted task and candidate",
        instructions="caller supplied instructions",
        max_output_tokens=999,
        timeout_ms=9999,
    )
    values.update(changes)
    return ProviderRequest(**values)


def decision(*, refs=("lightweight",), profiles=("V0", "V1")):
    return SimpleNamespace(
        validation_requirements=SimpleNamespace(
            evaluator_refs=refs, profiles=profiles, validator_refs=()
        )
    )


def domain_request():
    return Request(
        task_id="task",
        trace_id="trace",
        input="private task",
        requirements=("text_input", "text_output"),
        consequence="critical",
        context={"input_tokens": 10, "expected_output_tokens": 10},
    )


def generation_result():
    request = provider_request(purpose="generation")
    return ProviderResult(
        **request_evidence(request), response_status="completed", text="private candidate"
    )


def test_plans_preserve_required_order_and_readiness_detects_missing_refs_and_domain():
    service, _ = setup_service([])
    assert tuple(plan.ref for plan in service.plans(decision(refs=("strong_independent", "lightweight")))) == (
        "strong_independent",
        "lightweight",
    )
    assert service.readiness(decision(refs=("missing",))) == ("evaluator_unconfigured",)
    assert service.readiness(decision(refs=(), profiles=("V0", "V3"))) == (
        "domain_validator_unconfigured",
    )


def test_evaluation_pins_binding_schema_rubric_and_scale_and_invokes_once():
    service, evaluator = setup_service([0.8])
    binding = service.plans(decision())[0]
    provider, validation = service.evaluate(binding, provider_request())
    assert isinstance(provider, ProviderResult)
    assert evaluator.call_count == 1
    assert evaluator.requests == [
        {
            "task_id": "task",
            "trace_id": "trace",
            "invocation_id": "evaluation-1",
            "policy_version": "routing-policy-v1.0.0",
            "catalog_version": "models-v1.0.0",
            "model_alias": "luna",
            "provider_model_id": "gpt-5.6-luna",
            "reasoning_effort": "low",
            "purpose": "evaluation",
            "max_output_tokens": 128,
            "timeout_ms": 2000,
            "truncation": "disabled",
            "structured_output": True,
            "has_instructions": True,
        }
    ]
    assert validation.status == "passed"
    assert validation.score == 0.8
    assert (validation.score_min, validation.score_max) == (0.0, 1.0)
    assert validation.rubric_version == "semantic-lightweight-v1"
    assert validation.evaluator_attempt_id == "evaluation-1"
    assert validation.cost_usd == 0


def test_evaluate_rejects_a_binding_not_owned_by_the_versioned_config():
    service, evaluator = setup_service([1.0])
    binding = service.plans(decision())[0].model_copy(update={"pass_threshold": 0.1})
    provider, validation = service.evaluate(binding, provider_request())
    assert evaluator.call_count == 0
    assert isinstance(provider, ProviderFailure)
    assert provider.cause_code == "evaluator_binding_invalid"
    assert validation.status == "error"
    assert validation.failure.source == "evaluator"


def test_only_valid_below_threshold_score_is_quality_failure():
    service, _ = setup_service([0.79])
    binding = service.plans(decision())[0]
    _, validation = service.evaluate(binding, provider_request())
    assert validation.status == "failed"
    assert validation.failure == Failure(
        failure_type=FailureType.QUALITY_FAILURE,
        source="validation",
        stage="validation",
        cause_code="evaluator_score_below_threshold",
    )
    assert validation.evidence_code == "evaluator_score_below_threshold"


def test_provider_failure_remains_evaluator_error_and_forged_quality_is_sanitized():
    def forged(request):
        return ProviderFailure(
            **request_evidence(request),
            failure_type=FailureType.QUALITY_FAILURE,
            source="provider",
            stage="invocation",
            cause_code="untrusted_quality_claim",
        )

    service, evaluator = setup_service([forged])
    binding = service.plans(decision())[0]
    provider, validation = service.evaluate(binding, provider_request())
    assert evaluator.call_count == 1
    assert isinstance(provider, ProviderFailure)
    assert provider.failure_type == FailureType.VALIDATION_FAILURE
    assert provider.cause_code == "evaluator_failure_type_invalid"
    assert validation.status == "error"
    assert validation.failure.source == "evaluator"
    assert validation.failure.failure_type == FailureType.VALIDATION_FAILURE
    assert validation.cost_usd == 0


def test_timeout_is_an_evaluator_error_with_retry_evidence():
    def timeout(request):
        return ProviderFailure(
            **request_evidence(request),
            failure_type=FailureType.TIMEOUT,
            source="provider",
            stage="invocation",
            cause_code="provider_timeout",
            retryable=True,
            retry_after_ms=20,
        )

    service, _ = setup_service([timeout])
    binding = service.plans(decision())[0]
    provider, validation = service.evaluate(binding, provider_request())
    assert provider.failure_type == FailureType.TIMEOUT
    assert validation.status == "error"
    assert validation.failure.failure_type == FailureType.TIMEOUT
    assert validation.failure.source == "evaluator"
    assert validation.failure.retryable is True
    assert validation.failure.retry_after_ms == 20


def test_mismatched_incomplete_refused_and_bad_shape_never_become_quality():
    class WrongShape(BaseModel):
        grade: float

    def mismatch(request):
        return ProviderResult(
            **(request_evidence(request) | {"trace_id": "wrong"}),
            response_status="completed",
            structured_output=EvaluatorScore(score=1.0),
        )

    def incomplete(request):
        return ProviderResult(
            **request_evidence(request),
            response_status="incomplete",
            incomplete_reason="max_output_tokens",
        )

    def refused(request):
        return ProviderResult(
            **request_evidence(request), response_status="completed", refused=True
        )

    def wrong_shape(request):
        return ProviderResult(
            **request_evidence(request),
            response_status="completed",
            structured_output=WrongShape(grade=1.0),
        )

    service, evaluator = setup_service([mismatch, incomplete, refused, wrong_shape])
    binding = service.plans(decision())[0]
    outcomes = [service.evaluate(binding, provider_request(invocation_id=f"eval-{i}")) for i in range(4)]
    assert evaluator.call_count == 4
    assert [item[1].status for item in outcomes] == ["error"] * 4
    assert [item[1].evidence_code for item in outcomes] == [
        "evaluator_correlation_invalid",
        "evaluator_not_completed",
        "evaluator_refused",
        "evaluator_score_invalid",
    ]
    assert all(item[1].failure.failure_type != FailureType.QUALITY_FAILURE for item in outcomes)
    assert all(isinstance(item[0], ProviderFailure) for item in outcomes)


def test_domain_registry_is_explicit_and_mock_boundary_stores_no_content():
    passed = ValidationOutcome(
        evaluation_id="domain-eval",
        check="legal",
        status="passed",
        evidence_code="domain_check_passed",
    )
    domain = MockDomainValidator([passed])
    service, _ = setup_service([], domain_ref="legal", registry={"legal": domain})
    assert service.domain_bound == 0
    assert service.readiness(decision(refs=(), profiles=("V0", "V3"))) == ()
    outcome = service.validate_domain(domain_request(), generation_result())
    assert outcome == passed
    assert domain.call_count == 1
    assert domain.calls == [
        {"task_id": "task", "trace_id": "trace", "invocation_id": "evaluation-1"}
    ]
    assert "private" not in repr(domain.calls)


def test_invalid_domain_adapter_result_is_sanitized():
    domain = MockDomainValidator([object()])
    service, _ = setup_service([], domain_ref="legal", registry={"legal": domain})
    outcome = service.validate_domain(domain_request(), generation_result())
    assert outcome.status == "error"
    assert outcome.evidence_code == "domain_validator_error"
    assert outcome.failure.failure_type == FailureType.VALIDATION_FAILURE
    assert outcome.failure.source == "validation"
