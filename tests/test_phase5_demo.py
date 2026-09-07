"""Demo isolation and evidence reconciliation use the real persistence boundary."""
from datetime import UTC, datetime
from decimal import Decimal
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from model_router.core.execution_contracts import TaskResult
from model_router.storage.models import AttemptRow, OutboxRow, TaskRow, VerificationEvidenceRow
from model_router.telemetry.demo import generate_demo, open_demo


@pytest.fixture(scope='module')
def demo(tmp_path_factory):
    directory = tmp_path_factory.mktemp('phase5-synthetic')
    generate_demo(directory, now=datetime(2026, 9, 6, 20, tzinfo=UTC), count=70)
    return directory


def test_demo_reconciles_normalized_persisted_evidence(demo):
    repository = open_demo(demo)
    with Session(repository.engine) as session:
        tasks = [TaskResult.model_validate_json(row) for row in session.scalars(select(TaskRow.payload_json))]
        assert len(tasks) == 70
        assert session.scalar(select(func.count()).select_from(AttemptRow)) == sum(len(task.attempts) for task in tasks)
        assert session.scalar(select(func.count()).select_from(OutboxRow)) > len(tasks) * 4
        assert session.scalar(select(func.count()).select_from(VerificationEvidenceRow)) > len(tasks)
    assert {task.initial_decision.selected_model_alias for task in tasks} == {'luna', 'terra', 'sol', 'astra'}
    assert len({task.application_id for task in tasks}) == 3
    assert len({task.policy_version for task in tasks}) == 2
    assert any(task.counters.quality_escalations for task in tasks)
    assert any(task.counters.infrastructure_retries for task in tasks)
    assert any(task.counters.tool_recoveries for task in tasks)
    assert any(task.total_cost_usd is None for task in tasks)
    assert any(task.shadow_runs for task in tasks)
    for task in tasks:
        known = sum((attempt.actual_cost_usd or Decimal(0) for attempt in (*task.attempts, *task.evaluator_attempts)), Decimal(0))
        known += sum((tool.cost_usd or Decimal(0) for tool in task.tool_events), Decimal(0))
        assert known == task.known_cost_usd
        assert task.initial_decision.synthetic and task.task_id.startswith('synthetic-demo-')
        assert 'synthetic content never persisted' not in task.model_dump_json()
        if task.total_cost_usd is not None:
            assert known == task.total_cost_usd


def test_demo_never_overwrites_or_opens_unmarked_evidence(demo, tmp_path):
    original = (demo / 'synthetic-demo.sqlite3').read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        generate_demo(demo)
    assert (demo / 'synthetic-demo.sqlite3').read_bytes() == original
    with pytest.raises(FileNotFoundError):
        open_demo(tmp_path)
    (tmp_path / 'synthetic-demo.json').write_text(json.dumps({'dataset': 'production', 'synthetic': False}))
    with pytest.raises(ValueError, match='marker'):
        open_demo(tmp_path)


def test_demo_refuses_tampered_database(demo, tmp_path):
    (tmp_path / 'synthetic-demo.json').write_bytes((demo / 'synthetic-demo.json').read_bytes())
    (tmp_path / 'synthetic-demo.sqlite3').write_bytes((demo / 'synthetic-demo.sqlite3').read_bytes() + b'changed')
    with pytest.raises(ValueError, match='changed'):
        open_demo(tmp_path)
