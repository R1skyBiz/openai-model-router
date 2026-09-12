"""Client contract tests using in-process ASGI and synthetic HTTP only."""
import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import types
import sys

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from model_router.client import (
    RouterClient, ClientConfig, Request, Limits, RouterFailure, RouterTimeout,
    TransportFailure, MalformedResponse, AuthenticationFailure, ClientPolicyError,
)
from model_router.core.execution_contracts import ExecutionControls
from model_router.core.provider_contracts import ProviderFailure
from model_router.execution.provider import request_evidence
from model_router.service import create_app, create_authenticated_app, AuthenticatedApplication, credential_digest
from model_router.validation.v0 import V0Validator, DeterministicCheck
from phase3_support import setup, success
from test_phase4_service import _with_health
from test_phase3_execution import quality_check
from test_classify_route import composed


TOKEN = "test-client-credential"
MODE = {"schema_version": 1, "mode": "mock", "execution_enabled": True,
        "live_execution_enabled": False, "paid_classifier_enabled": False, "shadow_enabled": False}


def client(app=None, *, handler=None, mode="mock", **settings):
    config = ClientConfig(token=TOKEN, mode=mode, default_budget_usd="10", **settings)
    return RouterClient(config, transport=httpx.ASGITransport(app=app) if app else httpx.MockTransport(handler))


def authenticated(deps, scopes=("route", "execute", "read", "health")):
    return create_authenticated_app(applications=[AuthenticatedApplication(
        application_id="example", credential_digest=credential_digest(TOKEN),
        dependencies=deps, scopes=frozenset(scopes))])


def test_preview_execution_idempotency_and_lookup(tmp_path):
    req, cl, deps = setup(tmp_path)
    async def scenario():
        async with client(authenticated(deps)) as c:
            preview = await c.route_preview(req, cl)
            assert deps.provider.call_count == 0
            assert preview.selected_model_alias == "terra"
            assert preview.reasoning_effort == "medium"
            assert preview.validation_version and preview.rationale_codes
            assert preview.estimated_cost.amount > 0
            result = await c.execute(req, classification=cl, idempotency_key="logical-job")
            assert result.status == "succeeded" and result.output == "private output"
            assert result.selected_route.selected_model_alias == preview.selected_model_alias
            assert result.attempts[0].provider_outcome.usage.total_tokens == 20
            assert result.attempts[0].validations
            assert result.total_cost_usd == Decimal("0.00014")
            assert result.latency_ms >= 0
            assert all(a.trace_id == req.trace_id for a in result.attempts)
            replay = await c.execute(req, classification=cl, idempotency_key="logical-job")
            lookup = await c.get_task(req.task_id)
            assert deps.provider.call_count == 1
            assert replay.task_id == lookup.task_id == result.task_id
            assert lookup.output is None
    asyncio.run(scenario())


def test_paid_preview_is_explicit_and_uses_existing_schema(composed):
    _, app, calls, body, _ = composed
    async def scenario():
        config = ClientConfig(token="a" * 40, mode="live", allow_paid_classifier=True)
        async with RouterClient(config, transport=httpx.ASGITransport(app=app)) as c:
            request = Request.model_validate(body["request"])
            first = await c.classify_route(request, idempotency_key=body["idempotency_key"])
            again = await c.classify_route(request, idempotency_key=body["idempotency_key"])
            assert first == again == await c.get_preview(first.preview_id)
            assert first.status == "completed" and first.classification
            assert len(calls) == 1 and calls[0].purpose == "classification"
            assert first.trace_id == request.trace_id
    asyncio.run(scenario())


@pytest.mark.parametrize("code", [401, 403])
def test_auth_failure_sanitized(code, tmp_path):
    req, cl, _ = setup(tmp_path)
    def handler(_):
        return httpx.Response(code, json={"code": "authentication_required", "message": TOKEN, "retryable": False})
    async def scenario():
        async with client(handler=handler) as c:
            with pytest.raises(AuthenticationFailure) as caught:
                await c.route_preview(req, cl)
            assert caught.value.status_code == code
            assert caught.value.trace_id == req.trace_id
            assert TOKEN not in str(caught.value) + repr(vars(caught.value))
    asyncio.run(scenario())


