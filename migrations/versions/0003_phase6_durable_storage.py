"""Durable application budgets, causal outbox ordering, and delivery leases."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_phase6_durable_storage"
down_revision = "0002_phase4_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("outbox") as batch:
        batch.add_column(sa.Column("sequence", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("claim_owner", sa.String(), nullable=True))
        batch.add_column(sa.Column("claim_expires_at", sa.DateTime(), nullable=True))

    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(
            """
            UPDATE outbox AS target
            SET sequence = (
              SELECT numbered.sequence
              FROM (
                SELECT event_id,
                       ROW_NUMBER() OVER (PARTITION BY task_id ORDER BY rowid) AS sequence
                FROM outbox
              ) AS numbered
              WHERE numbered.event_id = target.event_id
            )
            """
        )
    else:
        connection.execute(
            sa.text(
                """
                WITH numbered AS (
                  SELECT event_id,
                         ROW_NUMBER() OVER (
                           PARTITION BY task_id ORDER BY occurred_at, event_id
                         ) AS sequence
                  FROM outbox
                )
                UPDATE outbox
                SET sequence = numbered.sequence
                FROM numbered
                WHERE outbox.event_id = numbered.event_id
                """
            )
        )

    with op.batch_alter_table("outbox") as batch:
        batch.alter_column("sequence", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint("uq_outbox_task_sequence", ["task_id", "sequence"])
        batch.create_index(
            "ix_outbox_claimable",
            ["acknowledged_at", "claim_expires_at", "occurred_at"],
            unique=False,
        )

    op.create_table(
        "budget_allocations",
        sa.Column("application_id", sa.String(), nullable=False),
        sa.Column("allocation_id", sa.String(), nullable=False),
        sa.Column("application_ceiling", sa.String(), nullable=False),
        sa.Column("task_ceiling", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("application_id", "allocation_id"),
    )
    op.create_table(
        "budget_tasks",
        sa.Column("application_id", sa.String(), nullable=False),
        sa.Column("allocation_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("task_ceiling", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id", "allocation_id"],
            ["budget_allocations.application_id", "budget_allocations.allocation_id"],
        ),
        sa.PrimaryKeyConstraint("application_id", "allocation_id", "task_id"),
    )
    op.create_table(
        "budget_reservations",
        sa.Column("application_id", sa.String(), nullable=False),
        sa.Column("allocation_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("action_id", sa.String(), nullable=False),
        sa.Column("reserved", sa.String(), nullable=False),
        sa.Column("actual", sa.String(), nullable=True),
        sa.Column("settled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["application_id", "allocation_id", "task_id"],
            ["budget_tasks.application_id", "budget_tasks.allocation_id", "budget_tasks.task_id"],
        ),
        sa.PrimaryKeyConstraint("application_id", "allocation_id", "task_id", "action_id"),
    )
    op.create_index(
        "ix_budget_reservations_allocation",
        "budget_reservations",
        ["application_id", "allocation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_budget_reservations_allocation", table_name="budget_reservations")
    op.drop_table("budget_reservations")
    op.drop_table("budget_tasks")
    op.drop_table("budget_allocations")
    with op.batch_alter_table("outbox") as batch:
        batch.drop_index("ix_outbox_claimable")
        batch.drop_constraint("uq_outbox_task_sequence", type_="unique")
        batch.drop_column("claim_expires_at")
        batch.drop_column("claim_owner")
        batch.drop_column("sequence")
