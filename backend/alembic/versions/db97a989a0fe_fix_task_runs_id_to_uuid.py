"""fix_task_runs_id_to_uuid

Revision ID: db97a989a0fe
Revises: 0eb0dd61ea1e
Create Date: 2026-07-04 23:49:27.669411

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db97a989a0fe'
down_revision: Union[str, Sequence[str], None] = '0eb0dd61ea1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Alter task_runs.id from CHAR(36) to UUID to match SQLAlchemy model."""
    op.alter_column(
        'task_runs', 'id',
        type_=sa.UUID(),
        postgresql_using='id::UUID',
    )


def downgrade() -> None:
    """Revert task_runs.id from UUID back to CHAR(36)."""
    op.alter_column(
        'task_runs', 'id',
        type_=sa.CHAR(36),
    )
