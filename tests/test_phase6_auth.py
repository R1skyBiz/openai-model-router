from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from model_router.service import (
    AuthenticatedApplication,
    create_authenticated_app,
    credential_digest,
)
from model_router.router import route
from model_router.core.execution_contracts import ExecutionEvent, TaskResult, TaskStatus

from phase3_support import setup


def _payload(request, classification):
    request_json = request.model_dump(mode="json")
    request_json["input"] = request.input
    return {
        "request": request_json,
        "classification": classification.model_dump(mode="json"),
    }


def _authorization(secret):
    return {"Authorization": f"Bearer {secret}"}


def _record(application_id, secret, dependencies, *scopes):
    return AuthenticatedApplication(
        application_id=application_id,
        credential_digest=credential_digest(secret),
        dependencies=dependencies,
        scopes=frozenset(scopes),
    )


def _persist_production_task(dependencies, application_id, suffix):
    created_at = dependencies.clock.now() - timedelta(seconds=1)
    task = TaskResult(
        task_id=f"production-{suffix}",
        trace_id=f"production-trace-{suffix}",
        application_id=application_id,
        status=TaskStatus.CREATED,
        policy_version=dependencies.bundle.policy["version"],
        created_at=created_at,
        updated_at=created_at,
    )
    dependencies.repository.create(
        task,
        ExecutionEvent(
            event_id=f"production-created-{suffix}",
            task_id=task.task_id,
            trace_id=task.trace_id,
            kind="TASK_CREATED",
            occurred_at=created_at,
            policy_version=task.policy_version,
        ),
        scope=application_id,
        key_digest=None,
        request_digest=f"production-request-{suffix}",
    )
    return task


def test_public_surface_is_minimal_and_every_other_endpoint_requires_authentication(tmp_path):
    _, _, dependencies = setup(tmp_path)
    app = create_authenticated_app(
        applications=[_record("app-a", "secret-a", dependencies, "health")]
    )
    client = TestClient(app)

    assert client.get("/health/live").json() == {"live": True}
    for path in (
        "/health/ready",
        "/health/components",
        "/openapi.json",
        "/docs",
        "/v1/tasks",
        "/v1/telemetry/summary",
    ):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == {
            "code": "authentication_required",
            "message": "Authentication is required.",
            "retryable": False,
        }

    for authorization in (
        "Basic secret-a",
        "Bearer",
        "Bearer ",
        "Bearer secret-a extra",
        "Bearer wrong",
    ):
        response = client.get(
            "/health/ready", headers={"Authorization": authorization}
        )
        assert response.status_code == 401
        assert "secret-a" not in response.text
        assert "wrong" not in response.text


def test_scopes_are_enforced_per_operation_and_openapi_is_health_scoped(tmp_path):
    request, classification, dependencies = setup(tmp_path)
    app = create_authenticated_app(
        applications=[
            _record("route-app", "route-secret", dependencies, "route"),
            _record("read-app", "read-secret", dependencies, "read"),
            _record("execute-app", "execute-secret", dependencies, "execute"),
            _record("health-app", "health-secret", dependencies, "health"),
        ]
    )
    client = TestClient(app)
    route_payload = _payload(request, classification)

    assert client.post(
        "/v1/route", json=route_payload, headers=_authorization("route-secret")
    ).status_code == 200
    assert client.post(
        "/v1/route", json=route_payload, headers=_authorization("read-secret")
    ).status_code == 403
    assert client.get(
        "/v1/tasks/missing", headers=_authorization("read-secret")
    ).status_code == 404
    assert client.get(
        "/v1/tasks/missing", headers=_authorization("route-secret")
    ).status_code == 403
    assert client.post(
        "/v1/execute", json=route_payload, headers=_authorization("execute-secret")
    ).status_code == 200
    assert client.post(
        "/v1/execute", json=route_payload, headers=_authorization("route-secret")
    ).status_code == 403
    assert client.get(
        "/health/ready", headers=_authorization("health-secret")
    ).status_code == 503
    assert client.get(
        "/health/ready", headers=_authorization("execute-secret")
    ).status_code == 403
    assert client.get(
        "/openapi.json", headers=_authorization("health-secret")
    ).status_code == 200
    assert client.get(
        "/openapi.json", headers=_authorization("read-secret")
    ).status_code == 403


def test_server_owned_identity_defeats_query_header_and_environment_spoofing(tmp_path):
    request, classification, dependencies = setup(tmp_path)
    _persist_production_task(dependencies, "trusted-app", "trusted")
    app = create_authenticated_app(
        applications=[
            _record(
                "trusted-app",
                "trusted-secret",
                dependencies,
                "route",
                "execute",
                "read",
            )
        ]
    )
    client = TestClient(app)
    headers = {
        **_authorization("trusted-secret"),
        "X-Application-ID": "forged-app",
    }

    route_response = client.post(
        "/v1/route", json=_payload(request, classification), headers=headers
    )
    assert route_response.status_code == 200
    expected = route(
        request.model_copy(update={"application_id": "trusted-app"}),
        classification,
        dependencies.environment.model_copy(
            update={"trusted_application_id": "trusted-app"}
        ),
        dependencies.bundle,
    )
    assert route_response.json()["decision_id"] == expected.decision_id

    forged_payload = _payload(request, classification)
    forged_payload["request"]["application_id"] = "forged-app"
    forged = client.post("/v1/route", json=forged_payload, headers=headers)
    assert forged.status_code == 422
    assert forged.json()["code"] == "caller_application_id_forbidden"
    assert "forged-app" not in forged.text

    execute_response = client.post(
        "/v1/execute", json=_payload(request, classification), headers=headers
    )
    assert execute_response.status_code == 200
    assert execute_response.json()["application_id"] == "trusted-app"

    tasks = client.get(
        "/v1/tasks",
        params={"application": "forged-app"},
        headers=headers,
    )
    assert tasks.status_code == 200
    assert tasks.json()["items"]
    assert all(item["application"] == "trusted-app" for item in tasks.json()["items"])


