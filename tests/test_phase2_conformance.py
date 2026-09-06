"""Independent conformance checks for the Phase 2 OpenAI boundaries.

The fake objects below use only documented public SDK attributes. One test also
uses OpenAI 2.x over httpx.MockTransport to cover real request serialization.
"""
from __future__ import annotations

import ast
import json
import logging
import re
from pathlib import Path
import shutil

import httpx
import pytest
import yaml
from openai import OpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from model_router.classification import (
    MockClassifier, OpenAIClassifier, build_output_type, load_classifier_config,
)
from model_router.core.classifier_contracts import ClassificationFailure, ClassificationResult
from model_router.core.contracts import Effort, FailureType, Request
from model_router.core.provider_contracts import ProviderFailure, ProviderRequest, ProviderResult, ProviderUsage
from model_router.execution.openai_provider import OpenAIProvider
from model_router.policy.loader import load_bundle
from tests.phase2_fixtures import RecordingOpenAIClient, RawResponse, make_response, response_json

ROOT = Path(__file__).parents[1]
SECRET_INPUT = "prompt-secret-c0nformance"


class StructuredAnswer(BaseModel):
    answer: str


@pytest.fixture(scope="module")
def bundle():
    return load_bundle(ROOT / "config")


def provider_request(**changes):
    values = dict(
        task_id="task-c", trace_id="trace-c", invocation_id="invoke-c",
        policy_version="router-v1.0.0", catalog_version="models-v1.0.0",
        model_alias="luna", provider_model_id="gpt-5.6-luna",
        reasoning_effort=Effort.HIGH, input=SECRET_INPUT, instructions="system-secret-c",
        max_output_tokens=321, timeout_ms=4321, purpose="generation",
    )
    values.update(changes)
    return ProviderRequest(**values)


def task_request(text=SECRET_INPUT):
    return Request(task_id="task-c", trace_id="trace-c", input=text,
                   requirements=("text_input", "text_output"), consequence="low",
                   context={"input_tokens": 10, "expected_output_tokens": 5})


def wire_payload(bundle):
    flags = {name: False for name in build_output_type(bundle).model_fields["flags"].annotation.model_fields}
    return {
        "task_family": "analysis", "task_subclass": None,
        "components": {"reasoning_depth": 5, "step_dependency": 4,
                       "context_synthesis": 3, "technical_precision": 2,
                       "ambiguity": 1, "tool_orchestration": 0,
                       "reliability_requirement": 1},
        "confidence": 0.75, "flags": flags,
    }


def live_classifier_config(tmp_path, bundle):
    shutil.copy(ROOT / "config/classifier.yaml", tmp_path / "classifier.yaml")
    (tmp_path / "prompts").mkdir()
    shutil.copy(ROOT / "config/prompts/task-properties-v1.txt",
                tmp_path / "prompts/task-properties-v1.txt")
    raw = yaml.safe_load((tmp_path / "classifier.yaml").read_text())
    raw["live_enabled"] = True
    (tmp_path / "classifier.yaml").write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_classifier_config(tmp_path, bundle)


def test_text_request_is_exact_and_usage_buckets_are_disjoint(bundle):
    client = RecordingOpenAIClient(make_response())
    result = OpenAIProvider(bundle, client=client).execute(provider_request())

    assert isinstance(result, ProviderResult)
    assert client.option_calls == [{"max_retries": 0}]
    method, sent = client.calls[0]
    assert method == "create"
    assert sent == {
        "model": "gpt-5.6-luna", "reasoning": {"effort": "high"},
        "input": SECRET_INPUT, "instructions": "system-secret-c",
        "max_output_tokens": 321, "truncation": "disabled", "store": False,
        "service_tier": "default", "stream": False, "timeout": 4.321,
    }
    assert result.usage == ProviderUsage(
        input_tokens=100, cached_input_tokens=30, cache_write_input_tokens=20,
        output_tokens=22, reasoning_tokens=7, total_tokens=122)
    assert result.usage.uncached_input_tokens == 50
    # Reasoning is contained in output; normalized total remains the provider's 122.
    assert result.usage.total_tokens == result.usage.input_tokens + result.usage.output_tokens


