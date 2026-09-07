"""OpenAI Responses API adapter for exactly one synchronous invocation."""
from __future__ import annotations
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Context as DecimalContext, Decimal, DecimalException, ROUND_CEILING, localcontext
import logging
from json import JSONDecodeError
from math import isfinite
import os
import re
from time import monotonic
from threading import Lock
from typing import Any
from pydantic import ValidationError
from model_router.core.configuration import PolicyBundle
from model_router.core.contracts import FailureType
from model_router.core.provider_contracts import ProviderFailure, ProviderRequest, ProviderResult, ProviderUsage
from .provider import request_evidence

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_STATUSES = {"completed", "failed", "in_progress", "cancelled", "queued", "incomplete"}

def _read(value: object, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)

def _safe_identifier(value: object, *, kind: str) -> str | None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        return None
    lowered = value.lower()
    if "sk-" in lowered or lowered.startswith(("bearer", "secret", "token")):
        return None
    if kind == "response" and not lowered.startswith(("resp_", "resp-")):
        return None
    if kind == "request" and not (lowered.startswith(("req_", "req-", "request_", "request-")) or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27,}", lowered)):
        return None
    return value

def _safe_status(value: object) -> str | None:
    return value if isinstance(value, str) and value in _STATUSES else None

def _count(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ValueError("provider token count is invalid")
    return value

def _usage(response: object | None) -> ProviderUsage:
    raw = _read(response, "usage") if response is not None else None
    if raw is None:
        return ProviderUsage()
    if not isinstance(raw, Mapping) and not hasattr(raw, "__dict__"):
        raise TypeError("provider usage must be an object")
    input_details = _read(raw, "input_tokens_details")
    output_details = _read(raw, "output_tokens_details")
    for details in (input_details, output_details):
        if details is not None and not isinstance(details, Mapping) and not hasattr(details, "__dict__"):
            raise TypeError("provider token details must be an object")
    return ProviderUsage(
        input_tokens=_count(_read(raw, "input_tokens")),
        cached_input_tokens=_count(_read(input_details, "cached_tokens")),
        cache_write_input_tokens=_count(_read(input_details, "cache_write_tokens")),
        output_tokens=_count(_read(raw, "output_tokens")),
        reasoning_tokens=_count(_read(output_details, "reasoning_tokens")),
        total_tokens=_count(_read(raw, "total_tokens")),
    )

def _response_fields(response: object | None) -> dict[str, object]:
    status = _safe_status(_read(response, "status")) if response is not None else None
    return {
        "response_id": _safe_identifier(_read(response, "id"), kind="response") if response is not None else None,
        "response_status": status,
        "returned_model_id": _safe_identifier(_read(response, "model"), kind="model") if response is not None else None,
        "returned_service_tier": (_read(response, "service_tier")
            if _read(response, "service_tier") in ("default", "flex", "priority", "auto", "scale") else None),
        "usage": _usage(response),
    }

def _failure(request: ProviderRequest, *, failure_type: FailureType, source: str,
             stage: str, cause_code: str, latency_ms: float = 0.0,
             response: object | None = None, retryable: bool = False,
             http_status: int | None = None, request_id: str | None = None,
             retry_after_ms: int | None = None,
             diagnostic_fields: tuple[str, ...] = ()) -> ProviderFailure:
    try:
        response_fields = _response_fields(response)
    except (ValidationError, ValueError, TypeError):
        response_fields = {"response_id": _safe_identifier(_read(response, "id"), kind="response"),
            "response_status": _safe_status(_read(response, "status")),
            "returned_model_id": _safe_identifier(_read(response, "model"), kind="model"), "usage": ProviderUsage()}
        diagnostic_fields = tuple(dict.fromkeys((*diagnostic_fields, "usage")))
    return ProviderFailure(**request_evidence(request, latency_ms), **response_fields,
        failure_type=failure_type, source=source, stage=stage, cause_code=cause_code,
        retryable=retryable, http_status=http_status, request_id=request_id,
        retry_after_ms=retry_after_ms, diagnostic_fields=diagnostic_fields)

def _preflight(request: ProviderRequest, bundle: PolicyBundle) -> ProviderFailure | None:
    reject = lambda failure_type, code, fields: _failure(request, failure_type=failure_type,
        source="adapter", stage="preflight", cause_code=code, diagnostic_fields=fields)
    try:
        timeout_finite = isfinite(request.timeout_ms / 1000)
    except OverflowError:
        timeout_finite = False
    if not timeout_finite:
        return reject(FailureType.CAPABILITY_FAILURE, "timeout_not_representable", ("timeout_ms",))
    if request.policy_version != bundle.policy.get("version"):
        return reject(FailureType.UNKNOWN_FAILURE, "policy_version_mismatch", ("policy_version",))
    if request.catalog_version != bundle.catalog.get("catalog_version"):
        return reject(FailureType.UNKNOWN_FAILURE, "catalog_version_mismatch", ("catalog_version",))
    if bundle.catalog.get("provider") != "openai":
        return reject(FailureType.CAPABILITY_FAILURE, "provider_unsupported", ("provider",))
    model = bundle.catalog.get("models", {}).get(request.model_alias)
    if model is None:
        return reject(FailureType.CAPABILITY_FAILURE, "model_alias_unknown", ("model_alias",))
    if model.get("provider_model_id") != request.provider_model_id:
        return reject(FailureType.CAPABILITY_FAILURE, "provider_model_id_mismatch", ("provider_model_id",))
    availability = model.get("availability", {})
    if availability.get("configured_enabled") is not True or availability.get("account_status") == "unavailable":
        return reject(FailureType.CAPABILITY_FAILURE, "model_disabled", ("availability",))
    capabilities = model.get("capabilities", {})
    if capabilities.get("text_input") is not True or capabilities.get("text_output") is not True:
        return reject(FailureType.CAPABILITY_FAILURE, "text_capability_unsupported", ("capabilities",))
    if request.output_type is not None and capabilities.get("structured_outputs") is not True:
        return reject(FailureType.CAPABILITY_FAILURE, "structured_output_unsupported", ("structured_outputs",))
    if request.reasoning_effort.value not in model.get("reasoning_efforts", ()):
        return reject(FailureType.CAPABILITY_FAILURE, "reasoning_effort_unsupported", ("reasoning_effort",))
    configured_max = model.get("max_output_tokens")
    context_window = model.get("context_window_tokens")
    if type(configured_max) is not int or type(context_window) is not int:
        return reject(FailureType.UNKNOWN_FAILURE, "catalog_limits_invalid", ("max_output_tokens", "context_window_tokens"))
    if request.max_output_tokens > min(configured_max, context_window):
        return reject(FailureType.CAPABILITY_FAILURE, "max_output_tokens_unsupported", ("max_output_tokens",))
    return None

def _headers(response: object | None) -> Mapping[str, object]:
    headers = _read(response, "headers", {}) if response is not None else {}
    return headers if isinstance(headers, Mapping) else {}

def _numeric_retry_after_ms(headers: Mapping[str, object]) -> int | None:
    direct = headers.get("retry-after-ms") or headers.get("Retry-After-Ms")
    # Representation bounds protect decoding of untrusted headers; these are
    # not operational retry ceilings or a backoff policy.
    largest_ms = 2**63 - 1
    if isinstance(direct, str) and len(direct) <= 19 and direct.isascii() and direct.isdigit():
        value = int(direct)
        return value if value <= largest_ms else None
    seconds = headers.get("retry-after") or headers.get("Retry-After")
    if not isinstance(seconds, str) or len(seconds) > 128 or not seconds.isascii():
        return None
    try:
        with localcontext(DecimalContext(prec=40)):
            value = Decimal(seconds)
            if not value.is_finite() or value < 0 or value > Decimal(largest_ms) / 1000:
                return None
            return int((value * 1000).to_integral_value(rounding=ROUND_CEILING))
    except (DecimalException, ValueError, OverflowError):
        return None

_LOG_SUPPRESSION_ACTIVE: ContextVar[bool] = ContextVar("model_router_sdk_log_suppression", default=False)
_LOG_FILTER_LOCK = Lock()
_LOG_FILTER_USERS = 0
_LOG_FILTER_HANDLERS: set[logging.Handler] = set()

class _SDKLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        sensitive_logger = record.name == "openai" or record.name.startswith("openai.")
        sensitive_logger |= record.name == "httpx" or record.name.startswith("httpx.")
        sensitive_logger |= record.name == "httpcore" or record.name.startswith("httpcore.")
        return not (_LOG_SUPPRESSION_ACTIVE.get() and sensitive_logger)

_SDK_LOG_FILTER = _SDKLogFilter()

def _logging_handlers() -> set[logging.Handler]:
    handlers = set(logging.getLogger().handlers)
    for value in logging.Logger.manager.loggerDict.values():
        if isinstance(value, logging.Logger):
            handlers.update(value.handlers)
    return handlers

@contextmanager
def _quiet_sdk_logs():
    global _LOG_FILTER_USERS
    with _LOG_FILTER_LOCK:
        for handler in _logging_handlers():
            if handler not in _LOG_FILTER_HANDLERS:
                handler.addFilter(_SDK_LOG_FILTER)
                _LOG_FILTER_HANDLERS.add(handler)
        _LOG_FILTER_USERS += 1
    token = _LOG_SUPPRESSION_ACTIVE.set(True)
    try:
        yield
    finally:
        _LOG_SUPPRESSION_ACTIVE.reset(token)
        with _LOG_FILTER_LOCK:
            _LOG_FILTER_USERS -= 1
            if _LOG_FILTER_USERS == 0:
                for handler in _LOG_FILTER_HANDLERS:
                    handler.removeFilter(_SDK_LOG_FILTER)
                _LOG_FILTER_HANDLERS.clear()

def _exception_failure(request: ProviderRequest, error: Exception, latency_ms: float) -> ProviderFailure:
    from openai import APIConnectionError, APIResponseValidationError, APIStatusError, APITimeoutError, RateLimitError
    response = getattr(error, "response", None)
    raw_status = getattr(error, "status_code", None)
    status = raw_status if type(raw_status) is int and 100 <= raw_status <= 599 else None
    headers = _headers(response)
    request_id = _safe_identifier(getattr(error, "request_id", None), kind="request")
    if request_id is None:
        request_id = _safe_identifier(headers.get("x-request-id") or headers.get("X-Request-Id"), kind="request")
    retry_after_ms = _numeric_retry_after_ms(headers)
    error_code = getattr(error, "code", None)
    error_param = getattr(error, "param", None)
    if isinstance(error, (JSONDecodeError, ValidationError, APIResponseValidationError)):
        failure_type, code, retryable = FailureType.MALFORMED_OUTPUT, "response_envelope_invalid", False
    elif isinstance(error, APITimeoutError) or status in {408, 504}:
        failure_type, code, retryable = FailureType.TIMEOUT, "provider_timeout", True
    elif isinstance(error, RateLimitError) or status == 429:
        failure_type, code, retryable = FailureType.RATE_LIMIT, "provider_rate_limit", True
    elif isinstance(error, APIConnectionError):
        failure_type, code, retryable = FailureType.PROVIDER_FAILURE, "provider_connection", True
    elif isinstance(error, APIStatusError) and (
        error_code in ("model_not_found", "invalid_model", "unsupported_model") or
        error_code == "unsupported_value" and error_param in ("model", "reasoning.effort")
    ):
        failure_type, code, retryable = FailureType.CAPABILITY_FAILURE, "provider_request_unsupported", False
    elif isinstance(error, APIStatusError) and status in {400, 404, 422}:
        failure_type, code, retryable = FailureType.UNKNOWN_FAILURE, "provider_request_rejected", False
    elif isinstance(error, APIStatusError):
        failure_type, code, retryable = FailureType.PROVIDER_FAILURE, "provider_http_error", bool(status and status >= 500)
    else:
        failure_type, code, retryable = FailureType.UNKNOWN_FAILURE, "provider_exception", False
    return _failure(request, failure_type=failure_type,
        source="provider" if isinstance(error, (APIStatusError, APIConnectionError, APITimeoutError)) else "adapter",
        stage="normalization" if failure_type == FailureType.MALFORMED_OUTPUT else "invocation",
        cause_code=code, latency_ms=latency_ms,
        retryable=retryable, http_status=status, request_id=request_id,
        retry_after_ms=retry_after_ms)

def _refused(response: object) -> bool:
    for output in _read(response, "output", ()) or ():
        for content in _read(output, "content", ()) or ():
            if _read(content, "type") == "refusal":
                return True
    return False

def _incomplete_reason(response: object) -> str | None:
    if _read(response, "status") != "incomplete":
        return None
    reason = _read(_read(response, "incomplete_details"), "reason")
    return reason if reason in {"max_output_tokens", "content_filter"} else "unknown"

def _raw_envelope(raw_response: object) -> Mapping[str, object]:
    http_response = _read(raw_response, "http_response")
    envelope = http_response.json()
    if not isinstance(envelope, Mapping):
        raise TypeError("provider response envelope is not an object")
    return envelope

class OpenAIProvider:
    """Translate one provider request to one Responses API invocation."""
    def __init__(self, bundle: PolicyBundle, *, client: object | None = None, api_key: str | None = None):
        self._bundle = bundle
        self._client = client
        self._api_key = api_key

    def _base_client(self) -> object:
        # Finish the SDK's environment-controlled logging setup before the
        # invocation filter snapshots handlers, including for lazy test clients.
        from openai import OpenAI
        if self._client is not None:
            return self._client
        if os.environ.get("RUN_LIVE_OPENAI_TESTS") != "1":
            raise RuntimeError("live_provider_disabled")
        self._client = OpenAI(api_key=self._api_key, max_retries=0)
        return self._client

    def execute(self, request: ProviderRequest) -> ProviderResult | ProviderFailure:
        rejected = _preflight(request, self._bundle)
        if rejected is not None:
            return rejected
        started = monotonic()
        kwargs = {
            "model": request.provider_model_id,
            "reasoning": {"effort": request.reasoning_effort.value},
            "input": request.input,
            "instructions": request.instructions,
            "max_output_tokens": request.max_output_tokens,
            "truncation": "disabled", "store": False, "service_tier": "default",
            "stream": False, "timeout": request.timeout_ms / 1000,
        }
        try:
            # SDK import may install logging handlers via OPENAI_LOG. Initialize
            # it before taking the handler snapshot; no request content is given
            # to the client constructor.
            base_client = self._base_client()
            with _quiet_sdk_logs():
                client = base_client.with_options(max_retries=0)
                if request.output_type is None:
                    response = client.responses.create(**kwargs)
                else:
                    raw = client.responses.with_raw_response.parse(text_format=request.output_type, **kwargs)
                    envelope = None
                    try:
                        envelope = _raw_envelope(raw)
                        incomplete_or_refused = _read(envelope, "status") == "incomplete" or _refused(envelope)
                    except (ValueError, TypeError, AttributeError):
                        return _failure(request, failure_type=FailureType.MALFORMED_OUTPUT,
                            source="adapter", stage="normalization", cause_code="response_envelope_invalid",
                            latency_ms=(monotonic() - started) * 1000, response=envelope,
                            diagnostic_fields=("response",))
                    if incomplete_or_refused:
                        response = envelope
                    else:
                        try:
                            response = raw.parse()
                        except (ValidationError, ValueError, TypeError, AttributeError):
                            return _failure(request, failure_type=FailureType.MALFORMED_OUTPUT,
                                source="adapter", stage="normalization", cause_code="structured_output_invalid",
                                latency_ms=(monotonic() - started) * 1000, response=envelope,
                                diagnostic_fields=("structured_output",))
        except Exception as error:
            return _exception_failure(request, error, (monotonic() - started) * 1000)
        return self._normalize(request, response, (monotonic() - started) * 1000)

    def _normalize(self, request: ProviderRequest, response: object, latency_ms: float) -> ProviderResult | ProviderFailure:
        try:
            fields = {**request_evidence(request, latency_ms), **_response_fields(response)}
            refused = _refused(response)
            incomplete_reason = _incomplete_reason(response)
            status = _safe_status(_read(response, "status"))
            if fields["response_id"] is None or status is None:
                return _failure(request, failure_type=FailureType.MALFORMED_OUTPUT,
                    source="adapter", stage="normalization", cause_code="response_identity_invalid",
                    latency_ms=latency_ms, response=response, diagnostic_fields=("response_id", "response_status"))
            if status in {"failed", "cancelled", "queued", "in_progress"}:
                error_code = _read(_read(response, "error"), "code")
                if error_code == "rate_limit_exceeded":
                    failure_type, code, retryable = FailureType.RATE_LIMIT, "provider_rate_limit", True
                elif error_code in {"model_not_found", "unsupported_value", "invalid_model"}:
                    failure_type, code, retryable = FailureType.CAPABILITY_FAILURE, "provider_request_unsupported", False
                elif error_code == "server_error":
                    failure_type, code, retryable = FailureType.PROVIDER_FAILURE, "provider_server_error", True
                else:
                    failure_type, code, retryable = FailureType.PROVIDER_FAILURE, "provider_response_not_complete", status in {"queued", "in_progress"}
                return _failure(request, failure_type=failure_type, source="provider",
                    stage="normalization", cause_code=code, latency_ms=latency_ms, response=response,
                    retryable=retryable, diagnostic_fields=("response_status",))
            if request.output_type is None:
                text = _read(response, "output_text")
                if text is not None and not isinstance(text, str):
                    raise TypeError("invalid output text")
                if text is None and not refused and status == "completed":
                    return _failure(request, failure_type=FailureType.MALFORMED_OUTPUT,
                        source="adapter", stage="normalization", cause_code="text_output_missing",
                        latency_ms=latency_ms, response=response, diagnostic_fields=("text",))
                structured_output = None
            else:
                text = None
                structured_output = _read(response, "output_parsed")
                if structured_output is None and not refused and status == "completed":
                    return _failure(request, failure_type=FailureType.MALFORMED_OUTPUT,
                        source="adapter", stage="normalization", cause_code="structured_output_missing",
                        latency_ms=latency_ms, response=response, diagnostic_fields=("structured_output",))
                if structured_output is not None and not isinstance(structured_output, request.output_type):
                    return _failure(request, failure_type=FailureType.MALFORMED_OUTPUT,
                        source="adapter", stage="normalization", cause_code="structured_output_wrong_type",
                        latency_ms=latency_ms, response=response, diagnostic_fields=("structured_output",))
            return ProviderResult(**fields, text=text, structured_output=structured_output,
                incomplete_reason=incomplete_reason, refused=refused)
        except (ValidationError, ValueError, TypeError):
            return _failure(request, failure_type=FailureType.MALFORMED_OUTPUT,
                source="adapter", stage="normalization", cause_code="response_normalization_invalid",
                latency_ms=latency_ms, response=response, diagnostic_fields=("response",))

__all__ = ["OpenAIProvider"]


def verify_model_access(models: Mapping[str, str], *, credential_env: str, timeout_ms: int) -> dict[str, bool]:
    """Explicit operator probe of model retrieval, not a paid generation canary."""
    if os.environ.get('RUN_LIVE_OPENAI_TESTS') != '1' or not os.environ.get(credential_env):
        raise ValueError('explicit live access probe opt-in and credential required')
    if type(timeout_ms) is not int or timeout_ms <= 0:
        raise ValueError('finite probe timeout required')
    from openai import OpenAI
    results = {}
    with _quiet_sdk_logs():
        with OpenAI(api_key=os.environ[credential_env],max_retries=0,timeout=timeout_ms/1000) as client:
            for alias, identifier in models.items():
                try:
                    result = client.models.retrieve(identifier)
                    results[alias] = result.id == identifier
                except Exception:
                    results[alias] = False
    return results
