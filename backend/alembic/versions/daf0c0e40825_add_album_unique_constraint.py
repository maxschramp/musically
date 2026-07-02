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

    # ------------------------------------------------------------------
    # Step 1: Find duplicate (artist_name, title) groups and keep the
    # row with the "best" status.  Works on both SQLite and PostgreSQL.
    # ------------------------------------------------------------------

    # Get all rows from albums so we can deduplicate in Python.
    # We only need (id, artist_name, title, status).
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
        # Sort: best status first (lowest _STATUS_KEEP_ORDER value)
        entries.sort(key=lambda x: _STATUS_KEEP_ORDER.get(x[3].lower(), 5))
        # Keep the first (best), delete the rest
        for dup in entries[1:]:
            ids_to_delete.append(dup[0])

    if ids_to_delete:
        # Delete in batches to avoid overly large IN clauses
        batch_size = 500
        for i in range(0, len(ids_to_delete), batch_size):
            batch = ids_to_delete[i : i + batch_size]
            placeholders = ", ".join(f"'{id_}'" for id_ in batch)
            conn.execute(sa.text(f"DELETE FROM albums WHERE id IN ({placeholders})"))

    # ------------------------------------------------------------------
    # Step 2: Add the unique constraint (skip if already exists)
    # ------------------------------------------------------------------
    # Check if constraint already exists (e.g., from create_all on SQLite)
    constraint_exists = False
    try:
        indexes = conn.execute(sa.text("PRAGMA index_list('albums')")).fetchall()
        index_names = {row[1] for row in indexes}
        if "uq_album_artist_title" in index_names or any(
            "uq_album_artist_title" in (name or "") for name in index_names
        ):
            constraint_exists = True
    except Exception:
        pass

    if not constraint_exists:
        with op.batch_alter_table("albums") as batch_op:
            batch_op.create_unique_constraint(
                "uq_album_artist_title", ["artist_name", "title"]
            )


def downgrade() -> None:
    """Remove the unique constraint."""
    with op.batch_alter_table("albums") as batch_op:
        batch_op.drop_constraint("uq_album_artist_title", type_="unique")
