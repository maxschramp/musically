"""Queue router — real DB-backed endpoints for album download queue management."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.album import Album, AlbumStatus, QueueType
from app.models.artist import Artist
from app.models.playlist_track import PlaylistTrack
from app.services.event_bus import event_bus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Background download helper — used when Celery workers aren't available
# ---------------------------------------------------------------------------

def _dispatch_download_bg(album_id: uuid.UUID) -> None:
    """Fire-and-forget: run the download pipeline in the background.

    Creates an asyncio task that runs independently of the HTTP request.
    Used when no Celery worker is available to process the task queue.
    """
    async def _run() -> None:
        try:
            from app.services.downloader import _build_pipeline_async
            pipeline = await _build_pipeline_async()
            result = await pipeline.process_album(album_id)
            if result.success:
                logger.info("Background download complete: %s", album_id)
            else:
                logger.warning("Background download failed: %s — %s", album_id, result.message)
            await pipeline.qobuz.close()
            await pipeline.notifier.close()
        except Exception:
            logger.exception("Background download crashed for %s", album_id)

    asyncio.create_task(_run())


def _celery_available() -> bool:
    """Check whether a Celery worker is online and able to process tasks."""
    try:
        from app.celery_app import celery_app
        workers = celery_app.control.ping(timeout=1.5)
        return bool(workers)
    except Exception:
        return False


def _try_dispatch(album_id: uuid.UUID) -> None:
    """Dispatch a download via Celery if available, otherwise run in background."""
    if _celery_available():
        try:
            from app.services.downloader import download_album_task
            download_album_task.delay(str(album_id))
            logger.info("Dispatched download %s via Celery", album_id)
            return
        except Exception:
            logger.warning("Celery dispatch failed for %s, falling back to background", album_id)

    # No Celery worker — run directly in the background
    _dispatch_download_bg(album_id)
from app.schemas.album import AlbumBulkCreate, AlbumCreate, AlbumResponse
from app.schemas.common import PaginatedResponse

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _album_to_response(album: Album) -> AlbumResponse:
    return AlbumResponse.model_validate(album)


# ---------------------------------------------------------------------------
# GET /queue — List with filters and pagination
# ---------------------------------------------------------------------------
@router.get("/queue", response_model=PaginatedResponse[AlbumResponse])
async def list_queue(
    status: str | None = Query(None, description="Filter by album status"),
    type: str | None = Query(None, description="Filter by queue type"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    sort: str = Query("created_at", description="Sort field"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AlbumResponse]:
    """List queue (album) entries with optional status/type filters and pagination.

    Supports filtering by:
      - status: queued, downloading, downloaded, stalled, rejected
      - type: auto, manual, watch_folder

    Results are sorted by created_at (default, newest last).
    Use sort=-created_at for reverse order.
    """
    # Build base query
    stmt = select(Album)

    # By default, hide rejected albums (they can still be shown with status=rejected)
    if status is None:
        stmt = stmt.where(Album.status != AlbumStatus.REJECTED)

    if status is not None:
        try:
            album_status = AlbumStatus(status)
            stmt = stmt.where(Album.status == album_status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}. Valid values: {[s.value for s in AlbumStatus]}",
            )

    if type is not None:
        try:
            queue_type = QueueType(type)
            stmt = stmt.where(Album.queue_type == queue_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid type: {type}. Valid values: {[t.value for t in QueueType]}",
            )

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Apply sorting
    descending = False
    sort_field = sort
    if sort.startswith("-"):
        descending = True
        sort_field = sort[1:]

    sort_column = getattr(Album, sort_field, Album.created_at)
    if descending:
        sort_column = sort_column.desc()
    else:
        sort_column = sort_column.asc()

    # Apply pagination
    offset = (page - 1) * limit
    result = await db.execute(
        stmt.order_by(sort_column).offset(offset).limit(limit)
    )
    albums = list(result.scalars().all())

    # -------------------------------------------------------------------
    # Enrich queued albums with track counts from PlaylistTrack.
    # Queued albums don't have files on disk yet, so filesystem-based
    # counting (used by the Library endpoint) always returns 0.  Instead,
    # count matching PlaylistTrack rows from LastFM / Spotify playlists.
    # -------------------------------------------------------------------
    for album in albums:
        count_stmt = select(func.count(PlaylistTrack.id)).where(
            func.lower(PlaylistTrack.artist_name) == func.lower(album.artist_name),
            func.lower(PlaylistTrack.album_name) == func.lower(album.title),
        )
        count_result = await db.execute(count_stmt)
        setattr(album, 'track_count', count_result.scalar() or 0)

    total_pages = max(1, (total + limit - 1) // limit)

    return PaginatedResponse(
        items=[_album_to_response(a) for a in albums],
        total=total,
        page=page,
        page_size=limit,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# GET /queue/{id} — Single album
# ---------------------------------------------------------------------------
@router.get("/queue/{queue_id}", response_model=AlbumResponse)
async def get_queue_item(
    queue_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AlbumResponse:
    """Get a single queue item (album) by ID."""
    result = await db.execute(select(Album).where(Album.id == queue_id))
    album = result.scalar_one_or_none()
    if album is None:
        raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

    # Enrich with track count from PlaylistTrack
    count_stmt = select(func.count(PlaylistTrack.id)).where(
        func.lower(PlaylistTrack.artist_name) == func.lower(album.artist_name),
        func.lower(PlaylistTrack.album_name) == func.lower(album.title),
    )
    count_result = await db.execute(count_stmt)
    setattr(album, 'track_count', count_result.scalar() or 0)

    return _album_to_response(album)


# ---------------------------------------------------------------------------
# POST /queue — Create queue item
# ---------------------------------------------------------------------------
async def _find_or_create_artist(db: AsyncSession, name: str) -> Artist:
    """Find an artist by name (case-insensitive), or create one if not found."""
    result = await db.execute(
        select(Artist).where(func.lower(Artist.name) == name.strip().lower())
    )
    artist = result.scalar_one_or_none()
    if artist is None:
        artist = Artist(name=name.strip(), subscribed=False)
        db.add(artist)
        await db.flush()
    return artist


@router.post("/queue", response_model=AlbumResponse, status_code=201)
async def create_queue_item(
    body: AlbumCreate,
    db: AsyncSession = Depends(get_db),
) -> AlbumResponse:
    """Create a new album queue entry.

    Auto-creates the Artist record if one doesn't already exist
    for this artist name (find-or-create pattern).
    """
    await _find_or_create_artist(db, body.artist_name)

    # Check if album already exists (case-insensitive)
    existing_stmt = select(Album).where(
        func.lower(Album.artist_name) == body.artist_name.strip().lower(),
        func.lower(Album.title) == body.title.strip().lower(),
    )
    existing_result = await db.execute(existing_stmt)
    existing_album = existing_result.scalar()

    if existing_album is not None:
        if existing_album.status in (AlbumStatus.DOWNLOADED, AlbumStatus.DOWNLOADING, AlbumStatus.QUEUED):
            raise HTTPException(
                status_code=409,
                detail=f"'{body.artist_name} - {body.title}' is already in queue or library",
            )
        # Stalled or rejected — re-queue the existing row instead of creating a new one
        existing_album.status = AlbumStatus.QUEUED
        existing_album.queue_type = body.queue_type
        existing_album.reason = body.reason
        existing_album.album_mbid = body.album_mbid or existing_album.album_mbid
        existing_album.qobuz_id = body.qobuz_id or existing_album.qobuz_id
        await db.commit()
        await db.refresh(existing_album)
        return _album_to_response(existing_album)

    album = Album(
        title=body.title,
        artist_name=body.artist_name,
        album_mbid=body.album_mbid,
        qobuz_id=body.qobuz_id,
        queue_type=body.queue_type,
        reason=body.reason,
        status=AlbumStatus.QUEUED,
    )
    db.add(album)
    await db.commit()
    await db.refresh(album)
    return _album_to_response(album)


# ---------------------------------------------------------------------------
# POST /queue/bulk — Create multiple queue items
# ---------------------------------------------------------------------------
@router.post("/queue/bulk", status_code=201)
async def create_queue_items_bulk(
    body: AlbumBulkCreate,
    db: AsyncSession = Depends(get_db),
) -> list[AlbumResponse]:
    """Create multiple album queue entries at once.

    Each album's artist is found-or-created automatically.
    Useful for adding multiple search results in one request.
    """
    albums: list[Album] = []
    skipped = 0
    for item in body.albums:
        # Check if album already exists (case-insensitive)
        existing_stmt = select(Album).where(
            func.lower(Album.artist_name) == item.artist_name.strip().lower(),
            func.lower(Album.title) == item.title.strip().lower(),
        )
        existing_result = await db.execute(existing_stmt)
        existing_album = existing_result.scalar()

        if existing_album is not None:
            if existing_album.status in (AlbumStatus.DOWNLOADED, AlbumStatus.DOWNLOADING, AlbumStatus.QUEUED):
                skipped += 1
                continue
            # Re-queue stalled/rejected
            existing_album.status = AlbumStatus.QUEUED
            existing_album.queue_type = item.queue_type
            existing_album.reason = item.reason
            existing_album.album_mbid = item.album_mbid or existing_album.album_mbid
            existing_album.qobuz_id = item.qobuz_id or existing_album.qobuz_id
            db.add(existing_album)
            albums.append(existing_album)
            continue

        await _find_or_create_artist(db, item.artist_name)
        album = Album(
            title=item.title,
            artist_name=item.artist_name,
            album_mbid=item.album_mbid,
            qobuz_id=item.qobuz_id,
            queue_type=item.queue_type,
            reason=item.reason,
            status=AlbumStatus.QUEUED,
        )
        db.add(album)
        albums.append(album)

    await db.commit()
    for album in albums:
        await db.refresh(album)

    if skipped > 0:
        logger.info("Bulk queue create: %d album(s) skipped (already in queue/library), %d created/requeued", skipped, len(albums))

    return [_album_to_response(a) for a in albums]


# ---------------------------------------------------------------------------
# POST /queue/{id}/approve
# ---------------------------------------------------------------------------
@router.post("/queue/{queue_id}/approve", response_model=AlbumResponse)
async def approve_queue_item(
    queue_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AlbumResponse:
    """Approve a queued album for automatic download.

    Sets queue_type=auto and dispatches the download immediately
    (via Celery worker or in-process background task).
    """
    result = await db.execute(select(Album).where(Album.id == queue_id))
    album = result.scalar_one_or_none()
    if album is None:
        raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

    album.queue_type = QueueType.AUTO
    # If it was stalled, reset it
    if album.status == AlbumStatus.STALLED:
        album.status = AlbumStatus.QUEUED
        album.next_retry_at = None
        album.retry_count = 0
    await db.commit()
    await db.refresh(album)

    # Dispatch download immediately
    _try_dispatch(queue_id)

    event_bus.publish("queue_changed", {"album_id": str(queue_id), "action": "approved"})

    return _album_to_response(album)


# ---------------------------------------------------------------------------
# POST /queue/{id}/promote
# ---------------------------------------------------------------------------
@router.post("/queue/{queue_id}/promote", response_model=AlbumResponse)
async def promote_queue_item(
    queue_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AlbumResponse:
    """Promote an album to download immediately: approve + dispatch."""
    result = await db.execute(select(Album).where(Album.id == queue_id))
    album = result.scalar_one_or_none()
    if album is None:
        raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

    # Approve: change to auto so dispatcher will pick it up
    album.queue_type = QueueType.AUTO
    if album.status == AlbumStatus.STALLED:
        album.status = AlbumStatus.QUEUED
        album.next_retry_at = None
        album.retry_count = 0
    await db.commit()
    await db.refresh(album)

    # Dispatch immediately
    _try_dispatch(queue_id)

    event_bus.publish("queue_changed", {"album_id": str(queue_id), "action": "promoted"})

    return _album_to_response(album)


# ---------------------------------------------------------------------------
# POST /queue/{id}/reject
# ---------------------------------------------------------------------------
@router.post("/queue/{queue_id}/reject", response_model=AlbumResponse)
async def reject_queue_item(
    queue_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AlbumResponse:
    """Reject a queued album. Sets status to rejected."""
    result = await db.execute(select(Album).where(Album.id == queue_id))
    album = result.scalar_one_or_none()
    if album is None:
        raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

    album.status = AlbumStatus.REJECTED
    album.next_retry_at = None
    await db.commit()
    await db.refresh(album)

    event_bus.publish("queue_changed", {"album_id": str(queue_id), "action": "rejected"})

    return _album_to_response(album)


# ---------------------------------------------------------------------------
# POST /queue/{id}/retry
# ---------------------------------------------------------------------------
@router.post("/queue/{queue_id}/retry", response_model=AlbumResponse)
async def retry_queue_item(
    queue_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AlbumResponse:
    """Reset a stuck or stalled album back to queued for retry.

    Clears retry_count and next_retry_at so the dispatcher will pick
    it up on the next cycle.  Works for albums in any non-terminal
    status (downloading, stalled, queued, etc.).
    """
    result = await db.execute(select(Album).where(Album.id == queue_id))
    album = result.scalar_one_or_none()
    if album is None:
        raise HTTPException(status_code=404, detail=f"Queue item {queue_id} not found")

    album.status = AlbumStatus.QUEUED
    album.retry_count = 0
    album.next_retry_at = None
    await db.commit()
    await db.refresh(album)
    return _album_to_response(album)


# ---------------------------------------------------------------------------
# POST /queue/bulk-approve
# ---------------------------------------------------------------------------
@router.post("/queue/bulk-approve")
async def bulk_approve(
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Approve multiple queue items at once.

    Request body: {"ids": ["uuid1", "uuid2", ...]}
    """
    ids_raw = body.get("ids", [])
    if not isinstance(ids_raw, list) or not ids_raw:
        raise HTTPException(status_code=400, detail="Field 'ids' must be a non-empty list")

    approved = 0
    errors = []

    for raw_id in ids_raw:
        try:
            album_id = uuid.UUID(raw_id)
        except (ValueError, TypeError):
            errors.append(f"Invalid UUID: {raw_id}")
            continue

        result = await db.execute(select(Album).where(Album.id == album_id))
        album = result.scalar_one_or_none()
        if album is None:
            errors.append(f"Not found: {raw_id}")
            continue

        album.queue_type = QueueType.AUTO
        if album.status == AlbumStatus.STALLED:
            album.status = AlbumStatus.QUEUED
            album.next_retry_at = None
            album.retry_count = 0
        approved += 1

    await db.commit()

    return {"status": "ok", "approved": approved, "errors": errors, "total": len(ids_raw)}