@pytest.mark.parametrize("payload", [None, [], {}, {"live": "true"}, {"live": True, "extra": TOKEN}])
def test_malformed_liveness_fails_closed(payload):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)
    async def scenario():
        async with client(handler=handler) as c:
            with pytest.raises(MalformedResponse):
                await c.liveness()
            assert len(calls) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("mutation", ["missing", "status", "correlation", "usage", "negative_cost", "structured"])
def test_execution_response_validation(tmp_path, mutation):
    req, cl, deps = setup(tmp_path)
    body = req.model_dump(mode="json"); body["input"] = req.input
    payload = TestClient(create_app(deps)).post("/v1/execute", json={"request": body, "classification": cl.model_dump(mode="json")}).json()
    if mutation == "missing": payload.pop("attempts")
    if mutation == "status": payload["status"] = "apparently_ok"
    if mutation == "correlation": payload["attempts"][0]["trace_id"] = "wrong"
    if mutation == "usage": payload["attempts"][0]["provider_outcome"]["usage"]["total_tokens"] = 1
    if mutation == "negative_cost": payload["total_cost_usd"] = "-1"
    if mutation == "structured": payload["structured_output"] = ["bad-shape"]
    def handler(request):
        return httpx.Response(200, json=MODE if request.url.path == "/health/integration" else payload)
    async def scenario():
        async with client(handler=handler) as c:
            with pytest.raises(MalformedResponse):
                await c.execute(req, classification=cl, idempotency_key="key")
    asyncio.run(scenario())


def test_successful_structured_result(tmp_path):
    class Output(BaseModel):
        value: str
    def output(request):
        return success(request).model_copy(update={"structured_output": Output(value="answer")})
    req, cl, deps = setup(tmp_path, [output], controls=ExecutionControls(authorized=True, output_type=Output))
    async def scenario():
        async with client(authenticated(deps)) as c:
            result = await c.execute(req, classification=cl, idempotency_key="structured")
            assert dict(result.structured_output) == {"value": "answer"}
            assert "answer" not in repr(result)
    asyncio.run(scenario())


def test_budget_rejection_preserves_ceiling(tmp_path):
    req, cl, deps = setup(tmp_path)
    req = req.model_copy(update={"constraints": Limits(task_cost_ceiling_usd="0")})
    async def scenario():
        async with client(authenticated(deps)) as c:
            with pytest.raises(RouterFailure) as caught:
                await c.route_preview(req, cl)
            assert caught.value.failure_type == "BUDGET_FAILURE"
            result = await c.execute(req, classification=cl, idempotency_key="no-budget")
            assert result.status == "failed" and result.failure.failure_type == "BUDGET_FAILURE"
            assert not result.attempts and deps.provider.call_count == 0
    asyncio.run(scenario())


@pytest.mark.parametrize("failure_type", ["QUALITY_FAILURE", "PROVIDER_FAILURE", "TIMEOUT"])
def test_typed_failure_and_recovery(tmp_path, failure_type):
    if failure_type == "QUALITY_FAILURE":
        req, cl, deps = setup(tmp_path, [success]*3,
            controls=ExecutionControls(authorized=True, required_checks=("quality",)),
            validator=V0Validator({"quality": DeterministicCheck(quality_check)}))
    else:
        def fail(request):
            return ProviderFailure(**request_evidence(request), failure_type=failure_type,
                source="provider", stage="invocation", cause_code="unavailable", retryable=False)
        req, cl, deps = setup(tmp_path, [fail])
    async def scenario():
        async with client(authenticated(deps)) as c:
            result = await c.execute(req, classification=cl, idempotency_key="failure")
            assert result.status != "succeeded"
            if failure_type == "QUALITY_FAILURE":
                assert result.failure.failure_type == "BUDGET_FAILURE"
                assert result.failure.cause_code == "recovery_attempts_exhausted"
            else:
                assert result.failure.failure_type == failure_type
            assert result.recovery_actions
            assert result.attempts[0].failure.failure_type == failure_type
            if failure_type == "QUALITY_FAILURE":
                assert len(result.attempts) == 3
                assert any(v.status == "failed" for v in result.attempts[0].validations)
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout, httpx.WriteError])
def test_execution_transport_never_replays(tmp_path, failure):
    req, cl, _ = setup(tmp_path)
    bodies = []
    def handler(request):
        if request.url.path == "/health/integration": return httpx.Response(200, json=MODE)
        bodies.append(request.content)
        raise failure(TOKEN)
    async def scenario():
        async with client(handler=handler, safe_retries=3) as c:
            for _ in range(2):
                with pytest.raises(TransportFailure) as caught:
                    await c.execute(req, classification=cl, idempotency_key="same-key")
                assert TOKEN not in str(caught.value)
            # Each explicitly requested call sends once, preserving exact payload/key.
            assert len(bodies) == 2 and bodies[0] == bodies[1]
            assert json.loads(bodies[0])["idempotency_key"] == "same-key"
    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["read", "preview"])
