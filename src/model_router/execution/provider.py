"""Provider port exports and a deterministic, credential-free test adapter."""
from __future__ import annotations
from collections.abc import Callable, Iterable
from typing import TypeAlias
from model_router.core.contracts import FailureType
from model_router.core.provider_contracts import ModelProvider, ProviderEvidence, ProviderFailure, ProviderRequest, ProviderResult, ProviderUsage

MockOutcome: TypeAlias = ProviderResult | ProviderFailure | Callable[[ProviderRequest], ProviderResult | ProviderFailure]

def request_evidence(request: ProviderRequest, latency_ms: float = 0.0) -> dict[str, object]:
    return {
        "task_id": request.task_id, "trace_id": request.trace_id,
        "invocation_id": request.invocation_id, "policy_version": request.policy_version,
        "catalog_version": request.catalog_version, "model_alias": request.model_alias,
        "provider_model_id": request.provider_model_id, "reasoning_effort": request.reasoning_effort,
        "purpose": request.purpose, "latency_ms": latency_ms,
    }

def sanitized_request(request: ProviderRequest) -> dict[str, object]:
    fields = request_evidence(request)
    fields.pop("latency_ms")
    return {**fields, "max_output_tokens": request.max_output_tokens,
            "timeout_ms": request.timeout_ms, "truncation": request.truncation,
            "structured_output": request.output_type is not None,
            "has_instructions": request.instructions is not None}

class MockProvider:
    """Consume scripted outcomes without importing an SDK or using a network."""
    def __init__(self, outcomes: Iterable[MockOutcome]):
        self._outcomes = iter(outcomes)
        self.requests: list[dict[str, object]] = []
        self.call_count = 0

    def execute(self, request: ProviderRequest) -> ProviderResult | ProviderFailure:
        self.call_count += 1
        self.requests.append(sanitized_request(request))
        try:
            scripted = next(self._outcomes)
        except StopIteration:
            return ProviderFailure(**request_evidence(request), failure_type=FailureType.UNKNOWN_FAILURE,
                source="adapter", stage="invocation", cause_code="mock_script_exhausted",
                diagnostic_fields=("outcomes",))
        outcome = scripted(request) if callable(scripted) else scripted
        if isinstance(outcome, (ProviderResult, ProviderFailure)):
            return outcome
        return ProviderFailure(**request_evidence(request), failure_type=FailureType.UNKNOWN_FAILURE,
            source="adapter", stage="normalization", cause_code="mock_outcome_invalid",
            diagnostic_fields=("outcome_type",))

__all__ = ["MockProvider", "ModelProvider", "ProviderEvidence", "ProviderFailure",
           "ProviderRequest", "ProviderResult", "ProviderUsage"]
