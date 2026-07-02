"""add task_runs table

Revision ID: 0eb0dd61ea1e
Revises: daf0c0e40825
Create Date: 2026-07-02 10:17:22.619161

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0eb0dd61ea1e'
down_revision: Union[str, Sequence[str], None] = 'daf0c0e40825'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create task_runs table if it does not exist."""
    op.create_table(
        'task_runs',
        sa.Column('id', sa.CHAR(36), nullable=False),
        sa.Column('task_name', sa.String(100), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.String(500), nullable=True),
        sa.Column('result_summary', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        if_not_exists=True,
    )
    op.create_index(op.f('ix_task_runs_task_name'), 'task_runs', ['task_name'], unique=False, if_not_exists=True)


def downgrade() -> None:
    """Drop task_runs table."""
    op.drop_index(op.f('ix_task_runs_task_name'), table_name='task_runs', if_exists=True)
    op.drop_table('task_runs', if_exists=True)
