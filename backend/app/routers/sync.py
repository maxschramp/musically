"""Sync router — trigger and history endpoints for the sync orchestrator."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.database
from app.config import get_settings
from app.database import get_db
from app.models.sync_history import SyncHistory
from app.schemas.common import PaginatedResponse
from app.schemas.sync import SyncResultResponse, SyncHistoryResponse
from app.services.sync_orchestrator import SyncOrchestrator

router = APIRouter()


@router.post("/sync/trigger", response_model=SyncResultResponse)
async def trigger_sync() -> SyncResultResponse:
    """Manually trigger a full sync cycle.

    Creates a SyncOrchestrator, runs the sync pipeline (LastFM fetch →
    aggregation → history), and returns the result.
    """
    settings = get_settings()
    orchestrator = SyncOrchestrator(
        db_session_factory=app.database.async_session_factory,
        settings=settings,
    )
    result = await orchestrator.run_sync()
    return SyncResultResponse(
        sync_id=result.sync_id,
        started_at=result.started_at,
        completed_at=result.completed_at,
        status=result.status,
        tracks_fetched=result.tracks_fetched,
        tracks_new=result.tracks_new,
        albums_updated=result.albums_updated,
        artists_updated=result.artists_updated,
        error_message=result.error_message,
    )


@router.get("/sync/history", response_model=PaginatedResponse[SyncHistoryResponse])
async def sync_history(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[SyncHistoryResponse]:
    """Return sync run history, ordered by most recent first."""
    # Count total
    count_stmt = select(func.count(SyncHistory.id))
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # Fetch page
    offset = (page - 1) * limit
    stmt = (
        select(SyncHistory)
        .order_by(SyncHistory.started_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    total_pages = max(1, (total + limit - 1) // limit) if total > 0 else 1

    return PaginatedResponse(
        items=[SyncHistoryResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=limit,
        total_pages=total_pages,
    )
