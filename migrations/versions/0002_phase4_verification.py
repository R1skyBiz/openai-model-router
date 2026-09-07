"""Transactional evaluator, health, domain and shadow evidence."""
from alembic import op
import sqlalchemy as sa
revision = '0002_phase4_verification'
down_revision = '0001_phase3_storage'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('verification_evidence',
        sa.Column('evidence_id', sa.String(), nullable=False),
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.task_id']),
        sa.PrimaryKeyConstraint('evidence_id'))
    op.create_index('ix_verification_evidence_task_id', 'verification_evidence', ['task_id'])

def downgrade():
    op.drop_index('ix_verification_evidence_task_id', table_name='verification_evidence')
    op.drop_table('verification_evidence')
