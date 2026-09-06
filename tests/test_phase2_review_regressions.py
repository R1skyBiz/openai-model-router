"""Regressions found during integrated Phase 2 review."""

from pathlib import Path
import os
import subprocess
import sys

import httpx
from openai import BadRequestError, RateLimitError
import pytest

from model_router.core.contracts import FailureType
from model_router.core.provider_contracts import ProviderFailure, ProviderRequest
from model_router.execution.openai_provider import OpenAIProvider
from model_router.policy.loader import load_bundle
from pydantic import BaseModel
from tests.phase2_fixtures import RecordingOpenAIClient, RawResponse, make_response


def invoke(outcome, **request_changes):
    bundle = load_bundle(Path(__file__).resolve().parents[1] / "config")
    alias, model = next(iter(bundle.catalog["models"].items()))
    values = dict(task_id="review", trace_id="review", invocation_id="review",
        policy_version=bundle.policy["version"], catalog_version=bundle.catalog["catalog_version"],
        model_alias=alias, provider_model_id=model["provider_model_id"],
        reasoning_effort=model["reasoning_efforts"][0], input="test",
        max_output_tokens=10, timeout_ms=1000)
    request = ProviderRequest(**(values | request_changes))
    return OpenAIProvider(bundle, client=RecordingOpenAIClient(outcome)).execute(request)


@pytest.mark.parametrize("headers", [
    {"retry-after-ms": "9" * 5000}, {"retry-after": "1e999999999"},
    {"retry-after": "9" * 5000}, {"retry-after": "NaN"},
    {"retry-after-ms": str(2**63)}, {"retry-after": "-1"},
])
def test_untrusted_retry_header_cannot_escape_normalization(headers):
    error = RateLimitError("raw-secret-message", response=httpx.Response(429, headers=headers,
        request=httpx.Request("POST", "https://example.test/responses")), body=None)
    result = invoke(error)
    assert isinstance(result, ProviderFailure)
    assert result.failure_type == FailureType.RATE_LIMIT
    assert result.retry_after_ms is None
    assert "raw-secret" not in result.model_dump_json()


@pytest.mark.parametrize("body,expected", [
    ({"code": "invalid_json_schema", "param": "text.format"}, FailureType.UNKNOWN_FAILURE),
    ({"code": "unsupported_value", "param": "temperature"}, FailureType.UNKNOWN_FAILURE),
    ({"code": "unsupported_value", "param": "reasoning.effort"}, FailureType.CAPABILITY_FAILURE),
    ({"code": "model_not_found", "param": "model"}, FailureType.CAPABILITY_FAILURE),
])
def test_capability_failure_requires_specific_evidence(body, expected):
    error = BadRequestError("raw-secret-message", response=httpx.Response(400,
        request=httpx.Request("POST", "https://example.test/responses")), body=body)
    result = invoke(error)
    assert result.failure_type == expected
    assert "raw-secret" not in result.model_dump_json()


def test_identifier_prefix_does_not_allow_embedded_api_key():
    result = invoke(make_response(response_id="resp_sk-private-test-credential"))
    assert isinstance(result, ProviderFailure)
    assert result.response_id is None
    assert "sk-private" not in result.model_dump_json()


def test_returned_model_identity_has_no_python_model_registry():
    result = invoke(make_response(model="future-configured-provider-snapshot"))
    assert result.returned_model_id == "future-configured-provider-snapshot"


def test_malformed_structured_envelope_keeps_paid_evidence():
    class Answer(BaseModel):
        answer: str

    envelope = {"id": "resp_bad", "status": "completed", "model": "configured-model",
                "output": 123, "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}}
    raw = RawResponse(envelope)
    result = invoke(raw, output_type=Answer)
    assert result.failure_type == FailureType.MALFORMED_OUTPUT
    assert result.stage == "normalization"
    assert result.response_id == "resp_bad"
    assert result.usage.total_tokens == 6
    assert raw.parse_calls == 0


@pytest.mark.parametrize("usage", [123, "invalid", []])
def test_wrong_usage_object_shape_is_malformed(usage):
    response = make_response()
    response.usage = usage
    result = invoke(response)
    assert result.failure_type == FailureType.MALFORMED_OUTPUT
    assert result.response_id == "resp_fixture"


def test_unrepresentable_timeout_is_rejected_before_dispatch():
    def forbidden_call(_):
        raise AssertionError("client dispatch must not happen")

    result = invoke(forbidden_call, timeout_ms=10**400)
    assert isinstance(result, ProviderFailure)
    assert result.stage == "preflight"
    assert result.cause_code == "timeout_not_representable"


def test_first_sdk_import_with_debug_logging_cannot_leak_content():
    root = Path(__file__).resolve().parents[1]
    program = '''
import json, socket
def no_network(*args, **kwargs):
    raise AssertionError("network forbidden")
socket.socket.connect = no_network
socket.create_connection = no_network
from model_router.policy.loader import load_bundle
from model_router.core.provider_contracts import ProviderRequest, ProviderResult
from model_router.execution.openai_provider import OpenAIProvider
class LazyClient:
    def with_options(self, **options):
        import httpx
        from openai import OpenAI
        def response(request):
            return httpx.Response(200, json={
                "id":"resp_private", "status":"completed", "object":"response",
                "created_at":1, "model":"gpt-5.6-luna", "error":None,
                "output":[{"id":"msg_private", "type":"message", "role":"assistant",
                    "status":"completed", "content":[{"type":"output_text", "text":"ok", "annotations":[]}]}],
                "parallel_tool_calls":False, "tool_choice":"auto", "tools":[]})
        return OpenAI(api_key="sk-fake-only", http_client=httpx.Client(
            transport=httpx.MockTransport(response))).with_options(**options)
bundle = load_bundle("config")
request = ProviderRequest(task_id="logtest", trace_id="logtest", invocation_id="logtest",
    policy_version=bundle.policy["version"], catalog_version=bundle.catalog["catalog_version"],
    model_alias="luna", provider_model_id=bundle.catalog["models"]["luna"]["provider_model_id"],
    reasoning_effort="low", input="PROMPT_SECRET_X", instructions="INSTRUCTION_SECRET_X",
    max_output_tokens=16, timeout_ms=1000)
assert isinstance(OpenAIProvider(bundle, client=LazyClient()).execute(request), ProviderResult)
'''
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["OPENAI_LOG"] = "debug"
    environment.pop("OPENAI_API_KEY", None)
    result = subprocess.run([sys.executable, "-c", program], cwd=root, env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "SECRET_X" not in result.stdout + result.stderr
    assert "sk-fake-only" not in result.stdout + result.stderr