def test_bounded_safe_retries(tmp_path, operation):
    req, cl, deps = setup(tmp_path)
    from model_router.router import route
    good = route(req, cl, deps.environment, deps.bundle).model_dump(mode="json")
    calls = []
    def handler(request):
        calls.append(request.content)
        if len(calls) == 1: raise httpx.ConnectError(TOKEN)
        return httpx.Response(200, json={"live": True} if operation == "read" else good)
    async def scenario():
        async with client(handler=handler) as c:
            if operation == "read": assert (await c.liveness()).live
            else: assert (await c.route_preview(req, cl)).trace_id == req.trace_id
            assert len(calls) == 2 and calls[0] == calls[1]
    asyncio.run(scenario())


def test_safe_retry_exhaustion_and_http_retry():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"code": "dependency_unavailable", "retryable": True})
    async def scenario():
        async with client(handler=handler, safe_retries=2) as c:
            with pytest.raises(RouterFailure): await c.liveness()
            assert len(calls) == 3
    asyncio.run(scenario())


def test_whole_request_timeout_and_cancellation():
    async def handler(_):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"live": True})
    async def scenario():
        async with client(handler=handler, request_timeout_s=0.01) as c:
            with pytest.raises(RouterTimeout): await c.liveness()
        async with client(handler=handler) as c:
            task = asyncio.create_task(c.liveness())
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(scenario())


def test_explicit_timeouts_and_constraint_serialization(tmp_path):
    req, cl, deps = setup(tmp_path)
    req = req.model_copy(update={"constraints": Limits(task_cost_ceiling_usd="0.005", task_deadline_ms=200,
        model_tier_floor=1, model_tier_ceiling=2), "requirements": ("text_input", "text_output", "structured_outputs")})
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"code": "dependency_unavailable", "retryable": False})
    async def scenario():
        async with client(handler=handler, connect_timeout_s=0.2, request_timeout_s=0.5) as c:
            with pytest.raises(RouterFailure): await c.route_preview(req, cl)
    asyncio.run(scenario())
    payload = json.loads(calls[0].content)["request"]
    assert payload["input"] == req.input
    assert payload["constraints"]["task_cost_ceiling_usd"] == "0.005"
    assert payload["constraints"]["task_deadline_ms"] == 200
    assert payload["constraints"]["model_tier_ceiling"] == 2
    assert payload["requirements"] == list(req.requirements)
    assert calls[0].extensions["timeout"] == {"connect": 0.2, "read": 0.5, "write": 0.5, "pool": 0.5}


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_never_forward_credentials(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "https://other.invalid"})
    async def scenario():
        async with client(handler=handler) as c:
            with pytest.raises(MalformedResponse): await c.liveness()
            assert len(calls) == 1
    asyncio.run(scenario())


def test_health_readiness_and_mode_are_distinct(tmp_path):
    _, _, deps = setup(tmp_path)
    async def scenario():
        async with client(authenticated(deps)) as c:
            assert (await c.liveness()).live
            assert not (await c.readiness()).ready
            assert (await c.integration_status()).mode == "mock"
            assert await c.database_availability() == "UNKNOWN"
        async with client(authenticated(_with_health(deps))) as c:
            assert (await c.readiness()).ready
            # Historical synthetic observations do not imply current health.
            assert await c.provider_family_health("terra") == "UNKNOWN"
    asyncio.run(scenario())


