"""add_album_unique_constraint

Revision ID: daf0c0e40825
Revises: d8e3f4a5b6c7
Create Date: 2026-07-02 10:16:38.780302

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'daf0c0e40825'
down_revision: Union[str, Sequence[str], None] = 'd8e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Status priority: keep the "best" row when deduplicating.
# Lower number = better status to keep.
_STATUS_KEEP_ORDER = {
    "downloaded": 0,
    "downloading": 1,
    "queued": 2,
    "stalled": 3,
    "rejected": 4,
}


def upgrade() -> None:
    """Deduplicate albums table, then add unique constraint on (artist_name, title)."""

    conn = op.get_bind()

    # Detect dialect for database-specific operations.
    dialect_name = conn.dialect.name  # "sqlite" or "postgresql"

    # ------------------------------------------------------------------
    # Step 1: Find duplicate (artist_name, title) groups and keep the
    # row with the "best" status.
    # ------------------------------------------------------------------
    rows = conn.execute(
        sa.text("SELECT id, artist_name, title, status FROM albums")
    ).fetchall()

    # Group by case-insensitive (artist_name, title)
    groups: dict[tuple[str, str], list[tuple[str, str, str, str]]] = {}
    for row in rows:
        key = (row[1].lower() if row[1] else "", row[2].lower() if row[2] else "")
        groups.setdefault(key, []).append((row[0], row[1], row[2], row[3] or "queued"))

    ids_to_delete: list[str] = []
    for entries in groups.values():
        if len(entries) <= 1:
            continue
        entries.sort(key=lambda x: _STATUS_KEEP_ORDER.get(x[3].lower(), 5))
        for dup in entries[1:]:
            ids_to_delete.append(dup[0])

    if ids_to_delete:
        batch_size = 500
        for i in range(0, len(ids_to_delete), batch_size):
            batch = ids_to_delete[i : i + batch_size]
            placeholders = ", ".join(f"'{id_}'" for id_ in batch)
            conn.execute(sa.text(f"DELETE FROM albums WHERE id IN ({placeholders})"))

    # ------------------------------------------------------------------
    # Step 2: Add the unique constraint (skip if already exists).
    # Uses database-appropriate method: direct DDL for PostgreSQL,
    # batch_alter_table for SQLite.
    # ------------------------------------------------------------------
    constraint_name = "uq_album_artist_title"

    # Check if constraint already exists
    constraint_exists = False
    if dialect_name == "sqlite":
        try:
            indexes = conn.execute(sa.text("PRAGMA index_list('albums')")).fetchall()
            index_names = {row[1] for row in indexes}
            if constraint_name in index_names:
                constraint_exists = True
        except Exception:
            pass
    else:
        # PostgreSQL / other databases: check information_schema
        try:
            result = conn.execute(
                sa.text(
                    "SELECT 1 FROM information_schema.table_constraints "
                    "WHERE constraint_name = :name AND table_name = 'albums'"
                ),
                {"name": constraint_name},
            ).fetchone()
            if result is not None:
                constraint_exists = True
        except Exception:
            pass

    if not constraint_exists:
        if dialect_name == "sqlite":
            with op.batch_alter_table("albums") as batch_op:
                batch_op.create_unique_constraint(
                    constraint_name, ["artist_name", "title"]
                )
        else:
            op.create_unique_constraint(
                constraint_name, "albums", ["artist_name", "title"]
            )


def downgrade() -> None:
    """Remove the unique constraint."""
    conn = op.get_bind()
    dialect_name = conn.dialect.name

    if dialect_name == "sqlite":
        with op.batch_alter_table("albums") as batch_op:
            batch_op.drop_constraint("uq_album_artist_title", type_="unique")
    else:
        op.drop_constraint("uq_album_artist_title", "albums", type_="unique")
