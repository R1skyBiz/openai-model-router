from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event as sqlalchemy_event

from model_router.core.execution_contracts import (
    Attempt,
    ExecutionEvent,
    Failure,
    RecoveryAction,
    TaskResult,
    TaskStatus,
    ToolOutcome,
)
from model_router.core.phase4_contracts import HealthObservation, HealthSnapshot
from model_router.storage import SQLiteTaskRepository
from model_router.storage.migrations import upgrade_database
from model_router.storage.telemetry import read_telemetry_snapshot
from model_router.telemetry.demo import generate_demo, open_demo
from model_router.telemetry.evidence import initial_route, task_is_synthetic
from model_router.telemetry.query import TelemetryQuery
from model_router.service.telemetry import register_telemetry


NOW = datetime(2026, 9, 6, 20, tzinfo=UTC)


@pytest.fixture(scope="module")
def telemetry_client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("phase5-api")
    generate_demo(directory, now=NOW, count=30)
    query = TelemetryQuery(
        open_demo(directory), now=NOW, application_scope=None, synthetic=True
    )
    app = FastAPI()
    register_telemetry(app, query=query)
    return TestClient(app), query


def test_all_telemetry_endpoints_are_typed_and_backed_by_persisted_evidence(telemetry_client):
    client, _query = telemetry_client
    for endpoint in (
        "summary", "spend", "routing", "efficacy", "health", "models",
        "task-families", "policies",
    ):
        response = client.get(f"/v1/telemetry/{endpoint}")
        assert response.status_code == 200, (endpoint, response.text)
        assert response.json()["meta"]["synthetic"] is True

    health = client.get("/v1/telemetry/health").json()
    assert health["production_ready"] is False
    assert health["outbox_pending"] > 0
    assert health["readiness_note"]

    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert {"Summary", "Spend", "Routing", "Health", "TaskList", "TaskDetail"} <= set(schemas)


def test_task_list_scoping_filters_half_open_window_and_pagination_are_deterministic(telemetry_client):
    client, _query = telemetry_client
    first = client.get("/v1/tasks", params={"offset": 0, "limit": 7}).json()
    second = client.get("/v1/tasks", params={"offset": 7, "limit": 7}).json()
    assert first["total"] == second["total"] == 30
    assert {item["task_id"] for item in first["items"]}.isdisjoint(
        item["task_id"] for item in second["items"]
    )
    ordering = [(item["created_at"], item["task_id"]) for item in first["items"]]
    assert ordering == sorted(ordering, reverse=True)

    application = first["items"][0]["application"]
    scoped = client.get("/v1/tasks", params={"application": application, "limit": 100}).json()
    assert scoped["items"] and all(item["application"] == application for item in scoped["items"])

    newest = datetime.fromisoformat(first["items"][0]["created_at"].replace("Z", "+00:00"))
    excluded = client.get(
        "/v1/tasks",
        params={"start": (newest + timedelta(microseconds=1)).isoformat(), "end": NOW.isoformat()},
    ).json()
    assert excluded["total"] == 0


def test_task_timeline_is_stable_paginated_and_allowlisted(telemetry_client):
    client, _query = telemetry_client
    task_id = client.get("/v1/tasks", params={"limit": 1}).json()["items"][0]["task_id"]
    full = client.get(f"/v1/tasks/{task_id}", params={"view": "timeline", "limit": 500})
    assert full.status_code == 200
    body = full.json()
    assert body["timeline"]
    stamps = [
        (datetime.fromisoformat(step["timestamp"].replace("Z", "+00:00")), step["id"])
        for step in body["timeline"]
    ]
    assert stamps == sorted(stamps)
    assert all(
        set(step["metadata"]) <= {
            "attempt_id", "decision_id", "tool_event_id", "evaluation_id",
            "task_family", "complexity", "validation_level",
            "routing_result", "executable", "purpose", "attempt_status", "tool",
            "operation", "tool_status", "side_effecting", "replay_safe", "check",
            "applicable", "validation_status", "rubric_version", "score", "score_min",
            "score_max",
            "health_evidence", "health_observed_at", "health_valid_until",
            "health_component_count", "health_component_states",
            "health_circuit_states",
        }
        for step in body["timeline"]
    )
    assert "synthetic content never persisted" not in full.text
    assert "rationale_details" not in full.text
    assert "phase4_config" not in full.text
    health_steps = [step for step in body["timeline"] if step["health_snapshot_id"]]
    assert health_steps
    assert all(step["metadata"]["health_evidence"] == "retained" for step in health_steps)
    assert all(step["metadata"]["health_component_count"] > 0 for step in health_steps)

    page = client.get(
        f"/v1/tasks/{task_id}", params={"view": "timeline", "offset": 1, "limit": 2}
    ).json()
    assert page["total"] == body["total"]
    assert page["timeline"] == body["timeline"][1:3]


