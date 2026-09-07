from __future__ import annotations

import multiprocessing
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from model_router.storage import SQLBudgetAuthority, SQLTaskRepository, upgrade_database


def _reserve(args: tuple[str, str, str]) -> bool:
    database_url, journal_path, task_id = args
    repository = SQLTaskRepository(database_url, journal_path=journal_path)
    budget = SQLBudgetAuthority(repository, "app-a", "allocation-v1", "1.00", "1.00")
    return budget.reserve(task_id, f"action-{task_id}", "0.60")


def test_budget_is_durable_idempotent_and_holds_unknown_outcomes(tmp_path: Path):
    url = f"sqlite+pysqlite:///{tmp_path / 'router.sqlite'}"
    upgrade_database(url)
    repository = SQLTaskRepository(url, journal_path=tmp_path / "pending.jsonl")
    budget = SQLBudgetAuthority(repository, "app-a", "allocation-v1", "1.00", "0.75")
    assert budget.remaining("task-1") == Decimal("0.75")
    assert budget.reserve("task-1", "action-1", "0.60")
    assert budget.reserve("task-1", "action-1", "0.60")
    assert budget.remaining("task-1") == Decimal("0.15")
    budget.settle("task-1", "action-1", None)
    assert budget.remaining("task-1") == Decimal("0.15")

    restarted = SQLBudgetAuthority(repository, "app-a", "allocation-v1", "1", ".75")
    assert restarted.remaining("task-1") == Decimal("0.15")
    restarted.settle("task-1", "action-1", "0.25")
    assert restarted.remaining("task-1") == Decimal("0.50")
    assert restarted.remaining("task-2") == Decimal("0.75")
    with pytest.raises(ValueError, match="immutable"):
        SQLBudgetAuthority(repository, "app-a", "allocation-v1", "2", ".75")
    with pytest.raises(ValueError):
        SQLBudgetAuthority(repository, "app-a", "float", 1.0, "0.5")


def test_concurrent_process_budget_admission_never_overspends(tmp_path: Path):
    url = f"sqlite+pysqlite:///{tmp_path / 'router.sqlite'}"
    journal = str(tmp_path / "pending.jsonl")
    upgrade_database(url)
    context = multiprocessing.get_context("spawn")
    with context.Pool(4) as pool:
        admitted = pool.map(_reserve, [(url, journal, f"task-{index}") for index in range(4)])
    assert admitted.count(True) == 1
    repository = SQLTaskRepository(url, journal_path=journal)
    budget = SQLBudgetAuthority(repository, "app-a", "allocation-v1", "1", "1")
    assert budget.remaining("another-task") == Decimal("0.40")


def test_budget_arithmetic_ignores_caller_decimal_precision(tmp_path: Path):
    url = f"sqlite+pysqlite:///{tmp_path / 'router.sqlite'}"
    upgrade_database(url)
    repository = SQLTaskRepository(url, journal_path=tmp_path / "pending.jsonl")
    budget = SQLBudgetAuthority(repository, "app-a", "precise", "1", "1")
    with localcontext() as context:
        context.prec = 2
        assert budget.reserve("task", "large", ".99")
        assert not budget.reserve("task", "over-cap", ".02")
        budget.settle("task", "large", ".001")
        assert budget.remaining("task") == Decimal(".999")
        assert budget.reserve("task", "exact", ".999")
        assert budget.remaining("task") == Decimal("0")