def test_structured_call_uses_public_raw_parse_and_preserves_evidence(bundle):
    parsed = StructuredAnswer(answer="ok")
    normalized = make_response(parsed=parsed)
    raw = RawResponse(response_json(), parsed=normalized)
    client = RecordingOpenAIClient(raw)
    result = OpenAIProvider(bundle, client=client).execute(
        provider_request(output_type=StructuredAnswer))

    assert isinstance(result, ProviderResult)
    assert raw.parse_calls == 1
    method, sent = client.calls[0]
    assert method == "parse"
    assert sent["text_format"] is StructuredAnswer
    assert sent["reasoning"] == {"effort": "high"}
    assert sent["truncation"] == "disabled"
    assert result.structured_output == parsed
    assert (result.response_id, result.response_status) == ("resp_fixture", "completed")


def test_unsupported_effort_is_rejected_before_client_dispatch(bundle):
    client = RecordingOpenAIClient(make_response())
    result = OpenAIProvider(bundle, client=client).execute(provider_request(
        model_alias="astra", provider_model_id="gpt-6-astra", reasoning_effort=Effort.NONE))
    assert isinstance(result, ProviderFailure)
    assert result.failure_type is FailureType.CAPABILITY_FAILURE
    assert result.stage == "preflight"
    assert result.cause_code == "reasoning_effort_unsupported"
    assert client.option_calls == [] and client.calls == []


def test_invalid_usage_and_malformed_structured_output_keep_safe_evidence(bundle):
    envelope = response_json(response_id="resp_malformed")
    envelope["usage"]["output_tokens_details"]["reasoning_tokens"] = 99
    raw = RawResponse(envelope, parse_error=ValidationError.from_exception_data("wire", []))
    result = OpenAIProvider(bundle, client=RecordingOpenAIClient(raw)).execute(
        provider_request(output_type=StructuredAnswer))

    assert isinstance(result, ProviderFailure)
    assert result.failure_type is FailureType.MALFORMED_OUTPUT
    assert result.response_id == "resp_malformed"
    assert result.response_status == "completed"
    assert "usage" in result.diagnostic_fields
    assert result.usage.status == "unavailable"


def test_incomplete_structured_response_does_not_attempt_schema_parse(bundle):
    envelope = response_json(status="incomplete", response_id="resp_incomplete")
    envelope["incomplete_details"] = {"reason": "max_output_tokens"}
    raw = RawResponse(envelope, parse_error=AssertionError("must not parse incomplete"))
    result = OpenAIProvider(bundle, client=RecordingOpenAIClient(raw)).execute(
        provider_request(output_type=StructuredAnswer))
    assert isinstance(result, ProviderResult)
    assert raw.parse_calls == 0
    assert result.response_id == "resp_incomplete"
    assert result.response_status == "incomplete"
    assert result.incomplete_reason == "max_output_tokens"


def test_rate_limit_metadata_is_validated_and_error_content_is_private(bundle):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(429, request=request,
                              headers={"x-request-id": "req_safe-123", "retry-after": "1.25"})
    error = RateLimitError("secret-body-and-url", response=response,
                           body={"api_key": "sk-secret-error"})
    result = OpenAIProvider(bundle, client=RecordingOpenAIClient(error)).execute(provider_request())

    assert isinstance(result, ProviderFailure)
    assert result.failure_type is FailureType.RATE_LIMIT
    assert result.retryable is True
    assert result.http_status == 429
    assert result.request_id == "req_safe-123"
    assert result.retry_after_ms == 1250
    serialized = result.model_dump_json()
    assert "secret-body" not in serialized and "sk-secret" not in serialized
    assert "api.openai.com" not in serialized


def test_real_sdk_mock_transport_disables_retries_and_suppresses_debug_secrets(bundle, caplog):
    calls = []
    response_secret = "raw-response-secret-c"
    header_secret = "header-secret-c"

    def handler(request):
        calls.append(request)
        return httpx.Response(200, request=request,
                              headers={"x-request-id": header_secret},
                              json=response_json(text=response_secret))

    sdk = OpenAI(api_key="sk-test-secret-c", base_url="https://sdk.test/v1",
                 http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    caplog.set_level(logging.DEBUG)
    result = OpenAIProvider(bundle, client=sdk).execute(provider_request())

    assert isinstance(result, ProviderResult)
    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert body["model"] == "gpt-5.6-luna"
    assert body["reasoning"] == {"effort": "high"}
    assert body["truncation"] == "disabled"
    assert body["store"] is False
    assert body["stream"] is False
    timeout = calls[0].extensions["timeout"]
    assert all(value == pytest.approx(4.321) for value in timeout.values())
    evidence = repr(result) + result.model_dump_json() + caplog.text
    for secret in (SECRET_INPUT, "system-secret-c", response_secret,
                   header_secret, "sk-test-secret-c"):
        assert secret not in evidence


def test_sdk_imports_remain_confined_to_openai_adapter():
    offenders = []
    for path in (ROOT / "src/model_router").rglob("*.py"):
        if path.name == "openai_provider.py":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "openai" for alias in node.names):
                offenders.append(path)
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "openai":
                offenders.append(path)
    assert offenders == []