def test_unknown_task_and_attempt_costs_are_partial_even_with_zero_known_subtotal(telemetry_client):
    client, _query = telemetry_client
    response = client.get(
        "/v1/tasks/synthetic-demo-0005", params={"view": "timeline", "limit": 500}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task"]["cost"] == {
        "amount": None,
        "known_subtotal": "0",
        "missing_count": 1,
        "status": "partial",
    }
    unknown_attempt_costs = [
        step["cost"]
        for step in body["timeline"]
        if step["kind"].startswith("ATTEMPT_")
        and step["cost"] is not None
        and step["cost"]["amount"] is None
    ]
    assert unknown_attempt_costs
    assert all(cost["status"] == "partial" for cost in unknown_attempt_costs)
    assert all(cost["known_subtotal"] == "0" for cost in unknown_attempt_costs)


def test_timeline_charges_each_fee_once_and_starts_have_no_final_evidence(telemetry_client):
    client, query = telemetry_client
    task_id = "synthetic-demo-0007"
    response = client.get(
        f"/v1/tasks/{task_id}", params={"view": "timeline", "limit": 500}
    )
    assert response.status_code == 200
    timeline = response.json()["timeline"]
    starts = [step for step in timeline if step["kind"] == "ATTEMPT_STARTED"]
    completions = [step for step in timeline if step["kind"] == "ATTEMPT_COMPLETED"]
    assert starts
    assert completions
    assert all(step["title"].endswith("· Started") for step in starts)
    assert all(step["title"].endswith("· Completed") for step in completions)
    assert {step["title"] for step in starts}.isdisjoint(
        step["title"] for step in completions
    )
    generation_steps = [
        step for step in (*starts, *completions)
        if step["metadata"]["purpose"] == "generation"
    ]
    evaluation_steps = [
        step for step in (*starts, *completions)
        if step["metadata"]["purpose"] == "evaluation"
    ]
    assert generation_steps and all(step["title"].startswith("Attempt ") for step in generation_steps)
    assert evaluation_steps and all(step["title"].startswith("Evaluation ") for step in evaluation_steps)
    assert all(step["cost"] is None and step["latency_ms"] is None for step in starts)
    assert all(step["failure_type"] is None for step in starts)
    assert all("attempt_status" not in step["metadata"] for step in starts)
    assert all(all(value is None for value in step["tokens"].values()) for step in starts)
    assert all(
        step["cost"] is None
        for step in timeline
        if step["kind"] == "VALIDATION_COMPLETED"
        and step["metadata"].get("rubric_version") is not None
    )

    task = next(
        task for task in read_telemetry_snapshot(query.repository).tasks
        if task.task_id == task_id
    )
    shadow_known = sum(
        (
            attempt.actual_cost_usd
            for run in task.shadow_runs
            for attempt in run.attempts
            if attempt.actual_cost_usd is not None
        ),
        Decimal("0"),
    )
    projected_known = sum(
        (
            Decimal(step["cost"]["known_subtotal"])
            for step in timeline
            if step["cost"] is not None
        ),
        Decimal("0"),
    )
    assert projected_known == task.known_cost_usd + shadow_known


