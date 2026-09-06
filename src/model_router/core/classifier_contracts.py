"""Classifier results characterize tasks and retain invocation accounting."""

from typing import Literal, Protocol, runtime_checkable

from model_router.core.contracts import Classification, FailureType, Name, Record, Request
from model_router.core.provider_contracts import ProviderFailure, ProviderResult


class ClassificationResult(Record):
    outcome: Literal["classification"] = "classification"
    classification: Classification
    classifier_version: Name
    prompt_version: Name
    schema_version: Name
    configuration_hash: Name
    provider_result: ProviderResult | None = None


class ClassificationFailure(Record):
    outcome: Literal["failure"] = "failure"
    task_id: Name
    trace_id: Name
    classifier_version: Name
    prompt_version: Name
    schema_version: Name
    configuration_hash: Name
    failure_type: FailureType
    cause_code: Name
    diagnostic_fields: tuple[Name, ...] = ()
    provider_result: ProviderResult | ProviderFailure | None = None


@runtime_checkable
class Classifier(Protocol):
    def classify(self, request: Request) -> ClassificationResult | ClassificationFailure: ...
