from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from model_router.health import HealthService, SyntheticHealthSource
from model_router.policy.phase4 import load_phase4
from model_router.service import create_app

from phase3_support import setup


def _health(dependencies):
    phase4 = load_phase4("config/phase4.yaml", dependencies.bundle)
    health = HealthService(dependencies.clock, phase4.health)
    SyntheticHealthSource(health).seed(models=dependencies.environment.models,
        provider_capabilities=("text_input", "text_output"))
    return health


def _with_health(dependencies):
    return replace(dependencies, health=_health(dependencies))


def _request_payload(request):
    payload = request.model_dump(mode="json")
    payload["input"] = request.input
    return payload


def test_liveness_never_reads_environment_or_calls_provider(tmp_path):
    _, _, dependencies = setup(tmp_path)

    def forbidden_environment():
        raise AssertionError("liveness read an execution dependency")

    dependencies = replace(dependencies, environment=forbidden_environment)
    response = TestClient(create_app(dependencies)).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"live": True, "state": "HEALTHY"}
    assert dependencies.provider.call_count == 0


def test_unconfigured_health_is_explicitly_not_ready_but_live(tmp_path):
    _, _, dependencies = setup(tmp_path)
    client = TestClient(create_app(dependencies))
    assert client.get("/health/live").status_code == 200
    ready = client.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["blockers"] == ["health_service_unconfigured"]
    assert dependencies.provider.call_count == 0


def test_ready_uses_fresh_snapshots_without_running_provider_probes(tmp_path):
    _, _, dependencies = setup(tmp_path)
    dependencies = _with_health(dependencies)
    client = TestClient(create_app(dependencies))
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["state"] == "HEALTHY"
    assert response.json()["snapshot_id"].startswith("health-")
    assert dependencies.provider.call_count == 0


def test_safe_degraded_and_unhealthy_dependency_readiness(tmp_path):
    _, _, dependencies = setup(tmp_path)
    health = _health(dependencies)
    dependencies = replace(dependencies, health=health)
    client = TestClient(create_app(dependencies))

    health.observe("telemetry", state="DEGRADED")
    degraded = client.get("/health/ready")
    assert degraded.status_code == 200
    assert degraded.json()["state"] == "DEGRADED"

    health.observe("database", state="UNHEALTHY")
    unhealthy = client.get("/health/ready")
    assert unhealthy.status_code == 503
    assert unhealthy.json()["ready"] is False
    assert "database:unhealthy" in unhealthy.json()["blockers"]
    assert dependencies.provider.call_count == 0


def test_stale_health_is_not_ready(tmp_path):
    _, _, dependencies = setup(tmp_path)
    health = _health(dependencies)
    dependencies = replace(dependencies, health=health)
    dependencies.clock.advance(health.config.freshness_ms)
    response = TestClient(create_app(dependencies)).get("/health/ready")
    assert response.status_code == 503
    assert any(blocker.endswith(":stale") for blocker in response.json()["blockers"])
    assert dependencies.provider.call_count == 0


def test_components_are_sanitized_and_snapshot_only(tmp_path):
    request, _, dependencies = setup(tmp_path)
    health = _health(dependencies)
    dependencies = replace(dependencies, health=health)
    health.observe("provider", model="luna", failure="RATE_LIMIT", latency_ms=12)

    response = TestClient(create_app(dependencies)).get("/health/components")
    assert response.status_code == 200
    body = response.json()
    assert body["config_version"] == health.config.version
    assert body["components"]
    assert {"component", "state", "observed_at", "valid_until", "circuit_state"} <= set(
        body["components"][0]
    )
    assert request.input not in response.text
    assert "private" not in response.text
    assert dependencies.provider.call_count == 0


def test_health_http_uses_one_snapshot_for_each_response(tmp_path):
    _, _, dependencies = setup(tmp_path)
    health = _health(dependencies)
    dependencies = replace(dependencies, health=health)
    original = health.snapshot
    calls = []

    def counted_snapshot():
        snapshot = original()
        calls.append(snapshot)
        return snapshot

    health.snapshot = counted_snapshot
    client = TestClient(create_app(dependencies))

    components = client.get("/health/components")
    assert components.status_code == 200
    assert len(calls) == 1
    assert components.json()["snapshot_id"] == calls[0].snapshot_id
    assert components.json()["components"] == [
        item.model_dump(mode="json") for item in calls[0].observations
    ]

    calls.clear()
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert len(calls) == 1
    assert ready.json()["snapshot_id"] == calls[0].snapshot_id


def test_route_only_uses_latest_health_projection_without_execution(tmp_path):
    request, classification, dependencies = setup(tmp_path)
    health = _health(dependencies)
    dependencies = replace(dependencies, health=health)
    payload = {
        "request": _request_payload(request),
        "classification": classification.model_dump(mode="json"),
    }
    response = TestClient(create_app(dependencies)).post("/v1/route", json=payload)
    assert response.status_code == 200
    assert response.json()["health_snapshot_id"] == health.snapshot().snapshot_id
    assert dependencies.provider.call_count == 0


def test_readiness_prerequisites_are_reported_without_provider_calls(tmp_path):
    _, _, dependencies = setup(tmp_path)
    health = _health(dependencies)
    environment = dependencies.environment.model_copy(
        update={"durable_retention": False}
    )
    dependencies = replace(
        dependencies,
        health=health,
        environment=environment,
        controls=dependencies.controls.model_copy(update={"authorized": False}),
        limits=None,
    )
    response = TestClient(create_app(dependencies)).get("/health/ready")
    assert response.status_code == 503
    assert {"approval_required", "finite_execution_limits_required", "durable_retention_unavailable"} <= set(
        response.json()["blockers"]
    )
    assert dependencies.provider.call_count == 0


def test_route_http_checks_requested_capability_health_without_dispatch(tmp_path):
    request,classification,deps=setup(tmp_path)
    health=_health(deps)
    for alias in deps.environment.models:
        health.observe('provider',model=alias,capability='structured_outputs',state='UNHEALTHY')
    deps=replace(deps,health=health)
    request=request.model_copy(update={'requirements':(*request.requirements,'structured_outputs')})
    response=TestClient(create_app(deps)).post('/v1/route',json={
        'request':_request_payload(request),'classification':classification.model_dump(mode='json')})
    assert response.status_code==422
    assert response.json()['failure_type']=='PROVIDER_FAILURE'
    assert deps.provider.call_count==0
