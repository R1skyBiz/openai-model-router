"""Transactional application and task budget authority."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from model_router.core.contracts import Money
from model_router.core.execution_contracts import IdempotencyConflict, RepositoryUnavailable
from model_router.execution.arithmetic import money_difference, money_sum
from model_router.storage.models import (
    BudgetAllocationRow,
    BudgetReservationRow,
    BudgetTaskRow,
    TaskRow,
)
from model_router.storage.repository import SQLTaskRepository


ZERO = Decimal("0")


def _amount(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        return None
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < ZERO:
        return None
    return amount


def _money_text(amount: Decimal) -> str:
    normalized = format(amount, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


class SQLBudgetAuthority:
    """A durable allocation shared safely by threads, processes, and hosts.

    Allocation identifiers are explicit and immutable. Reconstructing this
    object with the same identifier resumes prior reservations; it never resets
    them. An unknown settlement is intentionally a no-op so its reservation
    continues to hold funds pending operator reconciliation.
    """

    def __init__(
        self,
        repository: SQLTaskRepository,
        application_id: str,
        allocation_id: str,
        application_ceiling: Money,
        task_ceiling: Money,
    ) -> None:
        if not isinstance(repository, SQLTaskRepository):
            raise TypeError("repository must be a SQLTaskRepository")
        application_amount = _amount(application_ceiling)
        task_amount = _amount(task_ceiling)
        if not application_id or not allocation_id:
            raise ValueError("application_id and allocation_id are required")
        if application_amount is None or task_amount is None:
            raise ValueError("budget ceilings must be finite nonnegative decimal values")
        if task_amount > application_amount:
            raise ValueError("task ceiling cannot exceed application ceiling")
        self.repository = repository
        self.application_id = application_id
        self.allocation_id = allocation_id
        self.application_ceiling = application_amount
        self.task_ceiling = task_amount
        self._ensure_allocation()

    def _ensure_allocation(self) -> None:
        identity = (self.application_id, self.allocation_id)
        application_text = _money_text(self.application_ceiling)
        task_text = _money_text(self.task_ceiling)
        try:
            with self.repository._write_session() as session:
                if session.bind is not None and session.bind.dialect.name == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert as postgresql_insert

                    session.execute(
                        postgresql_insert(BudgetAllocationRow)
                        .values(
                            application_id=self.application_id,
                            allocation_id=self.allocation_id,
                            application_ceiling=application_text,
                            task_ceiling=task_text,
                            created_at=datetime.now(UTC),
                        )
                        .on_conflict_do_nothing(
                            index_elements=["application_id", "allocation_id"]
                        )
                    )
                    row = session.get(BudgetAllocationRow, identity, populate_existing=True)
                else:
                    row = session.get(BudgetAllocationRow, identity)
                    if row is None:
                        row = BudgetAllocationRow(
                            application_id=self.application_id,
                            allocation_id=self.allocation_id,
                            application_ceiling=application_text,
                            task_ceiling=task_text,
                            created_at=datetime.now(UTC),
                        )
                        session.add(row)
                if row is None or (
                    row.application_ceiling != application_text or row.task_ceiling != task_text
                ):
                    raise ValueError("budget allocation is immutable")
        except ValueError:
            raise
        except SQLAlchemyError:
            raise RepositoryUnavailable("budget storage unavailable") from None

    def remaining(self, task_id: str) -> Decimal:
        if not task_id:
            return ZERO
        try:
            with self.repository._write_session() as session:
                allocation = self._locked_allocation(session)
                self._verify_task_owner(session, task_id)
                reservations = session.scalars(
                    select(BudgetReservationRow).where(
                        BudgetReservationRow.application_id == self.application_id,
                        BudgetReservationRow.allocation_id == self.allocation_id,
                    )
                ).all()
                app_debit = money_sum(self._debit(row) for row in reservations)
                task_debit = money_sum(
                    self._debit(row) for row in reservations if row.task_id == task_id
                )
                app_remaining = max(
                    ZERO, money_difference(Decimal(allocation.application_ceiling), app_debit)
                )
                task_remaining = max(
                    ZERO, money_difference(Decimal(allocation.task_ceiling), task_debit)
                )
                return min(app_remaining, task_remaining)
        except IdempotencyConflict:
            raise
        except SQLAlchemyError:
            raise RepositoryUnavailable("budget storage unavailable") from None

    def reserve(self, task_id: str, action_id: str, amount: Money) -> bool:
        normalized = _amount(amount)
        if not task_id or not action_id or normalized is None:
            return False
        identity = (self.application_id, self.allocation_id, task_id, action_id)
        try:
            with self.repository._write_session() as session:
                allocation = self._locked_allocation(session)
                self._verify_task_owner(session, task_id)
                existing = session.get(BudgetReservationRow, identity)
                if existing is not None:
                    return Decimal(existing.reserved) == normalized

                task_identity = (self.application_id, self.allocation_id, task_id)
                task = session.get(BudgetTaskRow, task_identity)
                if task is None:
                    task = BudgetTaskRow(
                        application_id=self.application_id,
                        allocation_id=self.allocation_id,
                        task_id=task_id,
                        task_ceiling=allocation.task_ceiling,
                        created_at=datetime.now(UTC),
                    )
                    session.add(task)
                    session.flush()
                elif task.task_ceiling != allocation.task_ceiling:
                    raise ValueError("task budget is immutable")

                reservations = session.scalars(
                    select(BudgetReservationRow).where(
                        BudgetReservationRow.application_id == self.application_id,
                        BudgetReservationRow.allocation_id == self.allocation_id,
                    )
                ).all()
                app_debit = money_sum(self._debit(row) for row in reservations)
                task_debit = money_sum(
                    self._debit(row) for row in reservations if row.task_id == task_id
                )
                if money_sum((app_debit, normalized)) > Decimal(allocation.application_ceiling):
                    return False
                if money_sum((task_debit, normalized)) > Decimal(task.task_ceiling):
                    return False
                session.add(
                    BudgetReservationRow(
                        application_id=self.application_id,
                        allocation_id=self.allocation_id,
                        task_id=task_id,
                        action_id=action_id,
                        reserved=_money_text(normalized),
                        settled=False,
                        created_at=datetime.now(UTC),
                    )
                )
                return True
        except (IdempotencyConflict, ValueError):
            raise
        except SQLAlchemyError:
            raise RepositoryUnavailable("budget storage unavailable") from None

    def settle(self, task_id: str, action_id: str, actual: Money | None) -> None:
        if actual is None:
            return
        normalized = _amount(actual)
        if normalized is None:
            raise ValueError("actual cost must be finite and nonnegative")
        identity = (self.application_id, self.allocation_id, task_id, action_id)
        try:
            with self.repository._write_session() as session:
                self._locked_allocation(session)
                self._verify_task_owner(session, task_id)
                row = session.get(BudgetReservationRow, identity)
                if row is None:
                    raise KeyError("cannot settle an action without a reservation")
                if row.settled:
                    if row.actual is None or Decimal(row.actual) != normalized:
                        raise ValueError("action is already settled with a different amount")
                    return
                row.actual = _money_text(normalized)
                row.settled = True
                row.settled_at = datetime.now(UTC)
        except (IdempotencyConflict, KeyError, ValueError):
            raise
        except SQLAlchemyError:
            raise RepositoryUnavailable("budget storage unavailable") from None

    def _locked_allocation(self, session: Any) -> BudgetAllocationRow:
        statement = select(BudgetAllocationRow).where(
            BudgetAllocationRow.application_id == self.application_id,
            BudgetAllocationRow.allocation_id == self.allocation_id,
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise RepositoryUnavailable("budget allocation unavailable")
        return row

    def _verify_task_owner(self, session: Any, task_id: str) -> None:
        task = session.get(TaskRow, task_id)
        if task is not None and task.idempotency_scope != self.application_id:
            raise IdempotencyConflict("task belongs to another application scope")

    @staticmethod
    def _debit(row: BudgetReservationRow) -> Decimal:
        if row.settled and row.actual is not None:
            return Decimal(row.actual)
        return Decimal(row.reserved)


__all__ = ["SQLBudgetAuthority"]
