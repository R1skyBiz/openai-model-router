from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from model_router.core.execution_contracts import (
    Attempt,
    AttemptStatus,
    ConcurrentUpdate,
    ExecutionEvent,
    IdempotencyConflict,
    RecoveryAction,
    RepositoryUnavailable,
    TaskResult,
    TaskStatus,
    ToolOutcome,
)
from model_router.core.provider_contracts import ProviderResult, ProviderUsage
from model_router.policy.loader import load_bundle
from model_router.storage import SQLiteTaskRepository, upgrade_database
from model_router.storage.models import (
    ModelCatalogVersionRow,
    PolicyVersionRow,
    PricingVersionRow,
    TaskRow,
    ToolEventRow,
)
from model_router.telemetry.events import task_payload


NOW = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)


def task(*, task_id: str = "task-1", trace_id: str = "trace-1") -> TaskResult:
    return TaskResult(
        task_id=task_id,
        trace_id=trace_id,
        status=TaskStatus.CREATED,
        policy_version="policy-v1",
        created_at=NOW,
        updated_at=NOW,
        output="raw task output must stay in memory",
    )


def event(kind: str, *, event_id: str, task_id: str = "task-1", trace_id: str = "trace-1"):
    return ExecutionEvent(
        event_id=event_id,
        task_id=task_id,
        trace_id=trace_id,
        kind=kind,
        occurred_at=NOW,
        policy_version="policy-v1",
    )


@pytest.fixture
def repository(tmp_path: Path) -> SQLiteTaskRepository:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'router.sqlite'}"
    upgrade_database(database_url)
    return SQLiteTaskRepository(database_url, journal_path=tmp_path / "pending.jsonl")


def test_constructor_does_not_silently_create_schema(tmp_path: Path):
    repository = SQLiteTaskRepository(
        f"sqlite+pysqlite:///{tmp_path / 'empty.sqlite'}",
        journal_path=tmp_path / "pending.jsonl",
    )

    with pytest.raises(RepositoryUnavailable, match="storage unavailable"):
        repository.get("absent")


def test_migration_creates_required_tables_and_survives_restart(tmp_path: Path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'router.sqlite'}"
    upgrade_database(database_url)
    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert {
        "tasks",
        "routing_decisions",
        "attempts",
        "tool_events",
        "evaluations",
        "policy_versions",
        "model_catalog_versions",
        "pricing_versions",
        "outbox",
    } <= tables

    first = SQLiteTaskRepository(database_url, journal_path=tmp_path / "pending.jsonl")
    created = task()
    assert first.create(
        created,
        event("TASK_CREATED", event_id="event-1"),
        scope="application-a",
        key_digest="hashed-key",
        request_digest="request-a",
    ) is None
    first.engine.dispose()

    restarted = SQLiteTaskRepository(database_url, journal_path=tmp_path / "pending.jsonl")
    assert restarted.get(created.task_id) == created.model_copy(update={"output": None})


def test_create_atomically_claims_scoped_key(repository: SQLiteTaskRepository):
    created = task()
    created_event = event("TASK_CREATED", event_id="event-1")
    assert repository.create(
        created,
        created_event,
        scope="application-a",
        key_digest="hashed-key",
        request_digest="request-a",
    ) is None

    duplicate = repository.create(
        task(task_id="task-2", trace_id="trace-2"),
        event("TASK_CREATED", event_id="event-2", task_id="task-2", trace_id="trace-2"),
        scope="application-a",
        key_digest="hashed-key",
        request_digest="request-a",
    )
    assert duplicate is not None
    assert duplicate.task_id == "task-1"

    with pytest.raises(IdempotencyConflict):
        repository.create(
            task(task_id="task-3", trace_id="trace-3"),
            event("TASK_CREATED", event_id="event-3", task_id="task-3", trace_id="trace-3"),
            scope="application-a",
            key_digest="hashed-key",
            request_digest="different-request",
        )


def test_task_id_cannot_cross_scope_even_without_an_idempotency_key(
    repository: SQLiteTaskRepository,
):
    created = task()
    repository.create(
        created,
        event("TASK_CREATED", event_id="event-1"),
        scope="application-a",
        key_digest=None,
        request_digest="request-a",
    )

    with pytest.raises(IdempotencyConflict, match="another scope"):
        repository.create(
            created,
            event("TASK_CREATED", event_id="event-2"),
            scope="application-b",
            key_digest=None,
            request_digest="request-a",
        )