def test_legacy_synthetic_provenance_falls_back_to_production_attempt_decision(telemetry_client):
    _client, query = telemetry_client
    task = read_telemetry_snapshot(query.repository).tasks[0]
    legacy = task.model_copy(update={"initial_decision": None, "decisions": ()})
    assert initial_route(legacy) is not None
    assert task_is_synthetic(legacy) is True


def test_application_scope_cannot_be_overridden_and_production_excludes_demo(telemetry_client):
    _client, query = telemetry_client
    application = query.tasks(limit=1)["items"][0]["application"]
    scoped = TelemetryQuery(
        query.repository, now=NOW, application_scope=application, synthetic=True
    )
    requested = "synthetic-studio" if application != "synthetic-studio" else "synthetic-support"
    result = scoped.tasks({"application": requested}, limit=100)
    assert result["items"]
    assert all(item["application"] == application for item in result["items"])

    production = TelemetryQuery(
        query.repository, now=NOW, application_scope=None, synthetic=False
    )
    assert production.tasks()["total"] == 0


def test_production_telemetry_without_trusted_application_scope_fails_closed(tmp_path):
    url = "sqlite+pysqlite:///" + str(tmp_path / "unscoped.db")
    upgrade_database(url)
    repository = SQLiteTaskRepository(url, journal_path=tmp_path / "pending.jsonl")
    task = TaskResult(
        task_id="legacy-unscoped",
        trace_id="legacy-unscoped-trace",
        application_id=None,
        status=TaskStatus.CREATED,
        policy_version="policy-v1",
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
    )
    repository.create(
        task,
        ExecutionEvent(
            event_id="legacy-unscoped-created",
            task_id=task.task_id,
            trace_id=task.trace_id,
            kind="TASK_CREATED",
            occurred_at=task.created_at,
            policy_version=task.policy_version,
        ),
        scope="embedded",
        key_digest=None,
        request_digest="legacy-unscoped-request",
    )
    query = TelemetryQuery(
        repository, now=NOW, application_scope=None, synthetic=False
    )
    assert query.tasks()["total"] == 0
    assert query.task_detail(task.task_id) is None


def test_invalid_filters_and_validation_errors_are_sanitized(telemetry_client):
    client, _query = telemetry_client
    private = "private-value-must-not-echo"
    for params in (
        {"start": private},
        {"start": "2026-09-06T20:00:00", "end": NOW.isoformat()},
        {"start": NOW.isoformat(), "end": (NOW - timedelta(days=1)).isoformat()},
        {"limit": private},
    ):
        response = client.get("/v1/tasks", params=params)
        assert response.status_code == 422
        assert private not in response.text
        assert response.json()["code"] in {"invalid_filter", "invalid_request"}


