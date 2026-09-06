from types import SimpleNamespace
import httpx
from pydantic import BaseModel
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
import pytest
from model_router.core.contracts import FailureType
from model_router.execution.openai_provider import OpenAIProvider
from model_router.execution.provider import MockProvider, ProviderFailure, ProviderRequest, ProviderResult, ProviderUsage
from model_router.policy.loader import load_bundle

class Structured(BaseModel):
    answer: str

class RawResponse:
    def __init__(self, envelope, parsed=None, error=None):
        self.http_response = SimpleNamespace(json=lambda: envelope)
        self._parsed, self._error = parsed, error
        self.parse_calls = 0
    def parse(self):
        self.parse_calls += 1
        if self._error:
            raise self._error
        return self._parsed

class Responses:
    def __init__(self, *, response=None, raw=None):
        self.response, self.raw = response, raw
        self.calls = []
        self.with_raw_response = self
    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response
    def parse(self, **kwargs):
        self.calls.append(("parse", kwargs))
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw

class Client:
    def __init__(self, responses):
        self.responses = responses
        self.options = []
    def with_options(self, **kwargs):
        self.options.append(kwargs)
        return self

def request(bundle, **changes):
    values = dict(task_id="task", trace_id="trace", invocation_id="inv-1",
        policy_version=bundle.policy["version"], catalog_version=bundle.catalog["catalog_version"],
        model_alias="luna", provider_model_id="gpt-5.6-luna", reasoning_effort="low",
        input="private prompt", instructions="private instructions", max_output_tokens=100,
        timeout_ms=2500)
    values.update(changes)
    return ProviderRequest(**values)

def response(**changes):
    values = dict(id="resp-1", status="completed", model="gpt-5.6-luna", output_text="ok",
        output=[], incomplete_details=None,
        usage=SimpleNamespace(input_tokens=20,
            input_tokens_details=SimpleNamespace(cached_tokens=3, cache_write_tokens=2),
            output_tokens=7, output_tokens_details=SimpleNamespace(reasoning_tokens=4), total_tokens=27))
    values.update(changes)
    return SimpleNamespace(**values)

def test_text_request_has_explicit_safety_and_cost_parameters():
    bundle = load_bundle("config")
    responses = Responses(response=response())
    client = Client(responses)
    result = OpenAIProvider(bundle, client=client).execute(request(bundle))
    assert isinstance(result, ProviderResult)
    assert result.text == "ok"
    assert result.usage == ProviderUsage(input_tokens=20, cached_input_tokens=3,
        cache_write_input_tokens=2, output_tokens=7, reasoning_tokens=4, total_tokens=27)
    assert client.options == [{"max_retries": 0}]
    method, kwargs = responses.calls[0]
    assert method == "create"
    assert kwargs == {"model": "gpt-5.6-luna", "reasoning": {"effort": "low"},
        "input": "private prompt", "instructions": "private instructions", "max_output_tokens": 100,
        "truncation": "disabled", "store": False, "service_tier": "default", "stream": False,
        "timeout": 2.5}

def test_structured_uses_raw_response_and_returns_parsed_model():
    bundle = load_bundle("config")
    parsed = response(output_parsed=Structured(answer="yes"))
    envelope = {"id": "resp-1", "status": "completed", "model": "gpt-5.6-luna", "output": []}
    raw = RawResponse(envelope, parsed)
    responses = Responses(raw=raw)
    result = OpenAIProvider(bundle, client=Client(responses)).execute(request(bundle, output_type=Structured))
    assert isinstance(result, ProviderResult)
    assert result.structured_output == Structured(answer="yes")
    assert raw.parse_calls == 1
    method, kwargs = responses.calls[0]
    assert method == "parse" and kwargs.pop("text_format") is Structured

def test_malformed_structured_output_preserves_safe_paid_evidence():
    bundle = load_bundle("config")
    envelope = {"id": "resp-malformed", "status": "completed", "model": "gpt-5.6-luna", "output": [],
        "usage": {"input_tokens": 4, "input_tokens_details": {"cached_tokens": 1, "cache_write_tokens": 1},
                  "output_tokens": 2, "output_tokens_details": {"reasoning_tokens": 1}, "total_tokens": 6}}
    result = OpenAIProvider(bundle, client=Client(Responses(raw=RawResponse(envelope, error=ValueError("raw secret"))))).execute(
        request(bundle, output_type=Structured))
    assert isinstance(result, ProviderFailure)
    assert result.failure_type == FailureType.MALFORMED_OUTPUT
    assert (result.response_id, result.response_status, result.returned_model_id) == ("resp-malformed", "completed", "gpt-5.6-luna")
    assert result.usage.total_tokens == 6
    assert "raw secret" not in repr(result)