def test_save_is_optimistic_atomic_and_outbox_ack_is_idempotent(repository: SQLiteTaskRepository):
    created = task()
    created_event = event("TASK_CREATED", event_id="event-1")
    repository.create(
        created,
        created_event,
        scope="application-a",
        key_digest=None,
        request_digest="request-a",
    )
    running = created.model_copy(
        update={
            "status": TaskStatus.RUNNING,
            "updated_at": NOW + timedelta(seconds=1),
            "revision": 1,
        }
    )
    started_event = event("ATTEMPT_STARTED", event_id="event-2")
    repository.save(running, (started_event,), expected_revision=0)

    assert task_payload(repository.get(created.task_id)) == task_payload(running)
    assert [item.event_id for item in repository.pending_outbox()] == ["event-1", "event-2"]
    repository.ack_outbox("event-1")
    repository.ack_outbox("event-1")
    assert [item.event_id for item in repository.pending_outbox()] == ["event-2"]

    progressed = running.model_copy(
        update={"updated_at": NOW + timedelta(seconds=2), "revision": 2}
    )
    repository.save(progressed, (started_event,), expected_revision=1)
    assert [item.event_id for item in repository.pending_outbox()] == ["event-2"]

    conflicting_event = started_event.model_copy(update={"kind": "TASK_FAILED"})
    failed = progressed.model_copy(
        update={
            "status": TaskStatus.FAILED,
            "updated_at": NOW + timedelta(seconds=3),
            "revision": 3,
        }
    )
    with pytest.raises(ConcurrentUpdate):
        repository.save(failed, (conflicting_event,), expected_revision=2)
    assert task_payload(repository.get(created.task_id)) == task_payload(progressed)


def test_started_attempt_can_gain_evidence_then_becomes_immutable(repository: SQLiteTaskRepository):
    created = task()
    repository.create(
        created,
        event("TASK_CREATED", event_id="event-1"),
        scope="application-a",
        key_digest=None,
        request_digest="request-a",
    )
    started = Attempt(
        attempt_id="attempt-1",
        task_id=created.task_id,
        trace_id=created.trace_id,
        sequence=1,
        status=AttemptStatus.STARTED,
        started_at=NOW,
        estimated_cost_usd="0.10",
        pricing_version="pricing-v1",
    )
    revision_1 = created.model_copy(
        update={"status": TaskStatus.RUNNING, "revision": 1, "attempts": (started,)}
    )
    repository.save(
        revision_1,
        (event("ATTEMPT_STARTED", event_id="event-2"),),
        expected_revision=0,
    )

    provider_result = ProviderResult(
        task_id=created.task_id,
        trace_id=created.trace_id,
        invocation_id="invocation-1",
        policy_version="policy-v1",
        catalog_version="catalog-v1",
        model_alias="small-model",
        provider_model_id="provider-small",
        reasoning_effort="low",
        purpose="generation",
        latency_ms=12.5,
        usage=ProviderUsage(input_tokens=3, output_tokens=2, total_tokens=5),
        text="raw provider output must stay in memory",
    )
    evidenced = started.model_copy(
        update={"provider_outcome": provider_result, "actual_cost_usd": Decimal("0.08")}
    )
    revision_2 = revision_1.model_copy(update={"revision": 2, "attempts": (evidenced,)})
    repository.save(revision_2, (), expected_revision=1)

    completed = evidenced.model_copy(
        update={"status": AttemptStatus.SUCCEEDED, "completed_at": NOW + timedelta(seconds=1)}
    )
    revision_3 = revision_2.model_copy(
        update={"status": TaskStatus.SUCCEEDED, "revision": 3, "attempts": (completed,)}
    )
    repository.save(
        revision_3,
        (event("ATTEMPT_COMPLETED", event_id="event-3"),),
        expected_revision=2,
    )

    changed = completed.model_copy(update={"actual_cost_usd": Decimal("0.09")})
    revision_4 = revision_3.model_copy(update={"revision": 4, "attempts": (changed,)})
    with pytest.raises(ConcurrentUpdate, match="immutable"):
        repository.save(revision_4, (), expected_revision=3)
    assert repository.get(created.task_id).revision == 3


def test_save_preserves_prior_aggregate_evidence_and_stable_task_fields(
    repository: SQLiteTaskRepository,
):
    created = task()
    repository.create(
        created,
        event("TASK_CREATED", event_id="event-1"),
        scope="application-a",
        key_digest=None,
        request_digest="request-a",
    )
    started = Attempt(
        attempt_id="attempt-1",
        task_id=created.task_id,
        trace_id=created.trace_id,
        sequence=1,
        status=AttemptStatus.STARTED,
        started_at=NOW,
        pricing_version="pricing-v1",
    )
    action = RecoveryAction(action="stop", reason="recorded-action")
    running = created.model_copy(
        update={
            "status": TaskStatus.RUNNING,
            "revision": 1,
            "attempts": (started,),
            "recovery_actions": (action,),
        }
    )
    repository.save(running, (), expected_revision=0)

    dropped = running.model_copy(update={"revision": 2, "attempts": (), "recovery_actions": ()})
    with pytest.raises(ConcurrentUpdate, match="attempts"):
        repository.save(dropped, (), expected_revision=1)
    changed_trace = running.model_copy(update={"revision": 2, "trace_id": "trace-changed"})
    with pytest.raises(ConcurrentUpdate, match="stable"):
        repository.save(changed_trace, (), expected_revision=1)

    terminal = running.model_copy(update={"revision": 2, "status": TaskStatus.SUCCEEDED})
    repository.save(terminal, (), expected_revision=1)
    with pytest.raises(ConcurrentUpdate, match="terminal"):
        repository.save(terminal.model_copy(update={"revision": 3}), (), expected_revision=2)


