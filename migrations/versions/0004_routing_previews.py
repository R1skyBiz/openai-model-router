"""Dedicated paid routing previews; no production task foreign keys."""
from alembic import op
import sqlalchemy as sa

revision = "0004_routing_previews"
down_revision = "0003_phase6_durable_storage"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("routing_previews",
        sa.Column("preview_id", sa.String(), primary_key=True),
        sa.Column("allocation_id", sa.String(), nullable=False),
        sa.Column("application_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("key_digest", sa.String(), nullable=False),
        sa.Column("request_digest", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("application_id", "key_digest", name="uq_preview_scope_key"),
        sa.UniqueConstraint("application_id", "task_id", name="uq_preview_scope_task"))


def downgrade():
    op.drop_table("routing_previews")
