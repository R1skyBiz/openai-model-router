"""SQLite SQLAlchemy repository with transactional outbox and recovery journal."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, RLock
from typing import Any, Callable

from sqlalchemy import Engine, create_engine, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from model_router.core.execution_contracts import (
    AttemptStatus,
    ConcurrentUpdate,
    ExecutionEvent,
    IdempotencyConflict,
    RepositoryUnavailable,
    TaskResult,
    TaskStatus,
)
from model_router.storage.models import (
    AttemptRow,
    Base,
    EvaluationRow,
    ModelCatalogVersionRow,
    OutboxRow,
    PolicyVersionRow,
    PricingVersionRow,
    RoutingDecisionRow,
    TaskRow,
    ToolEventRow,
)
from model_router.telemetry.events import event_payload, task_payload


_JOURNAL_LOCKS: dict[str, RLock] = {}
_JOURNAL_LOCKS_GUARD = Lock()


def _journal_lock(path: Path) -> RLock:
    identity = str(path.resolve())
    with _JOURNAL_LOCKS_GUARD:
        return _JOURNAL_LOCKS.setdefault(identity, RLock())


def _portable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _portable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_portable(item) for item in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(_portable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def create_schema(engine: Engine) -> None:
    """Explicit test helper; production schema changes go through Alembic."""

    Base.metadata.create_all(engine)


class SQLiteTaskRepository:
    """A synchronous local repository implementing the core ``TaskRepository`` port.

    Construction never creates tables. Call the Alembic upgrade helper (or the
    explicit ``create_schema`` test helper) before use.
    """

    def __init__(self, database_url: str, *, journal_path: str | Path):
        if not database_url.startswith("sqlite"):
            raise ValueError("Phase 3 repository requires a SQLite database URL")
        self.engine = create_engine(database_url, future=True)
        self.journal_path = Path(journal_path)
        self._journal_lock = _journal_lock(self.journal_path)

    def create(
        self,
        task: TaskResult,
        event: ExecutionEvent,
        *,
        scope: str,
        key_digest: str | None,
        request_digest: str,
    ) -> TaskResult | None:
        if event.task_id != task.task_id or event.kind != "TASK_CREATED":
            raise ValueError("create requires a matching TASK_CREATED event")
        if not scope or not request_digest:
            raise ValueError("scope and request_digest are required")
        try:
            with Session(self.engine) as session, session.begin():
                duplicate = self._find_duplicate(session, task.task_id, scope, key_digest)
                if duplicate is not None:
                    return self._resolve_duplicate(duplicate, request_digest)
                session.add(self._task_row(task, scope, key_digest, request_digest))
                self._insert_event(session, event)
            return None
        except IntegrityError:
            # A concurrent claimant may have won after our pre-check.
            try:
                with Session(self.engine) as session:
                    duplicate = self._find_duplicate(session, task.task_id, scope, key_digest)
                    if duplicate is None:
                        raise RepositoryUnavailable("storage transaction failed")
                    return self._resolve_duplicate(duplicate, request_digest)
            except (IdempotencyConflict, RepositoryUnavailable):
                raise
            except SQLAlchemyError:
                raise RepositoryUnavailable("storage unavailable") from None
        except IdempotencyConflict:
            raise
        except SQLAlchemyError:
            raise RepositoryUnavailable("storage unavailable") from None

    def save(
        self,
        task: TaskResult,
        events: tuple[ExecutionEvent, ...],
        *,
        expected_revision: int,
    ) -> None:
        if task.revision != expected_revision + 1:
            raise ConcurrentUpdate("new task revision must follow expected revision")
        if any(event.task_id != task.task_id for event in events):
            raise ValueError("event task_id does not match task")
        try:
            with Session(self.engine) as session, session.begin():
                row = session.get(TaskRow, task.task_id)
                if row is None or row.revision != expected_revision:
                    raise ConcurrentUpdate("task revision changed")
                previous = TaskResult.model_validate_json(row.payload_json)
                self._verify_task_progression(previous, task)
                self._persist_children(session, task)
                result = session.execute(
                    update(TaskRow)
                    .where(TaskRow.task_id == task.task_id, TaskRow.revision == expected_revision)
                    .values(
                        trace_id=task.trace_id,
                        status=task.status.value,
                        policy_version=task.policy_version,
                        updated_at=task.updated_at,
                        revision=task.revision,
                        payload_json=_json(task_payload(task)),
                    )
                )
                if result.rowcount != 1:
                    raise ConcurrentUpdate("task revision changed")
                for event in events:
                    self._insert_event(session, event)
        except ConcurrentUpdate:
            raise
        except IntegrityError:
            raise ConcurrentUpdate("conflicting immutable evidence") from None
        except SQLAlchemyError:
            raise RepositoryUnavailable("storage unavailable") from None

    def get(self, task_id: str) -> TaskResult | None:
        try:
            with Session(self.engine) as session:
                row = session.get(TaskRow, task_id)
                return None if row is None else TaskResult.model_validate_json(row.payload_json)
        except SQLAlchemyError:
            raise RepositoryUnavailable("storage unavailable") from None

    def retain_pending(self, task: TaskResult, events: tuple[ExecutionEvent, ...]) -> None:
        """Append and fsync a content-free recovery record."""

        record = {
            "expected_revision": max(0, task.revision - 1),
            "task": task_payload(task),
            "events": [event_payload(event) for event in events],
        }
        try:
            with self._journal_lock:
                self.journal_path.parent.mkdir(parents=True, exist_ok=True)
                with self.journal_path.open("a", encoding="utf-8") as stream:
                    stream.write(_json(record) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                self._fsync_directory(self.journal_path.parent)
        except (OSError, TypeError, ValueError):
            raise RepositoryUnavailable("recovery journal unavailable") from None

    def reconcile_pending(self) -> int:
        """Replay durable journal entries and retain only entries still failing."""

        with self._journal_lock:
            return self._reconcile_pending_unlocked()

    def _reconcile_pending_unlocked(self) -> int:
        """Run replay while the path-wide in-process journal lock is held."""

        if not self.journal_path.exists():
            return 0
        try:
            lines = self.journal_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            raise RepositoryUnavailable("recovery journal unavailable") from None
        retained: list[str] = []
        replayed = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                task = TaskResult.model_validate(item["task"])
                events = tuple(ExecutionEvent.model_validate(event) for event in item["events"])
                expected = int(item["expected_revision"])
                existing = self.get(task.task_id)
                if existing is not None and existing.revision == task.revision:
                    if task_payload(existing) != task_payload(task):
                        raise ConcurrentUpdate("journal conflicts with persisted task")
                    self._ensure_events(events)
                else:
                    self.save(task, events, expected_revision=expected)
                replayed += 1
            except (KeyError, TypeError, ValueError, ConcurrentUpdate, RepositoryUnavailable):
                retained.append(line)
        self._replace_journal(retained)
        return replayed

    def replay_pending(self) -> int:
        """Alias for callers that describe reconciliation as journal replay."""

        return self.reconcile_pending()

    def pending_outbox(self, *, limit: int = 100) -> tuple[ExecutionEvent, ...]:
        if limit <= 0:
            return ()
        try:
            with Session(self.engine) as session:
                rows = session.scalars(
                    select(OutboxRow)
                    .where(OutboxRow.acknowledged_at.is_(None))
                    .order_by(OutboxRow.occurred_at, OutboxRow.event_id)
                    .limit(limit)
                ).all()
                return tuple(ExecutionEvent.model_validate_json(row.payload_json) for row in rows)
        except SQLAlchemyError:
            raise RepositoryUnavailable("storage unavailable") from None

    def ack_outbox(self, event_id: str) -> None:
        """Idempotently acknowledge an event, including an already-acked event."""

        try:
            with Session(self.engine) as session, session.begin():
                session.execute(
                    update(OutboxRow)
                    .where(OutboxRow.event_id == event_id, OutboxRow.acknowledged_at.is_(None))
                    .values(acknowledged_at=datetime.now(UTC))
                )
        except SQLAlchemyError:
            raise RepositoryUnavailable("storage unavailable") from None

    def store_policy_version(self, version: str, snapshot: dict[str, Any]) -> None:
        self._store_immutable(PolicyVersionRow, version, snapshot)

    def store_model_catalog_version(self, version: str, snapshot: dict[str, Any]) -> None:
        self._store_immutable(ModelCatalogVersionRow, version, snapshot)

    def store_pricing_version(self, version: str, snapshot: dict[str, Any]) -> None:
        self._store_immutable(PricingVersionRow, version, snapshot)

    def pin_versions(
        self,
        *,
        policy_version: str,
        policy_snapshot: Mapping[str, Any],
        catalog_version: str,
        catalog_snapshot: Mapping[str, Any],
    ) -> None:
        """Atomically retain the immutable policy, catalog, and model prices in use."""

        pinned_policy = policy_snapshot.get("policy")
        if not isinstance(pinned_policy, Mapping) or pinned_policy.get("version") != policy_version:
            raise ValueError("policy snapshot version mismatch")
        if not isinstance(policy_snapshot.get("budgets"), Mapping) or not isinstance(
            policy_snapshot.get("validation"), Mapping
        ):
            raise ValueError("policy snapshot requires budgets and validation")
        if not isinstance(policy_snapshot.get("content_hash"), str) or not policy_snapshot["content_hash"]:
            raise ValueError("policy snapshot requires content hash")
        if catalog_snapshot.get("catalog_version") != catalog_version:
            raise ValueError("catalog snapshot version mismatch")
        models = catalog_snapshot.get("models")
        if not isinstance(models, Mapping):
            raise ValueError("catalog snapshot has no model mapping")
        pricing: list[tuple[str, str, dict[str, Any]]] = []
        for model_alias, model in models.items():
            if not isinstance(model, Mapping) or not isinstance(model.get("pricing"), Mapping):
                raise ValueError("catalog model has no pricing snapshot")
            price = model["pricing"]
            price_version = price.get("version")
            if not isinstance(price_version, str) or not price_version:
                raise ValueError("pricing snapshot has no version")
            pricing.append(
                (
                    price_version,
                    str(model_alias),
                    {
                        "model_alias": model_alias,
                        "provider_model_id": model.get("provider_model_id"),
                        "pricing_version": price_version,
                        "pricing": price,
                    },
                )
            )
        price_version_counts = {
            version: sum(1 for candidate, _, _ in pricing if candidate == version)
            for version, _, _ in pricing
        }
        try:
            with Session(self.engine) as session, session.begin():
                self._put_immutable(session, PolicyVersionRow, policy_version, policy_snapshot)
                self._put_immutable(session, ModelCatalogVersionRow, catalog_version, catalog_snapshot)
                for price_version, model_alias, price_snapshot in pricing:
                    storage_version = (
                        price_version
                        if price_version_counts[price_version] == 1
                        else f"{price_version}:{model_alias}"
                    )
                    self._put_immutable(session, PricingVersionRow, storage_version, price_snapshot)
        except ConcurrentUpdate:
            raise
        except SQLAlchemyError:
            raise RepositoryUnavailable("storage unavailable") from None

    def _store_immutable(self, row_type: type, version: str, snapshot: dict[str, Any]) -> None:
        try:
            with Session(self.engine) as session, session.begin():
                self._put_immutable(session, row_type, version, snapshot)
        except ConcurrentUpdate:
            raise
        except SQLAlchemyError:
            raise RepositoryUnavailable("storage unavailable") from None

    @staticmethod
    def _put_immutable(session: Session, row_type: type, version: str, snapshot: Any) -> None:
        payload = _json(snapshot)
        row = session.get(row_type, version)
        if row is None:
            session.add(row_type(version_id=version, snapshot_json=payload))
        elif row.snapshot_json != payload:
            raise ConcurrentUpdate("activated version snapshot is immutable")

    @staticmethod
    def _task_row(task: TaskResult, scope: str, key_digest: str | None, request_digest: str) -> TaskRow:
        return TaskRow(
            task_id=task.task_id,
            trace_id=task.trace_id,
            status=task.status.value,
            policy_version=task.policy_version,
            created_at=task.created_at,
            updated_at=task.updated_at,
            revision=task.revision,
            idempotency_scope=scope,
            key_digest=key_digest,
            request_digest=request_digest,
            payload_json=_json(task_payload(task)),
        )

    @staticmethod
    def _find_duplicate(session: Session, task_id: str, scope: str, key_digest: str | None) -> TaskRow | None:
        by_id = session.get(TaskRow, task_id)
        if by_id is not None:
            if by_id.idempotency_scope != scope:
                raise IdempotencyConflict("task_id is already claimed in another scope")
            return by_id
        if key_digest is None:
            return None
        return session.scalar(
            select(TaskRow).where(TaskRow.idempotency_scope == scope, TaskRow.key_digest == key_digest)
        )

    @staticmethod
    def _resolve_duplicate(row: TaskRow, request_digest: str) -> TaskResult:
        if row.request_digest != request_digest:
            raise IdempotencyConflict("idempotency key reused with a different request")
        return TaskResult.model_validate_json(row.payload_json)

    @staticmethod
    def _verify_task_progression(previous: TaskResult, current: TaskResult) -> None:
        stable = ("task_id", "trace_id", "policy_version", "created_at", "application_id")
        if any(getattr(previous, name) != getattr(current, name) for name in stable):
            raise ConcurrentUpdate("stable task evidence changed")
        terminal = {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.BLOCKED,
            TaskStatus.CANCELLED,
        }
        if previous.status in terminal:
            raise ConcurrentUpdate("terminal task evidence is immutable")
        if previous.execution_limits is not None and previous.execution_limits != current.execution_limits:
            raise ConcurrentUpdate("execution limits are immutable")
        if previous.classification is not None and previous.classification != current.classification:
            raise ConcurrentUpdate("classification evidence is immutable")
        if previous.initial_decision is not None and previous.initial_decision != current.initial_decision:
            raise ConcurrentUpdate("initial decision evidence is immutable")
        collections = (
            (previous.decisions, current.decisions, "routing decisions", "decision_id"),
            (previous.attempts, current.attempts, "attempts", "attempt_id"),
            (previous.tool_events, current.tool_events, "tool events", "tool_event_id"),
        )
        for old, new, label, identity in collections:
            old_ids = tuple(getattr(item, identity) for item in old)
            new_ids = tuple(getattr(item, identity) for item in new)
            if new_ids[: len(old_ids)] != old_ids:
                raise ConcurrentUpdate(f"prior {label} must be preserved")
        if current.known_cost_usd < previous.known_cost_usd:
            raise ConcurrentUpdate("incurred cost cannot decrease")
        if previous.total_cost_usd is None and current.total_cost_usd is not None:
            raise ConcurrentUpdate("unknown incurred cost cannot become complete without reconciliation")
        if previous.total_cost_usd is not None and current.total_cost_usd is not None and current.total_cost_usd < previous.total_cost_usd:
            raise ConcurrentUpdate("incurred total cost cannot decrease")
        old_actions = previous.recovery_actions
        if current.recovery_actions[: len(old_actions)] != old_actions:
            raise ConcurrentUpdate("prior recovery actions must be preserved")
        for name in type(previous.counters).model_fields:
            if getattr(current.counters, name) < getattr(previous.counters, name):
                raise ConcurrentUpdate("execution counters cannot decrease")

    def _persist_children(self, session: Session, task: TaskResult) -> None:
        decisions = list(task.decisions)
        if task.initial_decision is not None and all(
            item.decision_id != task.initial_decision.decision_id for item in decisions
        ):
            decisions.insert(0, task.initial_decision)
        for sequence, decision in enumerate(decisions):
            payload = _json(decision.model_dump(mode="json"))
            self._insert_immutable(
                session,
                RoutingDecisionRow,
                decision.decision_id,
                lambda: RoutingDecisionRow(
                    decision_id=decision.decision_id,
                    task_id=task.task_id,
                    sequence=sequence,
                    routing_result=decision.routing_result,
                    payload_json=payload,
                ),
                payload,
            )
        for attempt in task.attempts:
            payload = _json(attempt.model_dump(mode="json"))
            existing = session.get(AttemptRow, attempt.attempt_id)
            if existing is None:
                session.add(
                    AttemptRow(
                        attempt_id=attempt.attempt_id,
                        task_id=task.task_id,
                        sequence=attempt.sequence,
                        status=attempt.status.value,
                        payload_json=payload,
                    )
                )
            elif existing.payload_json != payload:
                previous = json.loads(existing.payload_json)
                current = attempt.model_dump(mode="json")
                if existing.status != AttemptStatus.STARTED.value or not self._valid_attempt_progression(
                    previous, current
                ):
                    raise ConcurrentUpdate("finalized attempt evidence is immutable")
                existing.status = attempt.status.value
                existing.payload_json = payload
            for index, evaluation in enumerate(attempt.validations):
                evaluation_json = _json(evaluation.model_dump(mode="json"))
                self._insert_immutable(
                    session,
                    EvaluationRow,
                    evaluation.evaluation_id,
                    lambda e=evaluation, i=index, p=evaluation_json: EvaluationRow(
                        evaluation_id=e.evaluation_id,
                        task_id=task.task_id,
                        attempt_id=attempt.attempt_id,
                        sequence=i,
                        status=e.status,
                        payload_json=p,
                    ),
                    evaluation_json,
                )
        for sequence, tool_event in enumerate(task.tool_events):
            payload = _json(tool_event.model_dump(mode="json"))
            existing = session.get(ToolEventRow, tool_event.tool_event_id)
            if existing is None:
                session.add(
                    ToolEventRow(
                        tool_event_id=tool_event.tool_event_id,
                        task_id=task.task_id,
                        sequence=sequence,
                        status=tool_event.status,
                        payload_json=payload,
                    )
                )
            elif existing.payload_json != payload:
                previous = json.loads(existing.payload_json)
                current = tool_event.model_dump(mode="json")
                if (
                    existing.status != "started"
                    or tool_event.status == "started"
                    or not self._valid_tool_progression(previous, current)
                ):
                    raise ConcurrentUpdate("finalized tool evidence is immutable")
                existing.status = tool_event.status
                existing.payload_json = payload

    @staticmethod
    def _valid_attempt_progression(previous: dict[str, Any], current: dict[str, Any]) -> bool:
        """Allow a started record to gain evidence without changing earlier facts."""

        evolving = {
            "status",
            "completed_at",
            "actual_cost_usd",
            "provider_outcome",
            "failure",
            "validations",
        }
        if {key: value for key, value in previous.items() if key not in evolving} != {
            key: value for key, value in current.items() if key not in evolving
        }:
            return False
        for key in ("completed_at", "actual_cost_usd", "provider_outcome", "failure"):
            if previous.get(key) is not None and previous.get(key) != current.get(key):
                return False
        old_validations = previous.get("validations", [])
        new_validations = current.get("validations", [])
        if new_validations[: len(old_validations)] != old_validations:
            return False
        return True

    @staticmethod
    def _valid_tool_progression(previous: dict[str, Any], current: dict[str, Any]) -> bool:
        evolving = {"status", "failure", "cost_usd", "latency_ms"}
        if {key: value for key, value in previous.items() if key not in evolving} != {
            key: value for key, value in current.items() if key not in evolving
        }:
            return False
        for key in ("failure", "cost_usd"):
            if previous.get(key) is not None and previous.get(key) != current.get(key):
                return False
        return True

    @staticmethod
    def _insert_immutable(
        session: Session,
        row_type: type,
        identity: str,
        factory: Callable[[], Any],
        payload: str,
    ) -> None:
        existing = session.get(row_type, identity)
        if existing is None:
            session.add(factory())
        elif existing.payload_json != payload:
            raise ConcurrentUpdate("immutable evidence conflicts")

    @staticmethod
    def _insert_event(session: Session, event: ExecutionEvent) -> None:
        payload = _json(event_payload(event))
        existing = session.get(OutboxRow, event.event_id)
        if existing is None:
            session.add(
                OutboxRow(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    kind=event.kind,
                    occurred_at=event.occurred_at,
                    payload_json=payload,
                )
            )
        elif existing.payload_json != payload:
            raise ConcurrentUpdate("event_id already contains different evidence")

    def _ensure_events(self, events: tuple[ExecutionEvent, ...]) -> None:
        try:
            with Session(self.engine) as session, session.begin():
                for event in events:
                    self._insert_event(session, event)
        except ConcurrentUpdate:
            raise
        except SQLAlchemyError:
            raise RepositoryUnavailable("storage unavailable") from None

    def _replace_journal(self, retained: list[str]) -> None:
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.journal_path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                if retained:
                    stream.write("\n".join(retained) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.journal_path)
            self._fsync_directory(self.journal_path.parent)
        except OSError:
            raise RepositoryUnavailable("recovery journal unavailable") from None

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