def test_hidden_content_is_absent_from_database_and_journal(repository: SQLiteTaskRepository):
    created = task()
    repository.create(
        created,
        event("TASK_CREATED", event_id="event-1"),
        scope="application-a",
        key_digest=None,
        request_digest="request-a",
    )
    tool = ToolOutcome(
        tool_event_id="tool-1",
        tool="lookup",
        operation="read",
        status="succeeded",
        output={"secret": "raw tool output must stay in memory"},
    )
    updated = created.model_copy(update={"revision": 1, "tool_events": (tool,)})
    repository.save(updated, (), expected_revision=0)
    repository.retain_pending(updated, ())

    with Session(repository.engine) as session:
        persisted = " ".join(
            value
            for value in (
                session.scalar(select(TaskRow.payload_json)),
                session.scalar(select(ToolEventRow.payload_json)),
            )
            if value
        )
    journal = repository.journal_path.read_text(encoding="utf-8")
    assert "raw task output" not in persisted + journal
    assert "raw tool output" not in persisted + journal
    assert repository.get(created.task_id).output is None
    assert repository.get(created.task_id).tool_events[0].output is None


def test_journal_reconciliation_is_durable_and_idempotent(repository: SQLiteTaskRepository):
    created = task()
    repository.create(
        created,
        event("TASK_CREATED", event_id="event-1"),
        scope="application-a",
        key_digest=None,
        request_digest="request-a",
    )
    completed = created.model_copy(
        update={"status": TaskStatus.SUCCEEDED, "revision": 1, "updated_at": NOW + timedelta(seconds=1)}
    )
    completed_event = event("TASK_SUCCEEDED", event_id="event-2")
    repository.retain_pending(completed, (completed_event,))

    restarted = SQLiteTaskRepository(
        str(repository.engine.url), journal_path=repository.journal_path
    )
    assert restarted.reconcile_pending() == 1
    assert task_payload(restarted.get(created.task_id)) == task_payload(completed)
    assert [item.event_id for item in restarted.pending_outbox()] == ["event-1", "event-2"]
    assert restarted.reconcile_pending() == 0
    assert restarted.journal_path.read_text(encoding="utf-8") == ""


def test_immutable_snapshots_are_idempotent(repository: SQLiteTaskRepository):
    repository.store_policy_version("policy-v1", {"hash": "abc"})
    repository.store_policy_version("policy-v1", {"hash": "abc"})
    with pytest.raises(ConcurrentUpdate, match="immutable"):
        repository.store_policy_version("policy-v1", {"hash": "changed"})


def test_pin_versions_retains_actual_policy_catalog_and_model_prices_atomically(
    repository: SQLiteTaskRepository,
):
    bundle = load_bundle("config")
    policy_snapshot = {
        "policy": bundle.policy,
        "budgets": bundle.budgets,
        "validation": bundle.validation,
        "content_hash": bundle.content_hash,
    }
    repository.pin_versions(
        policy_version=bundle.policy["version"],
        policy_snapshot=policy_snapshot,
        catalog_version=bundle.catalog["catalog_version"],
        catalog_snapshot=bundle.catalog,
    )
    repository.pin_versions(
        policy_version=bundle.policy["version"],
        policy_snapshot=policy_snapshot,
        catalog_version=bundle.catalog["catalog_version"],
        catalog_snapshot=bundle.catalog,
    )

    with Session(repository.engine) as session:
        policy = session.get(PolicyVersionRow, bundle.policy["version"])
        catalog = session.get(ModelCatalogVersionRow, bundle.catalog["catalog_version"])
        prices = session.scalars(select(PricingVersionRow)).all()
    assert json.loads(policy.snapshot_json)["policy"]["objective"] == bundle.policy["objective"]
    assert json.loads(catalog.snapshot_json)["models"]["luna"]["tier"] == "L0"
    assert len(prices) == len(bundle.catalog["models"])
    assert {json.loads(row.snapshot_json)["model_alias"] for row in prices} == set(
        bundle.catalog["models"]
    )

    changed_policy = dict(policy_snapshot)
    changed_policy["content_hash"] = "changed-under-same-version"
    with pytest.raises(ConcurrentUpdate, match="immutable"):
        repository.pin_versions(
            policy_version=bundle.policy["version"],
            policy_snapshot=changed_policy,
            catalog_version=bundle.catalog["catalog_version"],
            catalog_snapshot=bundle.catalog,
        )


