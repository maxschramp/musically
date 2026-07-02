"""add_rule_engine_metrics_to_sync_history

Revision ID: d8e3f4a5b6c7
Revises: c21ada10b97c
Create Date: 2026-07-01 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e3f4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'c21ada10b97c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('sync_history', sa.Column('albums_queued_auto', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('sync_history', sa.Column('albums_queued_manual', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('sync_history', sa.Column('artists_subscribed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('sync_history', sa.Column('rules_fired', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('sync_history', 'rules_fired')
    op.drop_column('sync_history', 'artists_subscribed')
    op.drop_column('sync_history', 'albums_queued_manual')
    op.drop_column('sync_history', 'albums_queued_auto')
