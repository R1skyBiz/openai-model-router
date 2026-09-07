from dataclasses import replace

from fastapi.testclient import TestClient

from model_router.core.contracts import Limits
from model_router.core.execution_contracts import ExecutionControls, RepositoryUnavailable
from model_router.execution.orchestrator import execute
from model_router.service import create_app

from phase3_support import setup


def _request_payload(request):
    payload = request.model_dump(mode="json")
    payload["input"] = request.input
    return payload


def _route_payload(request, classification):
    return {
        "request": _request_payload(request),
        "classification": classification.model_dump(mode="json"),
    }


def _execute_payload(request, classification, *, key=None):
    payload = _route_payload(request, classification)
    if key is not None:
        payload["idempotency_key"] = key
    return payload


def test_route_only_uses_shared_router_without_execution(tmp_path):
    request, classification, dependencies = setup(tmp_path)
    client = TestClient(create_app(dependencies))

    response = client.post("/v1/route", json=_route_payload(request, classification))

    assert response.status_code == 200
    assert response.json()["selected_model_alias"] == "terra"
    assert response.json()["reasoning_effort"] == "medium"
    assert dependencies.provider.call_count == 0
    assert dependencies.repository.get(request.task_id) is None
    assert request.input not in response.text


def test_route_requires_classification_and_rejections_are_typed(tmp_path):
    request, classification, dependencies = setup(tmp_path)
    client = TestClient(create_app(dependencies))

    missing = client.post(
        "/v1/route",
        json={"request": _request_payload(request), "secret": "must-not-leak"},
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "invalid_request"
    assert "must-not-leak" not in missing.text
    assert dependencies.provider.call_count == 0

    rejected_request = request.model_copy(
        update={"constraints": Limits(task_cost_ceiling_usd="0")}
    )
    rejected = client.post(
        "/v1/route", json=_route_payload(rejected_request, classification)
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "route_rejected"
    assert rejected.json()["failure_type"] == "BUDGET_FAILURE"
    assert rejected.json()["task_id"] == request.task_id
    assert dependencies.provider.call_count == 0


def test_execute_matches_embedded_engine_and_only_success_exposes_output(tmp_path):
    embedded_dir = tmp_path / "embedded"
    http_dir = tmp_path / "http"
    embedded_dir.mkdir()
    http_dir.mkdir()
    request, classification, embedded_dependencies = setup(embedded_dir)
    expected = execute(
        request,
        embedded_dependencies,
        supplied_classification=classification,
    )

    request, classification, http_dependencies = setup(http_dir)
    client = TestClient(create_app(http_dependencies))
    response = client.post(
        "/v1/execute", json=_execute_payload(request, classification)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == expected.status.value == "succeeded"
    assert body["decisions"][-1]["selected_model_alias"] == expected.decisions[-1].selected_model_alias
    assert body["known_cost_usd"] == str(expected.known_cost_usd)
    assert body["output"] == "private output"
    assert http_dependencies.provider.call_count == 1

    retrieved = client.get(f"/v1/tasks/{request.task_id}")
    assert retrieved.status_code == 200
    assert "output" not in retrieved.json()
    assert "structured_output" not in retrieved.json()
    assert "private output" not in retrieved.text


def test_body_cannot_supply_authorization_or_tool_controls(tmp_path):
    request, classification, dependencies = setup(
        tmp_path,
        controls=ExecutionControls(authorized=False),
    )
    client = TestClient(create_app(dependencies))
    payload = _execute_payload(request, classification)
    payload["controls"] = {
        "authorized": True,
        "authorized_tools": ["dangerous-tool"],
        "side_effects_authorized": True,
    }

    response = client.post("/v1/execute", json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert dependencies.provider.call_count == 0

    blocked = client.post(
        "/v1/execute", json=_execute_payload(request, classification)
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"
    assert "output" not in blocked.json()
    assert dependencies.provider.call_count == 0


def test_body_idempotency_key_can_only_tighten_trusted_controls(tmp_path):
    request, classification, dependencies = setup(
        tmp_path,
        controls=ExecutionControls(authorized=True, idempotency_key="trusted-key"),
    )
    client = TestClient(create_app(dependencies))

    conflict = client.post(
        "/v1/execute",
        json=_execute_payload(request, classification, key="replacement-key"),
    )
    assert conflict.status_code == 422
    assert conflict.json()["code"] == "idempotency_scope_conflict"
    assert dependencies.provider.call_count == 0


def test_idempotency_conflict_missing_and_unavailable_are_sanitized(tmp_path):
    request, classification, dependencies = setup(tmp_path)
    client = TestClient(create_app(dependencies))
    first = client.post(
        "/v1/execute",
        json=_execute_payload(request, classification, key="stable-key"),
    )
    assert first.status_code == 200

    changed = request.model_copy(
        update={"task_id": "other-task", "input": "conflicting-private-input"}
    )
    conflict = client.post(
        "/v1/execute",
        json=_execute_payload(changed, classification, key="stable-key"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
    assert "conflicting-private-input" not in conflict.text

    missing = client.get("/v1/tasks/missing-task")
    assert missing.status_code == 404
    assert missing.json()["code"] == "task_not_found"

    unavailable_dependencies = replace(
        dependencies, repository=_UnavailableRepository()
    )
    unavailable = TestClient(create_app(unavailable_dependencies)).get(
        "/v1/tasks/task"
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "dependency_unavailable"


class _UnavailableRepository:
    def get(self, _task_id):
        raise RepositoryUnavailable("private database diagnostics")