def test_unknown_health_and_unsupported_repository_are_safe(tmp_path):
    url = "sqlite+pysqlite:///" + str(tmp_path / "empty.db")
    upgrade_database(url)
    empty = SQLiteTaskRepository(url, journal_path=tmp_path / "pending.jsonl")
    app = FastAPI()
    register_telemetry(
        app,
        query=TelemetryQuery(empty, now=NOW, application_scope=None, synthetic=True),
    )
    health = TestClient(app).get("/v1/telemetry/health")
    assert health.status_code == 200
    assert health.json()["state"] == "UNKNOWN"
    assert health.json()["components"] == []

    future_observation = HealthObservation(
        component="provider",
        model="future-model",
        state="DEGRADED",
        observed_at=NOW + timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=2),
    )
    future_task = TaskResult(
        task_id="future-health",
        trace_id="future-health-trace",
        application_id="app-a",
        status=TaskStatus.CREATED,
        policy_version="policy-v1",
        created_at=NOW - timedelta(days=1),
        updated_at=NOW - timedelta(days=1),
        health_snapshots=(HealthSnapshot(
            snapshot_id="future-snapshot",
            config_version="health-v1",
            observed_at=NOW + timedelta(minutes=1),
            valid_until=NOW + timedelta(minutes=2),
            observations=(future_observation,),
        ),),
    )
    empty.create(
        future_task,
        ExecutionEvent(
            event_id="future-health-created",
            task_id=future_task.task_id,
            trace_id=future_task.trace_id,
            kind="TASK_CREATED",
            occurred_at=future_task.created_at,
            policy_version=future_task.policy_version,
        ),
        scope="app-a",
        key_digest=None,
        request_digest="future-health-request",
    )
    future_app = FastAPI()
    register_telemetry(
        future_app,
        query=TelemetryQuery(
            empty, now=NOW, application_scope="app-a", synthetic=False
        ),
    )
    future_health = TestClient(future_app).get("/v1/telemetry/health").json()
    assert future_health["components"][0]["state"] == "UNKNOWN"
    assert future_health["degraded_periods"] == []

    unavailable = FastAPI()
    register_telemetry(
        unavailable,
        query=TelemetryQuery(object(), now=NOW, application_scope=None, synthetic=True),
    )
    response = TestClient(unavailable).get("/v1/telemetry/summary")
    assert response.status_code == 503
    assert response.json() == {
        "code": "dependency_unavailable",
        "message": "Telemetry storage is unavailable.",
        "retryable": True,
    }


def test_shared_health_snapshot_projects_one_degraded_interval(tmp_path):
    url = "sqlite+pysqlite:///" + str(tmp_path / "shared-health.db")
    upgrade_database(url)
    repository = SQLiteTaskRepository(url, journal_path=tmp_path / "pending.jsonl")
    observation = HealthObservation(
        component="database",
        state="DEGRADED",
        observed_at=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=1),
    )
    shared = HealthSnapshot(
        snapshot_id="shared-health-snapshot",
        config_version="health-v1",
        observed_at=observation.observed_at,
        valid_until=observation.valid_until,
        observations=(observation,),
    )
    for index in range(2):
        task = TaskResult(
            task_id=f"shared-health-task-{index}",
            trace_id=f"shared-health-trace-{index}",
            application_id="app-a",
            status=TaskStatus.CREATED,
            policy_version="policy-v1",
            created_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=1),
            health_snapshots=(shared,),
        )
        repository.create(
            task,
            ExecutionEvent(
                event_id=f"shared-health-created-{index}",
                task_id=task.task_id,
                trace_id=task.trace_id,
                kind="TASK_CREATED",
                occurred_at=task.created_at,
                policy_version=task.policy_version,
            ),
            scope="app-a",
            key_digest=None,
            request_digest=f"shared-health-request-{index}",
        )
    health = TelemetryQuery(
        repository, now=NOW, application_scope="app-a", synthetic=False
    ).health()
    assert health["degraded_periods"] == [{
        "start": "2026-09-06T19:59:00Z",
        "end": "2026-09-06T20:01:00Z",
        "component": "database",
        "state": "DEGRADED",
    }]


def test_sqlite_snapshot_explicitly_begins_before_selects(tmp_path):
    url = "sqlite+pysqlite:///" + str(tmp_path / "snapshot.db")
    upgrade_database(url)
    repository = SQLiteTaskRepository(url, journal_path=tmp_path / "pending.jsonl")
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.strip().upper())

    sqlalchemy_event.listen(repository.engine, "before_cursor_execute", record)
    try:
        read_telemetry_snapshot(repository)
    finally:
        sqlalchemy_event.remove(repository.engine, "before_cursor_execute", record)
    assert statements[0] == "BEGIN"
    assert statements[1].startswith("SELECT")


