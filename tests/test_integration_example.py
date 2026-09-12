"""Exercise the public FastAPI example against an in-process mock router."""
from dataclasses import replace
import json

import httpx
from fastapi.testclient import TestClient
import pytest

from examples.fastapi_integration import create_app
from model_router.client import ClientConfig
from model_router.core.execution_contracts import ExecutionControls
from model_router.core.provider_contracts import ProviderFailure
from model_router.execution.provider import request_evidence
from model_router.validation.v0 import DeterministicCheck, V0Validator
from phase3_support import setup, success
from test_integration_client import authenticated, TOKEN
from test_phase4_service import _with_health
from test_phase3_execution import quality_check


def payload(req, cl):
    request = req.model_dump(mode="json"); request["input"] = req.input
    request["constraints"]["task_cost_ceiling_usd"] = "0.01"
    return {"request": request, "classification": cl.model_dump(mode="json")}


def test_example_preview_then_explicit_execution(tmp_path, caplog):
    req, cl, deps = setup(tmp_path)
    app = create_app(ClientConfig(token=TOKEN, mode="mock"),
        transport=httpx.ASGITransport(app=authenticated(_with_health(deps))))
    with TestClient(app) as c:
        assert c.get("/router/readiness").json()["service"]["mode"] == "mock"
        proposed = c.post("/preview", json=payload(req, cl))
        assert proposed.status_code == 200
        assert proposed.json()["model"] == "terra"
        assert proposed.json()["trace_id"] == req.trace_id
        assert deps.provider.call_count == 0
        assert c.post("/execute", json=payload(req, cl)).status_code == 422
        executed = c.post("/execute", json={**payload(req, cl), "confirm_execution": True, "idempotency_key": "stable-key"})
        assert executed.status_code == 200 and executed.json()["outcome"] == "succeeded"
        assert deps.provider.call_count == 1
        assert req.input not in caplog.text and TOKEN not in caplog.text


def test_example_defaults_shadow_and_forbids_execution(tmp_path):
    req, cl, deps = setup(tmp_path)
    app = create_app(ClientConfig(token=TOKEN), transport=httpx.ASGITransport(app=authenticated(_with_health(deps))))
    with TestClient(app) as c:
        response = c.post("/execute", json={**payload(req, cl), "confirm_execution": True, "idempotency_key": "stable-key"})
        assert response.status_code == 409
        assert response.json()["code"] == "shadow_execution_forbidden"
        assert deps.provider.call_count == 0


@pytest.mark.parametrize("failure_type,outcome,http_status", [
    ("QUALITY_FAILURE", "validation_failed", 422),
    ("PROVIDER_FAILURE", "provider_unavailable", 503),
    ("TIMEOUT", "execution_timeout", 504),
    ("BUDGET_FAILURE", "budget_rejected", 422),
])
def test_example_handles_router_results(tmp_path, failure_type, outcome, http_status):
    if failure_type == "QUALITY_FAILURE":
        req, cl, deps = setup(tmp_path, [success] * 3,
            controls=ExecutionControls(authorized=True, required_checks=("quality",)),
            validator=V0Validator({"quality": DeterministicCheck(quality_check)}))
    elif failure_type == "BUDGET_FAILURE":
        req, cl, deps = setup(tmp_path)
    else:
        def fail(request):
            return ProviderFailure(**request_evidence(request), failure_type=failure_type,
                source="provider", stage="invocation", cause_code="unavailable", retryable=False)
        req, cl, deps = setup(tmp_path, [fail])
    body = payload(req, cl)
    if failure_type == "BUDGET_FAILURE": body["request"]["constraints"]["task_cost_ceiling_usd"] = "0"
    # Isolate result mapping from health-aware recovery; health behavior has its own tests.
    deps = replace(deps, release_readiness=lambda: {"ready": True, "state": "HEALTHY"})
    app = create_app(ClientConfig(token=TOKEN, mode="mock"), transport=httpx.ASGITransport(app=authenticated(deps)))
    with TestClient(app) as c:
        response = c.post("/execute", json={**body, "confirm_execution": True, "idempotency_key": "stable-key"})
        assert response.status_code == http_status, response.json().get("failure")
        assert response.json()["outcome"] == outcome
        assert response.json()["trace_id"] == req.trace_id


@pytest.mark.parametrize("kind,code", [("timeout", 504), ("transport", 502), ("auth", 503)])
def test_example_handles_http_errors(tmp_path, kind, code):
    req, cl, _ = setup(tmp_path)
    def handler(request):
        if kind == "timeout": raise httpx.ReadTimeout("private transport details")
        if kind == "transport": raise httpx.ReadError("private transport details")
        return httpx.Response(401, json={"code": "authentication_required", "message": TOKEN, "retryable": False})
    app = create_app(ClientConfig(token=TOKEN, safe_retries=0), transport=httpx.MockTransport(handler))
    with TestClient(app) as c:
        response = c.post("/preview", json=payload(req, cl))
        assert response.status_code == code
        assert TOKEN not in response.text and "private transport" not in response.text
