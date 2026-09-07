from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from model_router.core.execution_contracts import ExecutionEvent, TaskResult, TaskStatus
from model_router.storage import (
    SQLBudgetAuthority,
    SQLTaskRepository,
    downgrade_database,
    upgrade_database,
)


pytestmark = pytest.mark.postgresql
POSTGRES_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def postgres_url() -> str:
    if not POSTGRES_URL:
        pytest.skip("set POSTGRES_TEST_DATABASE_URL for explicit PostgreSQL integration")
    try:
        downgrade_database(POSTGRES_URL, "base")
        upgrade_database(POSTGRES_URL)
    except Exception as error:
        pytest.fail(f"explicit PostgreSQL backend is unavailable: {type(error).__name__}")
    return POSTGRES_URL


def _repository(url: str, journal: Path) -> SQLTaskRepository:
    return SQLTaskRepository(
        url,
        journal_path=journal,
        connection_timeout_ms=2_000,
        pool_size=2,
    )


def _task(task_id: str) -> TaskResult:
    now = datetime.now(UTC)
    return TaskResult(
        task_id=task_id,
        trace_id=f"trace-{task_id}",
        application_id="app-a",
        status=TaskStatus.CREATED,
        policy_version="policy-v1",
        created_at=now,
        updated_at=now,
    )


def _event(task_id: str, event_id: str) -> ExecutionEvent:
    return ExecutionEvent(
        event_id=event_id,
        task_id=task_id,
        trace_id=f"trace-{task_id}",
        kind="TASK_CREATED",
        occurred_at=datetime.now(UTC),
        policy_version="policy-v1",
    )


def test_postgres_migration_restart_idempotency_and_outbox_ownership(
    postgres_url: str, tmp_path: Path
):
    def claim(index: int):
        repository = _repository(postgres_url, tmp_path / f"journal-{index}.jsonl")
        task = _task(f"task-{index}")
        return repository.create(
            task,
            _event(task.task_id, f"event-{index}"),
            scope="app-a",
            key_digest="one-key",
            request_digest="one-request",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, range(4)))
    assert sum(result is None for result in results) == 1
    task_ids = {result.task_id for result in results if result is not None}
    assert len(task_ids) == 1

    restarted = _repository(postgres_url, tmp_path / "restart.jsonl")
    winner_id = next(iter(task_ids))
    assert restarted.get(winner_id, scope="app-a") is not None
    first = restarted.claim_outbox("worker-a", limit=10)
    assert len(first) == 1
    assert restarted.claim_outbox("worker-b", limit=10) == ()
    assert not restarted.ack_outbox(first[0].event_id, owner_id="worker-b")
    assert restarted.ack_outbox(first[0].event_id, owner_id="worker-a")
    assert restarted.current_migration_revision() == "0003_phase6_durable_storage"


def test_postgres_concurrent_budget_admission(postgres_url: str, tmp_path: Path):
    def reserve(index: int) -> bool:
        repository = _repository(postgres_url, tmp_path / f"budget-{index}.jsonl")
        budget = SQLBudgetAuthority(repository, "app-a", "pg-allocation", "1", "1")
        return budget.reserve(f"budget-task-{index}", f"action-{index}", ".6")

    with ThreadPoolExecutor(max_workers=4) as pool:
        admitted = list(pool.map(reserve, range(4)))
    assert admitted.count(True) == 1
    repository = _repository(postgres_url, tmp_path / "budget-restart.jsonl")
    restarted = SQLBudgetAuthority(repository, "app-a", "pg-allocation", "1", "1")
    assert restarted.remaining("new-task") == Decimal(".4")



def test_postgres_cross_process_duplicate_execute_dispatches_once(postgres_url,tmp_path):
    import multiprocessing
    from tests.test_phase6_recovery import _duplicate_execute_worker
    with multiprocessing.get_context('spawn').Pool(4) as workers:
        statuses=workers.map(_duplicate_execute_worker,[(postgres_url,str(tmp_path),i) for i in range(4)])
    assert 'succeeded' in statuses
    assert (tmp_path/'dispatches').read_text().splitlines()==['dispatched']