def test_same_tick_timeline_preserves_persisted_retry_and_tool_causality(tmp_path):
    url = "sqlite+pysqlite:///" + str(tmp_path / "same-tick.db")
    upgrade_database(url)
    repository = SQLiteTaskRepository(url, journal_path=tmp_path / "pending.jsonl")
    created_at = NOW - timedelta(seconds=1)
    failure = Failure(
        failure_type="TIMEOUT",
        source="provider",
        stage="invocation",
        cause_code="retained_timeout",
        retryable=True,
    )
    tool_failure = Failure(
        failure_type="TOOL_FAILURE",
        source="tool",
        stage="tool",
        cause_code="retained_tool_failure",
    )
    base = TaskResult(
        task_id="same-tick",
        trace_id="same-tick-trace",
        application_id="app-a",
        status=TaskStatus.CREATED,
        policy_version="policy-v1",
        created_at=created_at,
        updated_at=created_at,
    )
    created = ExecutionEvent(
        event_id="created",
        task_id=base.task_id,
        trace_id=base.trace_id,
        kind="TASK_CREATED",
        occurred_at=created_at,
        policy_version=base.policy_version,
    )
    repository.create(
        base,
        created,
        scope="app-a",
        key_digest=None,
        request_digest="same-tick-request",
    )
    first = Attempt(
        attempt_id="first-attempt",
        task_id=base.task_id,
        trace_id=base.trace_id,
        sequence=1,
        status="failed",
        started_at=NOW - timedelta(milliseconds=10),
        completed_at=NOW,
        actual_cost_usd="0",
        pricing_version="price-v1",
        failure=failure,
    )
    second = Attempt(
        attempt_id="second-attempt",
        task_id=base.task_id,
        trace_id=base.trace_id,
        sequence=2,
        status="started",
        started_at=NOW,
        pricing_version="price-v1",
    )
    tool = ToolOutcome(
        tool_event_id="failed-tool",
        tool="safe-tool",
        operation="read",
        status="failed",
        failure=tool_failure,
        cost_usd="0",
    )
    task = base.model_copy(update={
        "status": TaskStatus.RECOVERING,
        "updated_at": NOW + timedelta(milliseconds=1),
        "revision": 1,
        "attempts": (first, second),
        "tool_events": (tool,),
        "recovery_actions": (
            RecoveryAction(
                action="retry_backoff",
                failure="TIMEOUT",
                reason="retained_retry",
            ),
            RecoveryAction(
                action="retry_tool",
                failure="TOOL_FAILURE",
                reason="retained_tool_retry",
            ),
        ),
    })

    def event(event_id, kind, occurred_at, **values):
        return ExecutionEvent(
            event_id=event_id,
            task_id=base.task_id,
            trace_id=base.trace_id,
            kind=kind,
            occurred_at=occurred_at,
            policy_version=base.policy_version,
            **values,
        )

    repository.save(task, (
        event(
            "z-generation-completed",
            "ATTEMPT_COMPLETED",
            NOW,
            attempt_id=first.attempt_id,
            failure_type="TIMEOUT",
        ),
        event(
            "a-generation-recovery",
            "RECOVERY_SELECTED",
            NOW,
            attempt_id=first.attempt_id,
            action="retry_backoff",
        ),
        event(
            "m-next-attempt-started",
            "ATTEMPT_STARTED",
            NOW,
            attempt_id=second.attempt_id,
        ),
        event(
            "z-tool-completed",
            "TOOL_COMPLETED",
            NOW + timedelta(milliseconds=1),
            tool_event_id=tool.tool_event_id,
            failure_type="TOOL_FAILURE",
        ),
        event(
            "a-tool-recovery",
            "RECOVERY_SELECTED",
            NOW + timedelta(milliseconds=1),
            action="retry_tool",
        ),
    ), expected_revision=0)

    detail = TelemetryQuery(
        repository,
        now=NOW + timedelta(seconds=1),
        application_scope="app-a",
        synthetic=False,
    ).task_detail(base.task_id, limit=500)
    assert detail is not None
    assert [step["kind"] for step in detail["timeline"]] == [
        "TASK_CREATED",
        "ATTEMPT_COMPLETED",
        "RECOVERY_SELECTED",
        "ATTEMPT_STARTED",
        "TOOL_COMPLETED",
        "RECOVERY_SELECTED",
    ]