def test_incomplete_and_refusal_are_results_without_parsing_content():
    bundle = load_bundle("config")
    incomplete = {"id": "resp-incomplete", "status": "incomplete", "model": "gpt-5.6-luna",
        "incomplete_details": {"reason": "max_output_tokens"}, "output": [], "usage": None}
    raw = RawResponse(incomplete, error=AssertionError("must not parse"))
    result = OpenAIProvider(bundle, client=Client(Responses(raw=raw))).execute(request(bundle, output_type=Structured))
    assert isinstance(result, ProviderResult)
    assert result.incomplete_reason == "max_output_tokens" and raw.parse_calls == 0

    refusal = {"id": "resp-refusal", "status": "completed", "model": "gpt-5.6-luna",
        "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "private refusal"}]}], "usage": None}
    result = OpenAIProvider(bundle, client=Client(Responses(raw=RawResponse(refusal)))).execute(request(bundle, output_type=Structured))
    assert isinstance(result, ProviderResult) and result.refused
    assert "private refusal" not in repr(result) and "private refusal" not in str(result.model_dump())

def test_preflight_rejects_before_client_dispatch():
    bundle = load_bundle("config")
    client = Client(Responses(response=response()))
    result = OpenAIProvider(bundle, client=client).execute(request(bundle, model_alias="missing"))
    assert isinstance(result, ProviderFailure)
    assert result.failure_type == FailureType.CAPABILITY_FAILURE
    assert client.options == []

def test_rate_limit_retains_only_safe_retry_metadata():
    bundle = load_bundle("config")
    http_response = httpx.Response(429, headers={"x-request-id": "req-safe", "retry-after": "1.25"},
        request=httpx.Request("POST", "https://secret.example"))
    error = RateLimitError("secret body sk-private", response=http_response, body={"secret": "sk-private"})
    result = OpenAIProvider(bundle, client=Client(Responses(response=error))).execute(request(bundle))
    assert isinstance(result, ProviderFailure)
    assert result.failure_type == FailureType.RATE_LIMIT and result.retryable
    assert (result.http_status, result.request_id, result.retry_after_ms) == (429, "req-safe", 1250)
    serialized = repr(result) + str(result.model_dump())
    assert "sk-private" not in serialized and "secret.example" not in serialized

def test_invalid_usage_is_malformed_instead_of_silently_unknown():
    bundle = load_bundle("config")
    invalid = response(usage=SimpleNamespace(input_tokens=-1, input_tokens_details=None,
        output_tokens=1, output_tokens_details=None, total_tokens=0))
    result = OpenAIProvider(bundle, client=Client(Responses(response=invalid))).execute(request(bundle))
    assert isinstance(result, ProviderFailure)
    assert result.failure_type == FailureType.MALFORMED_OUTPUT
    assert "usage" in result.diagnostic_fields

def test_mock_records_no_content_and_exhaustion_is_explicit():
    bundle = load_bundle("config")
    expected = ProviderResult(**{k: v for k, v in {
        "task_id":"task", "trace_id":"trace", "invocation_id":"inv-1", "policy_version":bundle.policy["version"],
        "catalog_version":bundle.catalog["catalog_version"], "model_alias":"luna", "provider_model_id":"gpt-5.6-luna",
        "reasoning_effort":"low", "purpose":"generation", "latency_ms":0.0}.items()}, text="private output")
    provider = MockProvider([expected])
    assert provider.execute(request(bundle)) is expected
    assert "private prompt" not in repr(provider.requests) and "private instructions" not in repr(provider.requests)
    exhausted = provider.execute(request(bundle))
    assert isinstance(exhausted, ProviderFailure) and exhausted.cause_code == "mock_script_exhausted"

def test_missing_wire_identity_or_status_is_malformed():
    bundle = load_bundle("config")
    missing_status = response(status=None)
    result = OpenAIProvider(bundle, client=Client(Responses(response=missing_status))).execute(request(bundle))
    assert isinstance(result, ProviderFailure) and result.failure_type == FailureType.MALFORMED_OUTPUT
    invalid_id = response(id="secret-response")
    result = OpenAIProvider(bundle, client=Client(Responses(response=invalid_id))).execute(request(bundle))
    assert isinstance(result, ProviderFailure) and result.response_id is None

def test_invalid_raw_envelope_is_malformed():
    bundle = load_bundle("config")
    raw = RawResponse({})
    raw.http_response = SimpleNamespace(json=lambda: (_ for _ in ()).throw(ValueError("private body")))
    result = OpenAIProvider(bundle, client=Client(Responses(raw=raw))).execute(request(bundle, output_type=Structured))
    assert isinstance(result, ProviderFailure)
    assert result.failure_type == FailureType.MALFORMED_OUTPUT and result.stage == "normalization"
    assert "private body" not in repr(result)

def test_sdk_debug_logging_is_suppressed_during_invocation(caplog):
    import logging
    bundle = load_bundle("config")
    class LoggingResponses(Responses):
        def create(self, **kwargs):
            logging.getLogger("openai._base_client.explicit").debug("secret %s", kwargs["input"])
            return super().create(**kwargs)
    logger = logging.getLogger("openai._base_client.explicit")
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        with caplog.at_level(logging.DEBUG):
            result = OpenAIProvider(bundle, client=Client(LoggingResponses(response=response()))).execute(request(bundle))
    finally:
        logger.setLevel(old_level)
    assert isinstance(result, ProviderResult)
    assert "private prompt" not in caplog.text


@pytest.mark.parametrize("kind,expected", [
    ("timeout", FailureType.TIMEOUT),
    ("connection", FailureType.PROVIDER_FAILURE),
    ("server", FailureType.PROVIDER_FAILURE),
])
def test_sdk_infrastructure_failures_normalize_without_retry_or_escalation(kind, expected):
    bundle = load_bundle("config")
    wire_request = httpx.Request("POST", "https://example.test/responses")
    if kind == "timeout":
        error = APITimeoutError(request=wire_request)
    elif kind == "connection":
        error = APIConnectionError(message="private connection diagnostic", request=wire_request)
    else:
        error = InternalServerError("private server diagnostic", body=None,
            response=httpx.Response(503, request=wire_request, headers={"x-request-id": "req_outage"}))
    responses = Responses(response=error)
    client = Client(responses)
    result = OpenAIProvider(bundle, client=client).execute(request(bundle))
    assert isinstance(result, ProviderFailure)
    assert result.failure_type == expected
    assert result.source == "provider" and result.retryable
    assert result.stage == "invocation"
    assert len(responses.calls) == 1
    assert client.options == [{"max_retries": 0}]
    assert result.model_alias == "luna" and result.reasoning_effort.value == "low"
    assert "private" not in result.model_dump_json()
    if kind == "server":
        assert (result.http_status, result.request_id) == (503, "req_outage")


def test_mock_scripts_all_required_outcomes_and_preserves_partial_usage():
    bundle = load_bundle("config")
    sent = request(bundle)
    evidence = {key: value for key, value in sent.model_dump().items()
                if key not in {"max_output_tokens", "timeout_ms", "truncation"}}
    evidence["latency_ms"] = 1.0
    partial = ProviderUsage(input_tokens=10, output_tokens=3, total_tokens=13)
    scripted = [
        ProviderResult(**evidence, response_status="completed", text="ok", usage=partial),
        ProviderResult(**evidence, response_status="incomplete", incomplete_reason="max_output_tokens", usage=partial),
        *[ProviderFailure(**evidence, failure_type=kind, source="provider",
            stage="invocation", cause_code="scripted", usage=partial)
          for kind in (FailureType.MALFORMED_OUTPUT, FailureType.TIMEOUT,
                       FailureType.RATE_LIMIT, FailureType.PROVIDER_FAILURE)],
    ]
    mock = MockProvider(scripted)
    for expected in scripted:
        assert mock.execute(sent) is expected
        assert expected.usage.cached_input_tokens is None
        assert expected.usage.cache_write_input_tokens is None
        assert expected.usage.reasoning_tokens is None
    assert mock.call_count == len(scripted)
