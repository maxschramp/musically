"""Database Explorer router — read-only table browsing."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

import app.database
from app.database import Base
from app.schemas.database_explorer import TableDataResponse, TableInfo, TablesListResponse

router = APIRouter()

# Whitelist of allowed table names for security
ALLOWED_TABLES: set[str] = {
    "albums",
    "artists",
    "track_plays",
    "playlists",
    "playlist_tracks",
    "settings",
    "sync_history",
    "task_runs",
}


@router.get("/database/tables", response_model=TablesListResponse)
async def list_tables() -> TablesListResponse:
    """Return all allowed table names with row counts."""
    async with app.database.async_session_factory() as db:
        tables: list[TableInfo] = []
        for table_name in sorted(ALLOWED_TABLES):
            # Count rows
            try:
                result = await db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
                row_count = result.scalar() or 0
            except Exception:
                row_count = 0

            tables.append(TableInfo(name=table_name, rows=row_count))

    return TablesListResponse(tables=tables)


@router.get("/database/table/{table_name}", response_model=TableDataResponse)
async def browse_table(
    table_name: str,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Rows per page"),
) -> TableDataResponse:
    """Return paginated rows from the specified table (read-only)."""
    if table_name not in ALLOWED_TABLES:
        raise HTTPException(
            status_code=400,
            detail=f"Table '{table_name}' is not allowed. Allowed tables: {', '.join(sorted(ALLOWED_TABLES))}",
        )

    async with app.database.async_session_factory() as db:
        # Get column names from SQLAlchemy metadata (works for SQLite, PostgreSQL, etc.)
        sa_table = Base.metadata.tables.get(table_name)
        if sa_table is not None:
            columns = [c.name for c in sa_table.columns]
        else:
            # Fallback: execute a LIMIT 0 query and infer columns from result keys
            col_result = await db.execute(text(f'SELECT * FROM "{table_name}" LIMIT 0'))
            columns = list(col_result.keys())

        # Count total rows
        count_result = await db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        total_rows = count_result.scalar() or 0

        # Fetch paginated rows
        offset = (page - 1) * limit
        rows_result = await db.execute(
            text(f'SELECT * FROM "{table_name}" LIMIT :limit OFFSET :offset'),
            {"limit": limit, "offset": offset},
        )
        raw_rows = rows_result.fetchall()

        # Convert rows to list of dicts
        rows = [
            {columns[i]: _serialize_value(val) for i, val in enumerate(row)}
            for row in raw_rows
        ]

        total_pages = max(1, (total_rows + limit - 1) // limit) if total_rows > 0 else 1

    return TableDataResponse(
        table_name=table_name,
        columns=columns,
        rows=rows,
        total_rows=total_rows,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )


def _serialize_value(value: object) -> str | int | float | None:
    """Convert a database value to a JSON-serializable type."""
    if value is None:
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    # Handle datetime, UUID, bytes, etc.
    return str(value)
