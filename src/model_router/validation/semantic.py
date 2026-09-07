"""Configured semantic and application-domain validation boundaries.

The service performs exactly one evaluator invocation.  Retry, accounting and
attempt persistence belong to the execution orchestrator.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from typing import Annotated, Protocol, TypeAlias, runtime_checkable
from uuid import uuid4

from pydantic import Field

from model_router.core.contracts import FailureType, Record, Request, RouteDecision
from model_router.core.execution_contracts import Failure, ValidationOutcome
from model_router.core.phase4_contracts import EvaluatorBinding, Phase4Config
from model_router.core.provider_contracts import ProviderFailure, ProviderRequest, ProviderResult
from model_router.execution.provider import MockProvider, request_evidence


class EvaluatorScore(Record):
    """The complete evaluator response schema; free-form rationale is excluded."""

    score: Annotated[float, Field(strict=True, allow_inf_nan=False)]


@runtime_checkable
class DomainValidator(Protocol):
    def validate(self, request: Request, result: ProviderResult) -> ValidationOutcome: ...


DomainRegistry = Mapping[str, DomainValidator]
EvaluatorScript: TypeAlias = (
    float
    | int
    | ProviderResult
    | ProviderFailure
    | Callable[[ProviderRequest], float | int | ProviderResult | ProviderFailure]
)
DomainScript: TypeAlias = (
    ValidationOutcome
    | Callable[[Request, ProviderResult], ValidationOutcome]
)


def _provider_failure(
    request: ProviderRequest,
    *,
    failure_type: FailureType,
    cause_code: str,
    retryable: bool = False,
    outcome: ProviderResult | ProviderFailure | None = None,
) -> ProviderFailure:
    """Create safe normalized failure evidence without copying response content."""

    fields = request_evidence(request, outcome.latency_ms if outcome is not None else 0.0)
    if outcome is not None:
        fields.update(
            response_id=outcome.response_id,
            response_status=outcome.response_status,
            returned_model_id=outcome.returned_model_id,
            usage=outcome.usage,
        )
    return ProviderFailure(
        **fields,
        failure_type=failure_type,
        source="adapter",
        stage="normalization",
        cause_code=cause_code,
        retryable=retryable,
        diagnostic_fields=("evaluator_response",),
    )


def _correlated(request: ProviderRequest, outcome: ProviderResult | ProviderFailure) -> bool:
    return all(
        getattr(request, name) == getattr(outcome, name)
        for name in (
            "task_id",
            "trace_id",
            "invocation_id",
            "policy_version",
            "catalog_version",
            "model_alias",
            "provider_model_id",
            "reasoning_effort",
            "purpose",
        )
    )


def _safe_provider_failure(
    request: ProviderRequest, outcome: ProviderFailure
) -> ProviderFailure:
    """Evaluator infrastructure can never claim task quality failure."""

    if not _correlated(request, outcome):
        return _provider_failure(
            request,
            failure_type=FailureType.VALIDATION_FAILURE,
            cause_code="evaluator_correlation_invalid",
            outcome=outcome,
        )
    allowed = {
        FailureType.TIMEOUT,
        FailureType.RATE_LIMIT,
        FailureType.PROVIDER_FAILURE,
        FailureType.MALFORMED_OUTPUT,
        FailureType.CAPABILITY_FAILURE,
        FailureType.UNKNOWN_FAILURE,
    }
    if outcome.failure_type not in allowed:
        return _provider_failure(
            request,
            failure_type=FailureType.VALIDATION_FAILURE,
            cause_code="evaluator_failure_type_invalid",
            outcome=outcome,
        )
    return outcome


class ValidationService:
    """One-shot semantic evaluator plus a separately configured domain registry."""

    def __init__(
        self,
        config: Phase4Config,
        provider,
        bundle,
        domain_registry: DomainRegistry | None = None,
    ) -> None:
        from model_router.policy.phase4 import validate_phase4
        validate_phase4(config, bundle)
        self.config = config
        self.provider = provider
        self._bundle = bundle
        self._bindings = {binding.ref: binding for binding in config.evaluators}
        self._domain_registry = dict(domain_registry or {})

    @property
    def domain_bound(self) -> Decimal | None:
        """Return the configured cost bound, or ``None`` when no adapter is bound."""

        ref = self.config.domain_validator_ref
        if ref is None or ref not in self._domain_registry:
            return None
        return self.config.domain_cost_upper_bound_usd

    def plans(self, decision: RouteDecision) -> tuple[EvaluatorBinding, ...]:
        """Return configured bindings in the policy-required order."""

        return tuple(
            binding
            for ref in decision.validation_requirements.evaluator_refs
            if (binding := self._bindings.get(ref)) is not None
        )

    def readiness(self, decision: RouteDecision) -> tuple[str, ...]:
        blockers: list[str] = []
        if any(ref not in self._bindings for ref in decision.validation_requirements.evaluator_refs):
            blockers.append("evaluator_unconfigured")
        if "V3" in decision.validation_requirements.profiles and self.domain_bound is None:
            blockers.append("domain_validator_unconfigured")
        return tuple(blockers)

    def _bound_request(
        self, binding: EvaluatorBinding, request: ProviderRequest
    ) -> ProviderRequest:
        model = self._bundle.catalog["models"].get(binding.model_alias)
        provider_model_id = (
            model["provider_model_id"] if model is not None else request.provider_model_id
        )
        return request.model_copy(
            update={
                "model_alias": binding.model_alias,
                "provider_model_id": provider_model_id,
                "reasoning_effort": binding.reasoning_effort,
                "instructions": (
                    f"{binding.rubric} Score scale: {binding.score_min} to "
                    f"{binding.score_max}."
                ),
                "output_type": EvaluatorScore,
                "max_output_tokens": binding.max_output_tokens,
                "timeout_ms": min(request.timeout_ms, binding.timeout_ms),
                "purpose": "evaluation",
            }
        )

    def _outcome(
        self,
        binding: EvaluatorBinding,
        request: ProviderRequest,
        *,
        status: str,
        failure: Failure | None = None,
        evidence_code: str | None = None,
        score: float | None = None,
    ) -> ValidationOutcome:
        return ValidationOutcome(
            evaluation_id=str(uuid4()),
            check=binding.ref,
            status=status,
            failure=failure,
            evidence_code=evidence_code,
            cost_usd="0",
            evaluator_attempt_id=request.invocation_id,
            rubric_version=binding.rubric_version,
            score=score,
            score_min=binding.score_min,
            score_max=binding.score_max,
        )

    def _error(
        self,
        binding: EvaluatorBinding,
        request: ProviderRequest,
        provider_failure: ProviderFailure,
        evidence_code: str,
    ) -> ValidationOutcome:
        failure_type = provider_failure.failure_type
        if failure_type == FailureType.QUALITY_FAILURE:
            failure_type = FailureType.VALIDATION_FAILURE
        return self._outcome(
            binding,
            request,
            status="error",
            failure=Failure(
                failure_type=failure_type,
                source="evaluator",
                stage="validation",
                cause_code=evidence_code,
                retryable=provider_failure.retryable,
                retry_after_ms=provider_failure.retry_after_ms,
            ),
            evidence_code=evidence_code,
        )

    def evaluate(
        self, binding: EvaluatorBinding, provider_request: ProviderRequest
    ) -> tuple[ProviderResult | ProviderFailure, ValidationOutcome]:
        """Invoke an evaluator once and interpret only the pinned score schema."""

        configured = self._bindings.get(binding.ref)
        if configured is None or configured != binding:
            request = self._bound_request(binding, provider_request)
            failure = _provider_failure(
                request,
                failure_type=FailureType.VALIDATION_FAILURE,
                cause_code="evaluator_binding_invalid",
            )
            return failure, self._error(
                binding, request, failure, "evaluator_binding_invalid"
            )
        binding = configured
        request = self._bound_request(binding, provider_request)
        try:
            raw = self.provider.execute(request)
        except Exception:
            raw = _provider_failure(
                request,
                failure_type=FailureType.UNKNOWN_FAILURE,
                cause_code="evaluator_invocation_error",
            )

        if not isinstance(raw, (ProviderResult, ProviderFailure)):
            raw = _provider_failure(
                request,
                failure_type=FailureType.MALFORMED_OUTPUT,
                cause_code="evaluator_outcome_invalid",
            )

        if isinstance(raw, ProviderFailure):
            normalized = _safe_provider_failure(request, raw)
            return normalized, self._error(
                binding, request, normalized, "evaluator_provider_failure"
            )

        if not _correlated(request, raw):
            normalized = _provider_failure(
                request,
                failure_type=FailureType.VALIDATION_FAILURE,
                cause_code="evaluator_correlation_invalid",
                outcome=raw,
            )
            return normalized, self._error(
                binding, request, normalized, "evaluator_correlation_invalid"
            )
        if raw.response_status != "completed" or raw.incomplete_reason is not None:
            normalized = _provider_failure(
                request,
                failure_type=FailureType.VALIDATION_FAILURE,
                cause_code="evaluator_not_completed",
                outcome=raw,
            )
            return normalized, self._error(
                binding, request, normalized, "evaluator_not_completed"
            )
        if raw.refused:
            normalized = _provider_failure(
                request,
                failure_type=FailureType.VALIDATION_FAILURE,
                cause_code="evaluator_refused",
                outcome=raw,
            )
            return normalized, self._error(
                binding, request, normalized, "evaluator_refused"
            )

        try:
            if raw.structured_output is None:
                raise ValueError("missing evaluator score")
            score_record = EvaluatorScore.model_validate(
                raw.structured_output.model_dump()
            )
            score = score_record.score
            if not binding.score_min <= score <= binding.score_max:
                raise ValueError("score outside configured scale")
        except (AttributeError, TypeError, ValueError):
            normalized = _provider_failure(
                request,
                failure_type=FailureType.MALFORMED_OUTPUT,
                cause_code="evaluator_score_invalid",
                outcome=raw,
            )
            return normalized, self._error(
                binding, request, normalized, "evaluator_score_invalid"
            )

        if score < binding.pass_threshold:
            evidence = "evaluator_score_below_threshold"
            return raw, self._outcome(
                binding,
                request,
                status="failed",
                failure=Failure(
                    failure_type=FailureType.QUALITY_FAILURE,
                    source="validation",
                    stage="validation",
                    cause_code=evidence,
                ),
                evidence_code=evidence,
                score=score,
            )
        return raw, self._outcome(
            binding,
            request,
            status="passed",
            evidence_code="evaluator_score_passed",
            score=score,
        )

    def validate_domain(
        self, request: Request, result: ProviderResult
    ) -> ValidationOutcome:
        """Run the configured domain adapter behind a safe validation boundary."""

        ref = self.config.domain_validator_ref
        if ref is None or ref not in self._domain_registry:
            return ValidationOutcome(
                evaluation_id=str(uuid4()),
                check=ref or "domain",
                status="error",
                failure=Failure(
                    failure_type=FailureType.VALIDATION_FAILURE,
                    source="validation",
                    stage="validation",
                    cause_code="domain_validator_unconfigured",
                ),
                evidence_code="domain_validator_unconfigured",
                cost_usd="0",
            )
        outcome = None
        try:
            outcome = self._domain_registry[ref].validate(request, result)
            if not isinstance(outcome, ValidationOutcome):
                raise TypeError("invalid domain outcome")
            if outcome.check != ref:
                raise ValueError("mismatched domain check")
            if outcome.status in {"failed", "error"} and outcome.failure is None:
                raise ValueError("missing domain failure evidence")
            if outcome.status == "skipped" or not outcome.applicable:
                raise ValueError("required domain validation was skipped")
            if outcome.failure and outcome.failure.failure_type == FailureType.QUALITY_FAILURE and (
                outcome.status != "failed"
                or outcome.failure.source != "validation"
                or not outcome.evidence_code
            ):
                raise ValueError("unsupported domain quality evidence")
            if outcome.cost_usd is None or outcome.cost_usd > self.config.domain_cost_upper_bound_usd:
                return ValidationOutcome(
                    evaluation_id=str(uuid4()),
                    check=ref,
                    status="error",
                    failure=Failure(
                        failure_type=FailureType.BUDGET_FAILURE,
                        source="admission",
                        stage="validation",
                        cause_code="domain_cost_exceeded_reservation",
                    ),
                    evidence_code="domain_cost_exceeded_reservation",
                    cost_usd=outcome.cost_usd,
                )
            return outcome
        except Exception:
            return ValidationOutcome(
                evaluation_id=str(uuid4()),
                check=ref,
                status="error",
                failure=Failure(
                    failure_type=FailureType.VALIDATION_FAILURE,
                    source="validation",
                    stage="validation",
                    cause_code="domain_validator_error",
                ),
                evidence_code="domain_validator_error",
                cost_usd=outcome.cost_usd if isinstance(outcome, ValidationOutcome) else None,
            )


class MockEvaluator(MockProvider):
    """Score-oriented façade over the common deterministic MockProvider."""

    def __init__(self, outcomes: Iterable[EvaluatorScript]):
        def adapt(scripted: EvaluatorScript):
            def outcome(request: ProviderRequest):
                value = scripted(request) if callable(scripted) else scripted
                if isinstance(value, (ProviderResult, ProviderFailure)):
                    return value
                return ProviderResult(
                    **request_evidence(request),
                    response_status="completed",
                    structured_output=EvaluatorScore(score=value),
                )

            return outcome

        super().__init__(adapt(item) for item in outcomes)


class MockDomainValidator:
    """Credential-free application boundary with sanitized call observations."""

    def __init__(self, outcomes: Iterable[DomainScript]):
        self._outcomes = iter(outcomes)
        self.call_count = 0
        self.calls: list[dict[str, str | None]] = []

    def validate(self, request: Request, result: ProviderResult) -> ValidationOutcome:
        self.call_count += 1
        self.calls.append(
            {
                "task_id": request.task_id,
                "trace_id": request.trace_id,
                "invocation_id": result.invocation_id,
            }
        )
        scripted = next(self._outcomes)
        return scripted(request, result) if callable(scripted) else scripted


__all__ = [
    "DomainValidator",
    "EvaluatorScore",
    "MockDomainValidator",
    "MockEvaluator",
    "ValidationService",
]
