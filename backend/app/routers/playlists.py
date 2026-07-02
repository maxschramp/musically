"""Playlists router — list, update, and refresh playlists."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.playlist import Playlist
from app.schemas.common import PaginatedResponse
from app.schemas.playlist import PlaylistResponse, PlaylistUpdate

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /playlists — List playlists
# ---------------------------------------------------------------------------
@router.get("/playlists", response_model=PaginatedResponse[PlaylistResponse])
async def list_playlists(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[PlaylistResponse]:
    """List all configured playlists with their tracks."""
    stmt = select(Playlist)

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Apply pagination (sorted by name)
    offset = (page - 1) * limit
    result = await db.execute(
        stmt.options(selectinload(Playlist.tracks))
        .order_by(Playlist.name.asc())
        .offset(offset)
        .limit(limit)
    )
    playlists = result.scalars().all()

    total_pages = max(1, (total + limit - 1) // limit)

    return PaginatedResponse(
        items=[PlaylistResponse.model_validate(p) for p in playlists],
        total=total,
        page=page,
        page_size=limit,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# PUT /playlists/{playlist_id} — Update playlist
# ---------------------------------------------------------------------------
@router.put("/playlists/{playlist_id}", response_model=PlaylistResponse)
async def update_playlist(
    playlist_id: uuid.UUID,
    body: PlaylistUpdate,
    db: AsyncSession = Depends(get_db),
) -> PlaylistResponse:
    """Update a playlist's type or active status."""
    result = await db.execute(
        select(Playlist).options(selectinload(Playlist.tracks)).where(Playlist.id == playlist_id)
    )
    playlist = result.scalar_one_or_none()
    if playlist is None:
        raise HTTPException(status_code=404, detail=f"Playlist {playlist_id} not found")

    if body.playlist_type is not None:
        playlist.playlist_type = body.playlist_type
    if body.is_active is not None:
        playlist.is_active = body.is_active

    await db.commit()
    await db.refresh(playlist)
    return PlaylistResponse.model_validate(playlist)


# ---------------------------------------------------------------------------
# POST /playlists/refresh — Trigger Spotify refresh
# ---------------------------------------------------------------------------
@router.post("/playlists/refresh")
async def refresh_playlists() -> dict:
    """Trigger a refresh of all playlists from Spotify.

    Spotify integration is pending (Phase 6). This endpoint is a stub.
    """
    return {"status": "ok", "message": "Playlist refresh triggered (Spotify integration pending)"}
