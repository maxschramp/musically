"""Schemas for the Database Explorer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TableInfo(BaseModel):
    """Info about a database table."""
    name: str
    rows: int


class TablesListResponse(BaseModel):
    """Response for GET /api/database/tables."""
    tables: list[TableInfo]


class TableDataResponse(BaseModel):
    """Response for GET /api/database/table/{table_name}."""
    table_name: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total_rows: int
    page: int
    limit: int
    total_pages: int
