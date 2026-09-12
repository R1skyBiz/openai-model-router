"""Async HTTP boundary with bounded reads and no execution replay or fallback."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from pydantic import TypeAdapter, ValidationError

from model_router.core.contracts import Request, Classification, RouteDecision
from model_router.core.execution_contracts import TaskResult
from model_router.core.preview_contracts import RoutingPreview
from model_router.http_contracts import (
    RouteBody, ExecuteBody, ClassifyRouteBody, IntegrationStatus,
)
from .models import (
    ClientConfig, ExecutionResult, Liveness, Readiness, ComponentHealth, RouterErrorBody,
)


class ClientError(Exception):
    """Safe to log normally; no response, HTTP request, credential or raw input."""
    def __init__(self, code: str, *, status_code: int | None = None,
                 task_id: str | None = None, trace_id: str | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.task_id = task_id
        self.trace_id = trace_id


class TransportFailure(ClientError):
    """No trustworthy router result. Execution may still have completed."""


class RouterTimeout(TransportFailure):
    pass


class MalformedResponse(ClientError):
    pass


class RouterFailure(ClientError):
    """An HTTP error returned by the router, separate from TaskResult.failure."""
    failure_type = None


class AuthenticationFailure(RouterFailure):
    pass


class ClientPolicyError(ClientError):
    pass


_SAFE_CODES = frozenset({
    "execution_mode_mismatch", "authentication_required", "permission_denied", "route_rejected", "invalid_request",
    "idempotency_conflict", "idempotency_scope_conflict", "dependency_unavailable",
    "internal_error", "preview_disabled", "preview_unavailable", "preview_capacity_exhausted",
    "concurrency_limit", "task_not_found", "preview_not_found", "policy_version_mismatch",
    "caller_application_id_forbidden", "preview_body_too_large", "preview_body_timeout",
})


class RouterClient:
    """One event-loop-scoped pooled client. Use ``async with`` or ``aclose``.

    An injected transport is intended for local ASGI/MockTransport tests. Never
    give this client a transport with its own retry policy or logging of bodies.
    """
    def __init__(self, config: ClientConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._http = httpx.AsyncClient(
            base_url=config.base_url, transport=transport, trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(config.request_timeout_s, connect=config.connect_timeout_s),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()

    async def aclose(self):
        await self._http.aclose()

    def _request(self, request: Request) -> Request:
        try:
            value = request.model_dump(mode="json")
            value["input"] = request.input
            limits = value["constraints"]
            budget = request.constraints.task_cost_ceiling_usd
            limits["task_cost_ceiling_usd"] = str(min(
                budget if budget is not None else self.config.default_budget_usd,
                self.config.default_budget_usd))
            deadline = request.constraints.task_deadline_ms
            limits["task_deadline_ms"] = min(
                deadline if deadline is not None else int(self.config.request_timeout_s * 1000),
                int(self.config.request_timeout_s * 1000))
            if request.application_id is not None:
                raise ValueError()
            return Request.model_validate(value)
        except (ValueError, TypeError, AttributeError):
            raise ClientPolicyError("invalid_client_request") from None

    @staticmethod
    def _body(envelope):
        payload = envelope.model_dump(mode="json")
        # Raw content is excluded from core dumps to protect storage/telemetry.
        payload["request"]["input"] = envelope.request.input
        return payload

    async def liveness(self) -> Liveness:
        return await self._send("GET", "/health/live", Liveness)

    async def readiness(self) -> Readiness:
        return await self._send("GET", "/health/ready", Readiness, statuses=(200, 503))

    async def integration_status(self) -> IntegrationStatus:
        return await self._send("GET", "/health/integration", IntegrationStatus)

    async def component_health(self) -> ComponentHealth | Readiness:
        return await self._send("GET", "/health/components", ComponentHealth | Readiness,
                                statuses=(200, 503))

    async def database_availability(self) -> str:
        return await self._component_state("database")

    async def provider_family_health(self, model_alias: str) -> str:
        return await self._component_state("provider", model_alias)

    async def _component_state(self, component, model=None):
        report = await self.component_health()
        now = datetime.now(UTC)
        if isinstance(report, Readiness):
            # Release health lists healthy components but does not give each
            # observation's expiry. Do not promote this to current provider health.
            if component == "database" and report.ready and report.components and "database" in report.components:
                return "HEALTHY"
            return "UNKNOWN"
        values = [x for x in report.components if x.component == component and x.model == model]
        if not values or any(x.check_status != "observed" or not x.observed_at <= now < x.valid_until for x in values):
            return "UNKNOWN"
        if any(x.state == "UNHEALTHY" or x.circuit_state == "open" for x in values):
            return "UNHEALTHY"
        return "DEGRADED" if any(x.state == "DEGRADED" for x in values) else "HEALTHY"

    async def route_preview(self, request: Request, classification: Classification) -> RouteDecision:
        """Free routing from application-supplied classification; no generation."""
        request = self._request(request)
        return await self._send("POST", "/v1/route", RouteDecision,
                                body=self._body(RouteBody(request=request, classification=classification)),
                                request=request, safe=True)

    async def classify_route(self, request: Request, *, idempotency_key: str) -> RoutingPreview:
        """Potentially paid classification, never generation. No automatic replay."""
        if not self.config.allow_paid_classifier or self.config.mode != "live":
            raise ClientPolicyError("paid_classification_not_enabled")
        self._key(idempotency_key)
        status = await self.integration_status()
        if not status.paid_classifier_enabled:
            raise ClientPolicyError("paid_classification_not_enabled")
        request = self._request(request)
        return await self._send("POST", "/v1/classify-route", RoutingPreview,
            body=self._body(ClassifyRouteBody(request=request, idempotency_key=idempotency_key)),
            statuses=(200, 409, 422), request=request)

    async def execute(self, request: Request, *, idempotency_key: str,
                      classification: Classification | None = None) -> ExecutionResult:
        """Explicit execution, never called by preview. Client shadow mode forbids it."""
        if self.config.mode == "shadow":
            raise ClientPolicyError("shadow_execution_forbidden")
        self._key(idempotency_key)
        request = self._request(request)
        status = await self.integration_status()
        expected = self.config.mode
        if (status.mode != expected or not status.execution_enabled
                or status.live_execution_enabled != (expected == "live")
                or (expected == "mock" and (status.shadow_enabled or status.paid_classifier_enabled))):
            raise ClientPolicyError("execution_mode_mismatch")
        return await self._send("POST", "/v1/execute", ExecutionResult,
            body=self._body(ExecuteBody(request=request, classification=classification,
                                       idempotency_key=idempotency_key)), request=request, expected_mode=expected)

    async def get_task(self, task_id: str) -> ExecutionResult:
        self._identifier(task_id)
        result = await self._send("GET", "/v1/tasks/" + quote(task_id, safe=""), ExecutionResult)
        if result.task_id != task_id:
            raise MalformedResponse("correlation_mismatch")
        return result

    async def get_preview(self, preview_id: str) -> RoutingPreview:
        self._identifier(preview_id)
        result = await self._send("GET", "/v1/previews/" + quote(preview_id, safe=""), RoutingPreview)
        if result.preview_id != preview_id:
            raise MalformedResponse("correlation_mismatch")
        return result

    @staticmethod
    def _identifier(value):
        if not isinstance(value, str) or not value or value in {".", ".."} or "/" in value:
            raise ClientPolicyError("invalid_lookup_identifier")

    @staticmethod
    def _key(key):
        if not isinstance(key, str) or not key.strip() or len(key) > 256:
            raise ClientPolicyError("invalid_idempotency_key")

    async def _send(self, method, path, model, *, body=None, request=None,
                    statuses=(200,), safe=False, expected_mode=None):
        correlation = {"task_id": request.task_id, "trace_id": request.trace_id} if request else {}
        attempts = 1 + (self.config.safe_retries if method == "GET" or safe else 0)
        try:
            async with asyncio.timeout(self.config.request_timeout_s):
                for attempt in range(attempts):
                    try:
                        response = await self._http.request(method, path, json=body,
                            headers={"Authorization": "Bearer " + self.config.token.get_secret_value(),
                                     **({"X-Model-Router-Expected-Mode": expected_mode} if expected_mode else {})})
                    except httpx.TransportError as error:
                        if attempt + 1 < attempts and isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout)):
                            await asyncio.sleep(0.1 * (attempt + 1))
                            continue
                        cls = RouterTimeout if isinstance(error, httpx.TimeoutException) else TransportFailure
                        raise cls("router_timeout" if cls is RouterTimeout else "router_transport_failure", **correlation) from None
                    # Validate before deciding to retry, and never retain raw errors.
                    try:
                        if response.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                            raise ValueError()
                        payload = response.json()
                        if not isinstance(payload, dict):
                            raise ValueError()
                        is_error = "code" in payload
                        if is_error:
                            parsed = RouterErrorBody.model_validate_json(response.content)
                        else:
                            if response.status_code not in statuses:
                                raise ValueError()
                            if model in (ExecutionResult, RoutingPreview):
                                # The service always serializes all evidence fields. Defaults
                                # in the core are for construction, not partial HTTP results.
                                required = (set(TaskResult.model_fields) - {"output", "structured_output"}
                                            if model is ExecutionResult else set(RoutingPreview.model_fields))
                                if not required <= payload.keys():
                                    raise ValueError()
                            parsed = TypeAdapter(model).validate_json(response.content)
                            if isinstance(parsed, Readiness) and parsed.ready != (response.status_code == 200):
                                raise ValueError()
                            if isinstance(parsed, RoutingPreview):
                                for evidence in (parsed.route, parsed.classifier_evidence):
                                    if evidence and (evidence.task_id != parsed.task_id or evidence.trace_id != parsed.trace_id):
                                        raise ValueError()
                                if method == "POST":
                                    expected_status = (200 if parsed.status == "completed" else 422 if parsed.status == "blocked" else 409)
                                    if response.status_code != expected_status:
                                        raise ValueError()
                            if request and (parsed.task_id != request.task_id or parsed.trace_id != request.trace_id):
                                raise ValueError()
                    except (ValueError, TypeError, AttributeError, ValidationError):
                        raise MalformedResponse("malformed_router_response", status_code=response.status_code, **correlation) from None
                    if not is_error:
                        return parsed
                    if response.status_code < 400:
                        raise MalformedResponse("malformed_router_response", **correlation)
                    if attempt + 1 < attempts and response.status_code in {502, 503, 504} and parsed.retryable:
                        await asyncio.sleep(0.1 * (attempt + 1))
                        continue
                    cls = AuthenticationFailure if response.status_code in {401, 403} else RouterFailure
                    failure = cls(parsed.code if parsed.code in _SAFE_CODES else "router_error",
                                  status_code=response.status_code, **correlation)
                    failure.failure_type = parsed.failure_type
                    raise failure
        except TimeoutError:
            raise RouterTimeout("router_timeout", **correlation) from None