def test_primary_and_journal_failures_raise_only_sanitized_errors(tmp_path: Path):
    unavailable = SQLiteTaskRepository(
        f"sqlite+pysqlite:///{tmp_path}",
        journal_path=tmp_path / "recoverable.jsonl",
    )
    with pytest.raises(RepositoryUnavailable) as primary:
        unavailable.get("task-1")
    assert str(primary.value) == "storage unavailable"

    pending_task = task().model_copy(update={"revision": 1})
    unavailable.retain_pending(pending_task, ())
    assert unavailable.journal_path.is_file()

    journal_unavailable = SQLiteTaskRepository(
        "sqlite+pysqlite:///:memory:",
        journal_path=tmp_path,
    )
    with pytest.raises(RepositoryUnavailable) as journal:
        journal_unavailable.retain_pending(pending_task, ())
    assert str(journal.value) == "recovery journal unavailable"


def test_journal_lock_prevents_reconcile_from_losing_concurrent_append(
    repository: SQLiteTaskRepository,
):
    first = task(task_id="pending-1", trace_id="pending-trace-1").model_copy(update={"revision": 1})
    second = task(task_id="pending-2", trace_id="pending-trace-2").model_copy(update={"revision": 1})
    repository.retain_pending(first, ())
    peer = SQLiteTaskRepository(str(repository.engine.url), journal_path=repository.journal_path)

    entered_replace = Event()
    allow_replace = Event()
    append_started = Event()
    original_replace = repository._replace_journal

    def delayed_replace(retained: list[str]) -> None:
        entered_replace.set()
        assert allow_replace.wait(timeout=2)
        original_replace(retained)

    def append_second() -> None:
        append_started.set()
        peer.retain_pending(second, ())

    repository._replace_journal = delayed_replace
    with ThreadPoolExecutor(max_workers=2) as pool:
        replay = pool.submit(repository.reconcile_pending)
        assert entered_replace.wait(timeout=2)
        append = pool.submit(append_second)
        assert append_started.wait(timeout=2)
        assert not append.done()
        allow_replace.set()
        assert replay.result(timeout=2) == 0
        append.result(timeout=2)

    records = [json.loads(line) for line in repository.journal_path.read_text().splitlines()]
    assert [record["task"]["task_id"] for record in records] == ["pending-1", "pending-2"]


def test_tool_completion_cannot_change_replay_admission_evidence(repository):
    created=task()
    repository.create(created,event('TASK_CREATED',event_id='created'),scope='a',key_digest=None,request_digest='digest')
    started=ToolOutcome(tool_event_id='tool',tool='writer',operation='write',status='started',side_effecting=True,replay_safe=False)
    running=created.model_copy(update={'revision':1,'status':TaskStatus.RUNNING,'tool_events':(started,)})
    repository.save(running,(),expected_revision=0)
    completed=started.model_copy(update={'status':'succeeded','replay_safe':True,'cost_usd':Decimal('0')})
    with pytest.raises(ConcurrentUpdate):
        repository.save(running.model_copy(update={'revision':2,'tool_events':(completed,)}),(),expected_revision=1)
    assert repository.get(created.task_id).tool_events[0].replay_safe is False


@pytest.mark.parametrize('changes',[{'known_cost_usd':Decimal('0')},{'total_cost_usd':Decimal('0')}])
def test_aggregate_cannot_erase_incurred_cost(repository,changes):
    created=task().model_copy(update={'known_cost_usd':Decimal('1'),'total_cost_usd':Decimal('1')})
    repository.create(created,event('TASK_CREATED',event_id='created'),scope='a',key_digest=None,request_digest='digest')
    with pytest.raises(ConcurrentUpdate):
        repository.save(created.model_copy(update={'revision':1,**changes}),(),expected_revision=0)


def test_unknown_cost_cannot_be_rewritten_as_complete(repository):
    created=task().model_copy(update={'total_cost_usd':None})
    repository.create(created,event('TASK_CREATED',event_id='created'),scope='a',key_digest=None,request_digest='digest')
    with pytest.raises(ConcurrentUpdate):
        repository.save(created.model_copy(update={'revision':1,'total_cost_usd':Decimal('0')}),(),expected_revision=0)
