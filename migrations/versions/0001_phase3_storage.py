"""Create Phase 3 execution evidence and outbox tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_phase3_storage"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_scope", sa.String(), nullable=False),
        sa.Column("key_digest", sa.String(), nullable=True),
        sa.Column("request_digest", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("task_id"),
        sa.UniqueConstraint("idempotency_scope", "key_digest", name="uq_tasks_scope_key"),
    )
    op.create_index("ix_tasks_trace_id", "tasks", ["trace_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_table(
        "routing_decisions",
        sa.Column("decision_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("routing_result", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"]),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint("task_id", "sequence", name="uq_decision_task_sequence"),
    )
    op.create_index("ix_routing_decisions_task_id", "routing_decisions", ["task_id"])
    op.create_table(
        "attempts",
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"]),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint("task_id", "sequence", name="uq_attempt_task_sequence"),
    )
    op.create_index("ix_attempts_task_id", "attempts", ["task_id"])
    op.create_table(
        "tool_events",
        sa.Column("tool_event_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"]),
        sa.PrimaryKeyConstraint("tool_event_id"),
    )
    op.create_index("ix_tool_events_task_id", "tool_events", ["task_id"])
    op.create_table(
        "evaluations",
        sa.Column("evaluation_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.attempt_id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"]),
        sa.PrimaryKeyConstraint("evaluation_id"),
    )
    op.create_index("ix_evaluations_attempt_id", "evaluations", ["attempt_id"])
    op.create_index("ix_evaluations_task_id", "evaluations", ["task_id"])
    for table_name in ("policy_versions", "model_catalog_versions", "pricing_versions"):
        op.create_table(
            table_name,
            sa.Column("version_id", sa.String(), nullable=False),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("version_id"),
        )
    op.create_table(
        "outbox",
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_outbox_task_id", "outbox", ["task_id"])
    op.create_index("ix_outbox_pending", "outbox", ["acknowledged_at", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_pending", table_name="outbox")
    op.drop_index("ix_outbox_task_id", table_name="outbox")
    op.drop_table("outbox")
    for table_name in ("pricing_versions", "model_catalog_versions", "policy_versions"):
        op.drop_table(table_name)
    op.drop_index("ix_evaluations_task_id", table_name="evaluations")
    op.drop_index("ix_evaluations_attempt_id", table_name="evaluations")
    op.drop_table("evaluations")
    op.drop_index("ix_tool_events_task_id", table_name="tool_events")
    op.drop_table("tool_events")
    op.drop_index("ix_attempts_task_id", table_name="attempts")
    op.drop_table("attempts")
    op.drop_index("ix_routing_decisions_task_id", table_name="routing_decisions")
    op.drop_table("routing_decisions")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_trace_id", table_name="tasks")
    op.drop_table("tasks")
