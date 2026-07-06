"""Playlists router — list, update, and refresh playlists."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.playlist import Playlist
from app.schemas.common import PaginatedResponse
from app.schemas.playlist import PlaylistResponse, PlaylistUpdate

logger = logging.getLogger(__name__)

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
async def refresh_playlists(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fetch fresh playlists from Spotify, re-classify, and upsert tracks.

    Requires Spotify to be configured with a valid refresh token
    (OAuth PKCE flow completed via Settings → Connect Spotify).
    """
    from app.models.setting import Setting
    from app.services.spotify import (
        SpotifyService,
        SpotifySyncResult,
        _decrypt_token,
    )

    # 1. Read Spotify credentials from settings
    stmt = select(Setting).where(Setting.key.in_([
        "spotify_client_id", "spotify_client_secret",
        "spotify_redirect_uri", "spotify_refresh_token",
        "spotify_access_token_encrypted", "spotify_token_expiry",
    ]))
    rows = await db.execute(stmt)
    settings_map: dict[str, str] = {s.key: s.value for s in rows.scalars().all()}

    client_id = settings_map.get("spotify_client_id", "")
    client_secret = settings_map.get("spotify_client_secret", "")
    redirect_uri = settings_map.get(
        "spotify_redirect_uri",
        "http://localhost:8000/api/spotify/auth/callback",
    )

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="Spotify Client ID and Secret must be configured in Settings.",
        )

    encrypted_refresh = settings_map.get("spotify_refresh_token", "")
    if not _decrypt_token(encrypted_refresh):
        raise HTTPException(
            status_code=400,
            detail=(
                "Not connected to Spotify. Go to Settings → Spotify "
                "and click 'Connect Spotify' to authorize."
            ),
        )

    # 2. Build Spotify service and pre-load existing tokens
    spotify = SpotifyService(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )

    encrypted_access = settings_map.get("spotify_access_token_encrypted", "")
    if encrypted_access:
        spotify._access_token = _decrypt_token(encrypted_access)

    expiry_str = settings_map.get("spotify_token_expiry", "")
    if expiry_str:
        from datetime import datetime as dt
        try:
            spotify._token_expiry = dt.fromisoformat(expiry_str)
        except ValueError:
            pass

    # 3. Run sync
    try:
        result: SpotifySyncResult = await spotify.sync_playlists(db)
        logger.info(
            "Manual playlist refresh: %d playlists, %d tracks, "
            "seasonal=%d discover=%d other=%d",
            result.playlists_synced,
            result.tracks_added,
            result.seasonal,
            result.discover,
            result.other,
        )
        return {
            "status": "ok",
            "playlists_synced": result.playlists_synced,
            "tracks_added": result.tracks_added,
            "seasonal": result.seasonal,
            "discover": result.discover,
            "other": result.other,
        }
    except Exception as exc:
        logger.exception("Manual playlist refresh failed")
        raise HTTPException(
            status_code=500,
            detail=f"Spotify sync failed: {exc}",
        ) from exc
    finally:
        await spotify.close()
