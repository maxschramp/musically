import os
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.album import Album, AlbumStatus
from app.models.artist import Artist
from app.models.track_play import TrackPlay
from app.schemas.common import StatsResponse

router = APIRouter()

# Possible paths for the VERSION file (Docker, local dev, etc.)
_VERSION_PATHS = [
    Path("/app/VERSION"),
    Path("VERSION"),
    Path(__file__).resolve().parent.parent.parent.parent / "VERSION",
]


def _read_version() -> str:
    """Read version from env or VERSION file, with fallback chain."""
    # 1. Environment variable (set by Dockerfile ARG or docker-compose)
    env_version = os.environ.get("VERSION", "")
    if env_version and env_version != "0.0.0":
        return env_version

    # 2. VERSION file on disk
    for path in _VERSION_PATHS:
        try:
            content = path.read_text().strip()
            if content:
                return content
        except (FileNotFoundError, PermissionError, OSError):
            continue

    # 3. Fall back to env (even if "0.0.0") or hard default
    return env_version or "0.0.0"


@router.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "version": _read_version()}


@router.get("/health/version")
async def get_version() -> dict:
    """Return the current application version and build info."""
    return {
        "version": _read_version(),
        "build_date": os.environ.get("BUILD_DATE", "unknown"),
        "build_ref": os.environ.get("BUILD_REF", "dev"),
    }


@router.get("/stats", response_model=StatsResponse)
async def stats(
    db: AsyncSession = Depends(get_db),
) -> StatsResponse:
    """Return real-time library and queue statistics."""
    total_tracks = await db.scalar(select(func.count(TrackPlay.id)))
    total_artists = await db.scalar(select(func.count(Artist.id)))
    total_albums = await db.scalar(
        select(func.count(Album.id)).where(Album.status == AlbumStatus.DOWNLOADED)
    )
    queued_count = await db.scalar(
        select(func.count(Album.id)).where(Album.status == AlbumStatus.QUEUED)
    )
    downloading_count = await db.scalar(
        select(func.count(Album.id)).where(Album.status == AlbumStatus.DOWNLOADING)
    )
    downloaded_count = await db.scalar(
        select(func.count(Album.id)).where(Album.status == AlbumStatus.DOWNLOADED)
    )
    stalled_count = await db.scalar(
        select(func.count(Album.id)).where(Album.status == AlbumStatus.STALLED)
    )
    rejected_count = await db.scalar(
        select(func.count(Album.id)).where(Album.status == AlbumStatus.REJECTED)
    )
    subscribed_artists = await db.scalar(
        select(func.count(Artist.id)).where(Artist.subscribed == True)
    )

    return StatsResponse(
        total_albums=total_albums or 0,
        total_tracks=total_tracks or 0,
        total_artists=total_artists or 0,
        queued_count=queued_count or 0,
        downloading_count=downloading_count or 0,
        downloaded_count=downloaded_count or 0,
        stalled_count=stalled_count or 0,
        rejected_count=rejected_count or 0,
        subscribed_artists=subscribed_artists or 0,
        watch_folder_pending=0,  # Watch folder integration is Phase 7
    )
