"""SQLAlchemy models for Phase 3 local persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RoutingPreviewRow(Base):
    __tablename__ = "routing_previews"
    __table_args__ = (
        UniqueConstraint("application_id", "key_digest", name="uq_preview_scope_key"),
        UniqueConstraint("application_id", "task_id", name="uq_preview_scope_task"),
    )
    preview_id: Mapped[str] = mapped_column(String, primary_key=True)
    allocation_id: Mapped[str] = mapped_column(String, nullable=False)
    application_id: Mapped[str] = mapped_column(String, nullable=False)
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    key_digest: Mapped[str] = mapped_column(String, nullable=False)
    request_digest: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_scope", "key_digest", name="uq_tasks_scope_key"),
        Index("ix_tasks_trace_id", "trace_id"),
        Index("ix_tasks_status", "status"),
    )

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    policy_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_scope: Mapped[str] = mapped_column(String, nullable=False)
    key_digest: Mapped[str | None] = mapped_column(String, nullable=True)
    request_digest: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class RoutingDecisionRow(Base):
    __tablename__ = "routing_decisions"
    __table_args__ = (UniqueConstraint("task_id", "sequence", name="uq_decision_task_sequence"),)

    decision_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    routing_result: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class AttemptRow(Base):
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("task_id", "sequence", name="uq_attempt_task_sequence"),)

    attempt_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class ToolEventRow(Base):
    __tablename__ = "tool_events"

    tool_event_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class EvaluationRow(Base):
    __tablename__ = "evaluations"

    evaluation_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.attempt_id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class PolicyVersionRow(Base):
    __tablename__ = "policy_versions"

    version_id: Mapped[str] = mapped_column(String, primary_key=True)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class ModelCatalogVersionRow(Base):
    __tablename__ = "model_catalog_versions"

    version_id: Mapped[str] = mapped_column(String, primary_key=True)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class PricingVersionRow(Base):
    __tablename__ = "pricing_versions"

    version_id: Mapped[str] = mapped_column(String, primary_key=True)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class OutboxRow(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        Index("ix_outbox_pending", "acknowledged_at", "occurred_at"),
        Index("ix_outbox_claimable", "acknowledged_at", "claim_expires_at", "occurred_at"),
        UniqueConstraint("task_id", "sequence", name="uq_outbox_task_sequence"),
    )

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    claim_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)


class BudgetAllocationRow(Base):
    """An immutable, explicitly named application budget allocation."""

    __tablename__ = "budget_allocations"

    application_id: Mapped[str] = mapped_column(String, primary_key=True)
    allocation_id: Mapped[str] = mapped_column(String, primary_key=True)
    application_ceiling: Mapped[str] = mapped_column(String, nullable=False)
    task_ceiling: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class BudgetTaskRow(Base):
    """Pins a task to one application allocation without resetting its balance."""

    __tablename__ = "budget_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["application_id", "allocation_id"],
            ["budget_allocations.application_id", "budget_allocations.allocation_id"],
        ),
    )

    application_id: Mapped[str] = mapped_column(String, primary_key=True)
    allocation_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_ceiling: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class BudgetReservationRow(Base):
    """An immutable reservation whose unknown settlement continues to hold funds."""

    __tablename__ = "budget_reservations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["application_id", "allocation_id", "task_id"],
            ["budget_tasks.application_id", "budget_tasks.allocation_id", "budget_tasks.task_id"],
        ),
        Index("ix_budget_reservations_allocation", "application_id", "allocation_id"),
    )

    application_id: Mapped[str] = mapped_column(String, primary_key=True)
    allocation_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    action_id: Mapped[str] = mapped_column(String, primary_key=True)
    reserved: Mapped[str] = mapped_column(String, nullable=False)
    actual: Mapped[str | None] = mapped_column(String, nullable=True)
    settled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(nullable=True)


class VerificationEvidenceRow(Base):
    """Phase 4 attempt, health, pairing and domain evidence in task transaction."""
    __tablename__ = 'verification_evidence'
    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.task_id'), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