def test_classifier_schema_contains_task_properties_and_forbids_route_selection(bundle):
    output_type = build_output_type(bundle)
    schema = output_type.model_json_schema()
    assert set(output_type.model_fields) == {"task_family", "task_subclass", "components", "confidence", "flags"}
    for forbidden in ("model", "selected_model", "tier", "reasoning_effort",
                      "validation_level", "supplied_total", "total"):
        assert forbidden not in output_type.model_fields
    valid = wire_payload(bundle)
    assert output_type.model_validate(valid).task_family == "analysis"
    for mutation in (
        lambda value: value.update(selected_model="gpt-6-astra"),
        lambda value: value.update(task_family="unknown-family"),
        lambda value: value["flags"].update(unknown_flag=True),
        lambda value: value.update(confidence=1.1),
    ):
        candidate = json.loads(json.dumps(valid))
        mutation(candidate)
        with pytest.raises(ValidationError):
            output_type.model_validate(candidate)
    assert "additionalProperties" in json.dumps(schema)


def test_classifier_transmits_configured_route_but_model_cannot_author_one(tmp_path, bundle):
    config = live_classifier_config(tmp_path, bundle)

    class CaptureProvider:
        request = None
        def execute(self, request):
            self.request = request
            parsed = request.output_type.model_validate(wire_payload(bundle))
            return ProviderResult(
                task_id=request.task_id, trace_id=request.trace_id,
                invocation_id=request.invocation_id, policy_version=request.policy_version,
                catalog_version=request.catalog_version, model_alias=request.model_alias,
                provider_model_id=request.provider_model_id,
                reasoning_effort=request.reasoning_effort, purpose="classification",
                response_id="resp_classifier", response_status="completed",
                returned_model_id=request.provider_model_id, latency_ms=1,
                usage=ProviderUsage(input_tokens=10, output_tokens=5, total_tokens=15),
                structured_output=parsed)

    provider = CaptureProvider()
    result = OpenAIClassifier(provider, bundle, config).classify(task_request())
    assert isinstance(result, ClassificationResult)
    sent = provider.request
    assert sent.purpose == "classification"
    assert sent.reasoning_effort == config.reasoning_effort
    assert sent.output_type is not None
    assert sent.truncation == "disabled"
    assert sent.input == SECRET_INPUT and sent.instructions == config.prompt_text
    assert result.classification.task_family == "analysis"
    assert result.classification.provenance.startswith(config.version)
    assert result.provider_result.usage.total_tokens == 15


def test_classifier_malformed_diagnostics_do_not_echo_raw_values(bundle):
    config = load_classifier_config(ROOT / "config", bundle)
    malicious = wire_payload(bundle)
    malicious["selected_model"] = "sk-secret-route-injection"
    result = MockClassifier([malicious], bundle, config).classify(task_request())
    assert isinstance(result, ClassificationFailure)
    assert result.failure_type is FailureType.MALFORMED_OUTPUT
    assert result.cause_code == "CLASSIFIER_OUTPUT_SCHEMA_INVALID"
    serialized = repr(result) + result.model_dump_json()
    assert "sk-secret-route-injection" not in serialized
    assert "selected_model" not in serialized


def test_classifier_prompt_describes_properties_without_model_recommendations():
    prompt = (ROOT / "config/prompts/task-properties-v1.txt").read_text().lower()
    assert "task properties" in prompt
    for forbidden in ("gpt-", "select a model", "complexity band"):
        assert forbidden not in prompt
    for model_name in ("luna", "terra", "sol", "astra"):
        assert re.search(rf"\b{model_name}\b", prompt) is None