def test_health_fresh_missing_and_unhealthy():
    now = datetime.now(UTC)
    observation = {"component": "provider", "model": "terra", "state": "HEALTHY",
        "observed_at": now.isoformat(), "valid_until": (now + timedelta(seconds=60)).isoformat()}
    payload = {"snapshot_id": "snapshot", "config_version": "v1", "synthetic": True, "components": [observation]}
    async def scenario():
        async with client(handler=lambda _: httpx.Response(200, json=payload)) as c:
            assert await c.provider_family_health("terra") == "HEALTHY"
            assert await c.provider_family_health("missing") == "UNKNOWN"
            observation["state"] = "UNHEALTHY"
            assert await c.provider_family_health("terra") == "UNHEALTHY"
            observation["check_status"] = "stale"
            assert await c.provider_family_health("terra") == "UNKNOWN"
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["mock", "shadow", "live", "route_only", "unknown"])
def test_mode_mismatch_never_executes(tmp_path, mode):
    req, cl, _ = setup(tmp_path)
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={**MODE, "mode": mode, "live_execution_enabled": mode == "live"})
    async def scenario():
        async with client(handler=handler, mode="live" if mode == "mock" else "mock") as c:
            with pytest.raises(ClientPolicyError): await c.execute(req, classification=cl, idempotency_key="key")
            assert calls == ["/health/integration"]
    asyncio.run(scenario())


def test_shadow_and_paid_classifier_default_block_without_io(tmp_path):
    req, cl, _ = setup(tmp_path)
    def forbidden(_): raise AssertionError("no I/O expected")
    async def scenario():
        async with client(handler=forbidden, mode="shadow") as c:
            with pytest.raises(ClientPolicyError): await c.execute(req, classification=cl, idempotency_key="key")
            with pytest.raises(ClientPolicyError): await c.classify_route(req, idempotency_key="key")
    asyncio.run(scenario())


def test_new_health_endpoint_requires_health_scope(tmp_path):
    _, _, deps = setup(tmp_path)
    c = TestClient(authenticated(deps, scopes=("route",)))
    assert c.get("/health/integration").status_code == 401
    assert c.get("/health/integration", headers={"Authorization": "Bearer " + TOKEN}).status_code == 403


def test_environment_and_credentials_are_safe():
    cfg = ClientConfig.from_env({"MODEL_ROUTER_APP_TOKEN": TOKEN})
    assert cfg.mode == "shadow" and not cfg.allow_paid_classifier
    assert TOKEN not in repr(cfg) + str(cfg.model_dump())
    with pytest.raises(ValueError) as caught:
        ClientConfig.from_env({"MODEL_ROUTER_APP_TOKEN": TOKEN, "MODEL_ROUTER_URL": "https://" + TOKEN + "@example.com"})
    assert TOKEN not in str(caught.value)
    for env in ({}, {"MODEL_ROUTER_APP_TOKEN": "bad\r\ntoken"},
                {"MODEL_ROUTER_APP_TOKEN": TOKEN, "MODEL_ROUTER_REQUEST_TIMEOUT_S": "nan"},
                {"MODEL_ROUTER_APP_TOKEN": TOKEN, "MODEL_ROUTER_ALLOW_PAID_CLASSIFIER": "yes"}):
        with pytest.raises(ValueError): ClientConfig.from_env(env)


@pytest.mark.parametrize("url", ["http://example.com", "https://user:secret@example.com", "https://example.com?token=secret", "https://example.com/path"])
def test_unsafe_urls_rejected(url):
    with pytest.raises(ValueError): ClientConfig(base_url=url, token=TOKEN)


def test_concurrent_requests_keep_correlation(tmp_path):
    req, cl, deps = setup(tmp_path)
    async def scenario():
        async with client(authenticated(deps)) as c:
            requests = [req.model_copy(update={"task_id": f"task-{i}", "trace_id": f"trace-{i}"}) for i in range(24)]
            responses = await asyncio.gather(*(c.route_preview(r, cl) for r in requests))
            assert [(r.task_id, r.trace_id) for r in responses] == [(r.task_id, r.trace_id) for r in requests]
            assert deps.provider.call_count == 0
    asyncio.run(scenario())


def test_existing_openapi_schema_unchanged(tmp_path, monkeypatch):
    _, _, deps = setup(tmp_path)
    # Public compatibility baseline; keep it available in published repository history.
    baseline = subprocess.run(["git", "show", "0d56cf5:src/model_router/service/app.py"], check=True, capture_output=True, text=True).stdout
    old = types.ModuleType("baseline_app")
    monkeypatch.setitem(sys.modules, "baseline_app", old)
    exec(compile(baseline, "baseline_app.py", "exec"), old.__dict__)
    before = old.create_app(deps).openapi()
    after = create_app(deps).openapi()
    after["paths"].pop("/health/integration")
    after["components"]["schemas"].pop("IntegrationStatus")
    assert after == before


