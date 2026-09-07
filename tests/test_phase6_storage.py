from __future__ import annotations

import multiprocessing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from model_router.core.execution_contracts import ExecutionEvent, IdempotencyConflict, TaskResult, TaskStatus
from model_router.storage import (
    SQLTaskRepository,
    SQLiteTaskRepository,
    downgrade_database,
    migrate_database,
    upgrade_database,
)
from model_router.storage.models import OutboxRow


NOW = datetime(2026, 9, 7, tzinfo=UTC)


def _task(task_id: str, application_id: str = "app-a") -> TaskResult:
    return TaskResult(
        task_id=task_id,
        trace_id=f"trace-{task_id}",
        application_id=application_id,
        status=TaskStatus.CREATED,
        policy_version="policy-v1",
        created_at=NOW,
        updated_at=NOW,
    )


def _event(task_id: str, event_id: str, *, at: datetime = NOW) -> ExecutionEvent:
    return ExecutionEvent(
        event_id=event_id,
        task_id=task_id,
        trace_id=f"trace-{task_id}",
        kind="TASK_CREATED",
        occurred_at=at,
        policy_version="policy-v1",
    )


def _create_claim(args: tuple[str, str, str]) -> str:
    database_url, journal_path, task_id = args
    repository = SQLiteTaskRepository(database_url, journal_path=journal_path)
    duplicate = repository.create(
        _task(task_id),
        _event(task_id, f"event-{task_id}"),
        scope="app-a",
        key_digest="same-key",
        request_digest="same-request",
    )
    return "created" if duplicate is None else duplicate.task_id


def _append_journal(args: tuple[str, str, str]) -> None:
    database_url, journal_path, task_id = args
    repository = SQLiteTaskRepository(database_url, journal_path=journal_path)
    repository.retain_pending(_task(task_id).model_copy(update={"revision": 1}), ())


def test_sqlite_process_claim_and_journal_are_cross_process_safe(tmp_path: Path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'router.sqlite'}"
    journal = str(tmp_path / "pending.jsonl")
    upgrade_database(database_url)
    context = multiprocessing.get_context("spawn")
    with context.Pool(4) as pool:
        results = pool.map(
            _create_claim,
            [(database_url, journal, f"task-{index}") for index in range(4)],
        )
    assert results.count("created") == 1
    assert len(set(item for item in results if item != "created")) == 1

    with context.Pool(4) as pool:
        pool.map(
            _append_journal,
            [(database_url, journal, f"pending-{index}") for index in range(4)],
        )
    assert len((tmp_path / "pending.jsonl").read_text().splitlines()) == 4


def test_scoped_reads_and_leased_outbox_ownership(tmp_path: Path):
    url = f"sqlite+pysqlite:///{tmp_path / 'router.sqlite'}"
    upgrade_database(url)
    repository = SQLTaskRepository(url, journal_path=tmp_path / "pending.jsonl")
    created = _task("task-1")
    repository.create(
        created,
        _event("task-1", "event-1"),
        scope="app-a",
        key_digest=None,
        request_digest="request",
    )
    running = created.model_copy(update={"revision": 1, "status": TaskStatus.RUNNING})
    repository.save(
        running,
        (_event("task-1", "event-2", at=NOW + timedelta(seconds=1)).model_copy(update={"kind": "ATTEMPT_STARTED"}),),
        expected_revision=0,
        scope="app-a",
    )
    assert repository.get("task-1", scope="app-a") is not None
    with pytest.raises(IdempotencyConflict):
        repository.get("task-1", scope="app-b")

    claimed = repository.claim_outbox("worker-a", limit=10)
    assert [item.event_id for item in claimed] == ["event-1", "event-2"]
    assert repository.claim_outbox("worker-b", limit=10) == ()
    assert repository.ack_outbox("event-1", owner_id="worker-b") is False
    assert repository.ack_outbox("event-1") is False
    assert repository.ack_outbox("event-1", owner_id="worker-a") is True
    assert [item.event_id for item in repository.pending_outbox()] == ["event-2"]
    with Session(repository.engine) as session:
        assert [row.sequence for row in session.scalars(select(OutboxRow).order_by(OutboxRow.sequence))] == [1, 2]


def test_migration_preserves_history_and_round_trips_phase6(tmp_path: Path):
    url = f"sqlite+pysqlite:///{tmp_path / 'router.sqlite'}"
    migrate_database(url, "0002_phase4_verification")
    legacy = SQLiteTaskRepository(url, journal_path=tmp_path / "pending.jsonl")
    # Phase 2 code cannot use the Phase 6 ORM because its sequence column is not
    # present, so create representative history through schema-level SQL.
    with legacy.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO tasks (task_id,trace_id,status,policy_version,created_at,updated_at,revision,idempotency_scope,key_digest,request_digest,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("task-1", "trace-task-1", "created", "policy-v1", NOW, NOW, 0, "app-a", None, "r", _task("task-1").model_dump_json()),
        )
        for event_id in ("legacy-1", "legacy-2"):
            connection.exec_driver_sql(
                "INSERT INTO outbox (event_id,task_id,kind,occurred_at,payload_json,acknowledged_at) VALUES (?,?,?,?,?,NULL)",
                (event_id, "task-1", "TASK_CREATED", NOW, _event("task-1", event_id).model_dump_json()),
            )
    upgrade_database(url)
    current = SQLTaskRepository(url, journal_path=tmp_path / "pending.jsonl")
    assert current.current_migration_revision() == "0003_phase6_durable_storage"
    with Session(current.engine) as session:
        assert [row.sequence for row in session.scalars(select(OutboxRow).order_by(OutboxRow.sequence))] == [1, 2]
    downgrade_database(url, "0002_phase4_verification")
    assert "sequence" not in {column["name"] for column in inspect(current.engine).get_columns("outbox")}
    upgrade_database(url)
    assert current.current_migration_revision() == "0003_phase6_durable_storage"