def test_concurrent_credentials_never_share_application_scope(tmp_path):
    base_request, classification, dependencies = setup(tmp_path)
    app = create_authenticated_app(
        applications=[
            _record("app-a", "secret-a", dependencies, "route"),
            _record("app-b", "secret-b", dependencies, "route"),
        ]
    )
    def route_as(index):
        expected = "app-a" if index % 2 == 0 else "app-b"
        secret = "secret-a" if index % 2 == 0 else "secret-b"
        request = base_request.model_copy(
            update={"task_id": f"task-{index}", "trace_id": f"trace-{index}"}
        )
        with TestClient(app) as client:
            response = client.post(
                "/v1/route",
                json=_payload(request, classification),
                headers=_authorization(secret),
            )
        return expected, index, response

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(route_as, range(64)))

    for expected, index, response in results:
        assert response.status_code == 200
        request = base_request.model_copy(
            update={"task_id": f"task-{index}", "trace_id": f"trace-{index}"}
        )
        expected_decision = route(
            request.model_copy(update={"application_id": expected}),
            classification,
            dependencies.environment.model_copy(
                update={"trusted_application_id": expected}
            ),
            dependencies.bundle,
        )
        assert response.json()["decision_id"] == expected_decision.decision_id


def test_cross_application_task_and_telemetry_reads_fail_closed(tmp_path):
    request, classification, dependencies = setup(tmp_path)
    production_task = _persist_production_task(dependencies, "app-a", "app-a")
    app = create_authenticated_app(
        applications=[
            _record("app-a", "secret-a", dependencies, "execute", "read"),
            _record("app-b", "secret-b", dependencies, "execute", "read"),
        ]
    )
    client = TestClient(app)
    executed = client.post(
        "/v1/execute",
        json=_payload(request, classification),
        headers=_authorization("secret-a"),
    )
    assert executed.status_code == 200
    dependencies.clock.advance(1)

    assert client.get(
        f"/v1/tasks/{production_task.task_id}", headers=_authorization("secret-a")
    ).status_code == 200
    hidden = client.get(
        f"/v1/tasks/{production_task.task_id}", headers=_authorization("secret-b")
    )
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "task_not_found"

    own_tasks = client.get("/v1/tasks", headers=_authorization("secret-a")).json()
    other_tasks = client.get(
        "/v1/tasks",
        params={"application": "app-a"},
        headers=_authorization("secret-b"),
    ).json()
    assert own_tasks["total"] == 1
    assert other_tasks["total"] == 0

    own_summary = client.get(
        "/v1/telemetry/summary", headers=_authorization("secret-a")
    ).json()
    other_summary = client.get(
        "/v1/telemetry/summary", headers=_authorization("secret-b")
    ).json()
    assert own_summary["metrics"]["total_tasks"] == 1
    assert other_summary["metrics"]["total_tasks"] == 0


def test_configuration_accepts_only_unique_valid_digests_and_records(tmp_path):
    _, _, dependencies = setup(tmp_path)
    record = _record("app-a", "secret-a", dependencies, "read")
    app = create_authenticated_app(
        applications={record.credential_digest: record}
    )
    assert TestClient(app).get(
        "/v1/tasks", headers=_authorization("secret-a")
    ).status_code == 200

    with pytest.raises(ValueError, match="mapping key"):
        create_authenticated_app(applications={"0" * 64: record})
    with pytest.raises(ValueError, match="unique"):
        create_authenticated_app(applications=[record, record])
    with pytest.raises(ValueError, match="non-empty"):
        create_authenticated_app(applications=[])
    with pytest.raises(ValueError, match="lowercase"):
        AuthenticatedApplication(
            application_id="app",
            credential_digest="raw-secret",
            dependencies=dependencies,
            scopes=frozenset({"read"}),
        )


def test_dependency_exception_details_do_not_escape_response_or_asgi_boundary(tmp_path):
    request, classification, dependencies = setup(tmp_path)
    private = "private-dependency-detail"

    def unavailable_environment():
        raise RuntimeError(private)

    dependencies = replace(dependencies, environment=unavailable_environment)
    app = create_authenticated_app(
        applications=[_record("app-a", "secret-a", dependencies, "route")]
    )
    response = TestClient(app).post(
        "/v1/route",
        json=_payload(request, classification),
        headers=_authorization("secret-a"),
    )
    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "The request could not be completed.",
        "retryable": True,
    }
    assert private not in response.text