# ---------------------------------------------------------------------------
# POST /queue/bulk-reject
# ---------------------------------------------------------------------------
@router.post("/queue/bulk-reject")
async def bulk_reject(
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reject multiple queue items at once.

    Request body: {"ids": ["uuid1", "uuid2", ...]}
    """
    ids_raw = body.get("ids", [])
    if not isinstance(ids_raw, list) or not ids_raw:
        raise HTTPException(status_code=400, detail="Field 'ids' must be a non-empty list")

    rejected = 0
    errors = []

    for raw_id in ids_raw:
        try:
            album_id = uuid.UUID(raw_id)
        except (ValueError, TypeError):
            errors.append(f"Invalid UUID: {raw_id}")
            continue

        result = await db.execute(select(Album).where(Album.id == album_id))
        album = result.scalar_one_or_none()
        if album is None:
            errors.append(f"Not found: {raw_id}")
            continue

        album.status = AlbumStatus.REJECTED
        album.next_retry_at = None
        rejected += 1

    await db.commit()

    return {"status": "ok", "rejected": rejected, "errors": errors, "total": len(ids_raw)}


# ---------------------------------------------------------------------------
# POST /queue/clear-stalled
# ---------------------------------------------------------------------------
@router.post("/queue/clear-stalled")
async def clear_stalled(db: AsyncSession = Depends(get_db)) -> dict:
    """Delete all stalled albums from the queue."""
    result = await db.execute(
        select(Album).where(Album.status == AlbumStatus.STALLED)
    )
    stalled = result.scalars().all()
    count = len(stalled)
    for album in stalled:
        await db.delete(album)
    await db.commit()
    return {"cleared": count, "message": f"Cleared {count} stalled album(s)"}
