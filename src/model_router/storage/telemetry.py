"""Read-only, transactionally consistent telemetry evidence from SQLite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import literal_column, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from model_router.core.execution_contracts import (
    ExecutionEvent,
    RepositoryUnavailable,
    TaskResult,
)
from model_router.storage.models import OutboxRow, TaskRow
from model_router.storage.repository import SQLiteTaskRepository


@dataclass(frozen=True)
class TelemetrySnapshot:
    """One SQLite read snapshot, including acknowledged event history."""

    tasks: tuple[TaskResult, ...]
    events: tuple[ExecutionEvent, ...]
    pending_event_ids: frozenset[str]
    pending_occurred_at: tuple[datetime, ...]


def read_telemetry_snapshot(repository: object) -> TelemetrySnapshot:
    """Read tasks and their complete outbox history in one database transaction."""

    if not isinstance(repository, SQLiteTaskRepository):
        raise RepositoryUnavailable("telemetry storage is unsupported")
    try:
        # Python's legacy sqlite transaction mode does not issue BEGIN for a
        # SELECT.  Start it explicitly so both tables come from one snapshot.
        with repository.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN")
            with Session(bind=connection) as session:
                task_payloads = session.scalars(
                    select(TaskRow.payload_json).order_by(TaskRow.task_id)
                ).all()
                # The schema has no event sequence column. SQLite rowid is the
                # retained append order and is therefore the only factual
                # tie-break for events emitted at the same instant.
                outbox_rowid = literal_column("outbox.rowid")
                outbox_rows = session.execute(
                    select(
                        OutboxRow.event_id,
                        OutboxRow.occurred_at,
                        OutboxRow.payload_json,
                        OutboxRow.acknowledged_at,
                        outbox_rowid,
                    ).order_by(OutboxRow.occurred_at, outbox_rowid)
                ).all()
            connection.rollback()
        tasks = tuple(TaskResult.model_validate_json(payload) for payload in task_payloads)
        events = tuple(
            ExecutionEvent.model_validate_json(row.payload_json) for row in outbox_rows
        )
        pending_indexes = tuple(
            index for index, row in enumerate(outbox_rows) if row.acknowledged_at is None
        )
        return TelemetrySnapshot(
            tasks=tasks,
            events=events,
            pending_event_ids=frozenset(outbox_rows[index].event_id for index in pending_indexes),
            pending_occurred_at=tuple(events[index].occurred_at for index in pending_indexes),
        )
    except (SQLAlchemyError, TypeError, ValueError):
        raise RepositoryUnavailable("telemetry storage is unavailable") from None


def read_evidence(
    repository: object,
) -> tuple[tuple[TaskResult, ...], tuple[ExecutionEvent, ...]]:
    """Small validation helper for consumers that only need retained records."""

    snapshot = read_telemetry_snapshot(repository)
    return snapshot.tasks, snapshot.events


__all__ = ["TelemetrySnapshot", "read_evidence", "read_telemetry_snapshot"]
