"""Core-owned contracts for one provider invocation, with no SDK dependencies."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, StrictBool, StrictStr, model_validator

from model_router.core.contracts import Count, Duration, Effort, FailureType, Name, Record


class ProviderRequest(Record):
    task_id: Name
    trace_id: Name
    invocation_id: Name
    policy_version: Name
    catalog_version: Name
    model_alias: Name
    provider_model_id: Name
    reasoning_effort: Effort
    input: StrictStr = Field(exclude=True, repr=False)
    instructions: StrictStr | None = Field(default=None, exclude=True, repr=False)
    output_type: type[BaseModel] | None = Field(default=None, exclude=True, repr=False)
    max_output_tokens: Duration
    timeout_ms: Duration
    purpose: Literal["generation", "classification", "evaluation"] = "generation"
    truncation: Literal["disabled"] = "disabled"


class ProviderUsage(Record):
    """Null means unreported. Reasoning is a subset of output, never additive."""

    input_tokens: Count | None = None
    cached_input_tokens: Count | None = None
    cache_write_input_tokens: Count | None = None
    output_tokens: Count | None = None
    reasoning_tokens: Count | None = None
    total_tokens: Count | None = None

    @model_validator(mode="after")
    def reconcile(self):
        if self.input_tokens is not None:
            known_cache = (self.cached_input_tokens or 0) + (self.cache_write_input_tokens or 0)
            if known_cache > self.input_tokens:
                raise ValueError("cache buckets exceed input usage")
        if self.output_tokens is not None and self.reasoning_tokens is not None:
            if self.reasoning_tokens > self.output_tokens:
                raise ValueError("reasoning usage exceeds output usage")
        if all(value is not None for value in (self.input_tokens, self.output_tokens, self.total_tokens)):
            if self.input_tokens + self.output_tokens != self.total_tokens:
                raise ValueError("total usage does not equal input plus output")
        return self

    @property
    def uncached_input_tokens(self) -> int | None:
        if any(value is None for value in (self.input_tokens, self.cached_input_tokens, self.cache_write_input_tokens)):
            return None
        return self.input_tokens - self.cached_input_tokens - self.cache_write_input_tokens

    @property
    def status(self) -> Literal["known", "partial", "unavailable"]:
        values = [getattr(self, field) for field in type(self).model_fields]
        return "known" if all(value is not None for value in values) else "unavailable" if all(value is None for value in values) else "partial"


class ProviderEvidence(Record):
    task_id: Name
    trace_id: Name
    invocation_id: Name
    policy_version: Name
    catalog_version: Name
    model_alias: Name
    provider_model_id: Name
    reasoning_effort: Effort
    purpose: Literal["generation", "classification", "evaluation"]
    response_id: Name | None = None
    response_status: Literal["completed", "failed", "in_progress", "cancelled", "queued", "incomplete"] | None = None
    returned_model_id: Name | None = None
    returned_service_tier: Literal["default", "flex", "priority", "auto", "scale"] | None = None
    latency_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    usage: ProviderUsage = Field(default_factory=ProviderUsage)


class ProviderResult(ProviderEvidence):
    outcome: Literal["result"] = "result"
    text: StrictStr | None = Field(default=None, exclude=True, repr=False)
    structured_output: BaseModel | None = Field(default=None, exclude=True, repr=False)
    incomplete_reason: Literal["max_output_tokens", "content_filter", "unknown"] | None = None
    refused: StrictBool = False


class ProviderFailure(ProviderEvidence):
    outcome: Literal["failure"] = "failure"
    failure_type: FailureType
    source: Literal["provider", "adapter"]
    stage: Literal["preflight", "invocation", "normalization"]
    cause_code: Name
    retryable: StrictBool = False
    http_status: Annotated[Count, Field(ge=100, le=599)] | None = None
    request_id: Name | None = None
    retry_after_ms: Count | None = None
    diagnostic_fields: tuple[Name, ...] = ()


@runtime_checkable
class ModelProvider(Protocol):
    def execute(self, request: ProviderRequest) -> ProviderResult | ProviderFailure: ...