def test_expected_mode_checked_at_server_dispatch(tmp_path):
    req, cl, deps = setup(tmp_path)
    payload = req.model_dump(mode="json"); payload["input"] = req.input
    response = TestClient(authenticated(deps)).post("/v1/execute",
        headers={"Authorization": "Bearer " + TOKEN, "X-Model-Router-Expected-Mode": "live"},
        json={"request": payload, "classification": cl.model_dump(mode="json"), "idempotency_key": "key"})
    assert response.status_code == 409
    assert response.json()["code"] == "execution_mode_mismatch"
    assert deps.provider.call_count == 0


@pytest.mark.parametrize("kind", ["mock", "shadow", "live", "route_only"])
def test_service_reports_actual_composition(tmp_path, kind):
    _, _, deps = setup(tmp_path)
    if kind == "shadow": deps = replace(deps, shadow=object())
    if kind in {"live", "route_only"}:
        deps = replace(deps, environment=deps.environment.model_copy(update={"synthetic": False}),
            live=object() if kind == "live" else None,
            controls=ExecutionControls(authorized=kind == "live"))
    response = TestClient(authenticated(deps)).get("/health/integration", headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 200
    assert response.json()["mode"] == kind
    assert response.json()["live_execution_enabled"] == (kind == "live")
    assert deps.provider.call_count == 0


def test_concurrent_execution_preserves_job_identity(tmp_path):
    req, cl, deps = setup(tmp_path, [success] * 8)
    async def scenario():
        async with client(authenticated(deps)) as c:
            requests = [req.model_copy(update={"task_id": f"job-{i}", "trace_id": f"trace-{i}"}) for i in range(8)]
            results = await asyncio.gather(*(c.execute(r, classification=cl, idempotency_key=f"key-{i}") for i, r in enumerate(requests)))
            assert all(result.status == "succeeded" for result in results)
            assert [(r.task_id, r.trace_id) for r in results] == [(r.task_id, r.trace_id) for r in requests]
            assert deps.provider.call_count == 8
    asyncio.run(scenario())


def test_live_client_path_uses_router_only(tmp_path):
    req, cl, deps = setup(tmp_path)
    from model_router.execution.orchestrator import execute
    from model_router.service.app import _task_projection
    result = _task_projection(execute(req, deps, supplied_classification=cl), include_output=True)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={**MODE, "mode": "live", "live_execution_enabled": True}
                              if request.url.path == "/health/integration" else result)
    async def scenario():
        async with client(handler=handler, mode="live") as c:
            response = await c.execute(req, classification=cl, idempotency_key="live-plumbing-only")
            assert response.status == "succeeded"
            assert calls[-1].headers["X-Model-Router-Expected-Mode"] == "live"
            assert {r.url.host for r in calls} == {"127.0.0.1"}
    asyncio.run(scenario())


def test_unknown_error_text_and_transport_logs_do_not_leak(tmp_path, caplog):
    req, cl, _ = setup(tmp_path)
    def handler(_):
        return httpx.Response(500, json={"code": TOKEN, "message": TOKEN, "retryable": False})
    async def scenario():
        async with client(handler=handler) as c:
            with pytest.raises(RouterFailure) as caught:
                await c.route_preview(req, cl)
            assert caught.value.code == "router_error"
            assert TOKEN not in str(caught.value) + repr(vars(caught.value)) + caplog.text
    asyncio.run(scenario())


def test_unsupported_fields_fail_instead_of_disappearing(tmp_path):
    req, cl, _ = setup(tmp_path)
    for name in ("allowed_tools", "metadata", "shadow_mode"):
        with pytest.raises(ValueError): Request.model_validate({**req.model_dump(), name: {}})
    async def scenario():
        async with client(handler=lambda _: pytest.fail("no I/O")) as c:
            with pytest.raises(TypeError):
                await c.execute(req, classification=cl, idempotency_key="key", allowed_tools=["write"])
    asyncio.run(scenario())
