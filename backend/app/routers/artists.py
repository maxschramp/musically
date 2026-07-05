"""Artists router — artist listing, detail, subscribe/unsubscribe, and per-artist albums."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.album import Album, AlbumStatus
from app.models.artist import Artist
from app.models.setting import Setting
from app.schemas.album import AlbumResponse
from app.schemas.artist import ArtistCreate, ArtistLookupRequest, ArtistResponse
from app.schemas.common import PaginatedResponse

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /artists — List artists
# ---------------------------------------------------------------------------
@router.get("/artists", response_model=PaginatedResponse[ArtistResponse])
async def list_artists(
    subscribed: bool | None = Query(None, description="Filter by subscription status"),
    search: str | None = Query(None, description="Search artist name (case-insensitive contains)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ArtistResponse]:
    """List artists.

    Supports optional filtering by subscription status and name search.
    Results are sorted alphabetically by name.
    """
    stmt = select(Artist)

    if subscribed is not None:
        stmt = stmt.where(Artist.subscribed == subscribed)

    if search:
        stmt = stmt.where(func.lower(Artist.name).contains(search.lower()))

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Apply pagination (sorted by name ascending)
    offset = (page - 1) * limit
    result = await db.execute(
        stmt.order_by(Artist.name.asc()).offset(offset).limit(limit)
    )
    artists = result.scalars().all()

    total_pages = max(1, (total + limit - 1) // limit)

    return PaginatedResponse(
        items=[ArtistResponse.model_validate(a) for a in artists],
        total=total,
        page=page,
        page_size=limit,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# GET /artists/lookup — Find artist by name (for FollowButton initial state)
# MUST be defined BEFORE /artists/{artist_id} to avoid "lookup" matching as a UUID
# ---------------------------------------------------------------------------
@router.get("/artists/lookup")
async def lookup_artist_get(
    artist_name: str = Query(..., min_length=1, description="Artist name (case-insensitive)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Look up an artist by name (case-insensitive) via GET.

    Returns a lightweight response suitable for the FollowButton component:
      - found: whether the artist exists in the DB
      - artist_id: the artist's UUID (null if not found)
      - artist_name: the resolved artist name
      - subscribed: current subscription status
    """
    artist = await _find_artist_by_name(db, artist_name)
    if artist is None:
        return {
            "found": False,
            "artist_id": None,
            "artist_name": artist_name.strip(),
            "subscribed": False,
        }
    return {
        "found": True,
        "artist_id": str(artist.id),
        "artist_name": artist.name,
        "subscribed": artist.subscribed,
    }


# ---------------------------------------------------------------------------
# GET /artists/{artist_id} — Single artist
# ---------------------------------------------------------------------------
@router.get("/artists/{artist_id}", response_model=ArtistResponse)
async def get_artist(
    artist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ArtistResponse:
    """Get a single artist by ID."""
    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if artist is None:
        raise HTTPException(status_code=404, detail=f"Artist {artist_id} not found")
    return ArtistResponse.model_validate(artist)


# ---------------------------------------------------------------------------
# POST /artists — Create artist manually
# ---------------------------------------------------------------------------
@router.post("/artists", response_model=ArtistResponse, status_code=201)
async def create_artist(
    body: ArtistCreate,
    db: AsyncSession = Depends(get_db),
) -> ArtistResponse:
    """Create a new artist manually.

    Returns 409 Conflict if an artist with the same name already exists.
    """
    existing = await _find_artist_by_name(db, body.name)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Artist '{body.name}' already exists",
        )

    artist = Artist(
        name=body.name.strip(),
        artist_mbid=body.artist_mbid,
        subscribed=False,
    )
    db.add(artist)
    await db.commit()
    await db.refresh(artist)
    return ArtistResponse.model_validate(artist)


# ---------------------------------------------------------------------------
# POST /artists/{artist_id}/subscribe
# ---------------------------------------------------------------------------
@router.post("/artists/{artist_id}/subscribe", response_model=ArtistResponse)
async def subscribe_artist(
    artist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ArtistResponse:
    """Subscribe to an artist for automatic downloads.

    Sets subscribed=True and subscription_source="manual".
    """
    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if artist is None:
        raise HTTPException(status_code=404, detail=f"Artist {artist_id} not found")

    artist.subscribed = True
    artist.subscription_source = "manual"
    await db.commit()
    await db.refresh(artist)
    return ArtistResponse.model_validate(artist)


# ---------------------------------------------------------------------------
# POST /artists/{artist_id}/unsubscribe
# ---------------------------------------------------------------------------
@router.post("/artists/{artist_id}/unsubscribe", response_model=ArtistResponse)
async def unsubscribe_artist(
    artist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ArtistResponse:
    """Unsubscribe from an artist.

    Sets subscribed=False and subscription_source=None.
    """
    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if artist is None:
        raise HTTPException(status_code=404, detail=f"Artist {artist_id} not found")

    artist.subscribed = False
    artist.subscription_source = None
    await db.commit()
    await db.refresh(artist)
    return ArtistResponse.model_validate(artist)


# ---------------------------------------------------------------------------
# GET /artists/{artist_id}/albums — Albums by this artist
# ---------------------------------------------------------------------------
@router.get("/artists/{artist_id}/albums", response_model=PaginatedResponse[AlbumResponse])
async def get_artist_albums(
    artist_id: uuid.UUID,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AlbumResponse]:
    """Get downloaded albums by this artist.

    Looks up the artist by ID, then returns all downloaded albums
    matching that artist's name.
    """
    # Find the artist first
    artist_result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = artist_result.scalar_one_or_none()
    if artist is None:
        raise HTTPException(status_code=404, detail=f"Artist {artist_id} not found")

    # Query albums by artist name (only downloaded)
    stmt = select(Album).where(
        Album.artist_name == artist.name,
        Album.status == AlbumStatus.DOWNLOADED,
    )

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Apply pagination (sorted by title ascending)
    offset = (page - 1) * limit
    result = await db.execute(
        stmt.order_by(Album.title.asc()).offset(offset).limit(limit)
    )
    albums = result.scalars().all()

    total_pages = max(1, (total + limit - 1) // limit)

    return PaginatedResponse(
        items=[AlbumResponse.model_validate(a) for a in albums],
        total=total,
        page=page,
        page_size=limit,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# POST /artists/auto-follow — Scan library and auto-subscribe artists
# ---------------------------------------------------------------------------
@router.post("/artists/auto-follow")
async def auto_follow_artists(db: AsyncSession = Depends(get_db)) -> dict:
    """Scan the music library directory and auto-subscribe artists.

    Reads music_library_directory from settings, scans for Artist/Album
    directory layout, counts albums per artist, and subscribes artists
    whose album count meets or exceeds library_albums_subscribe_threshold.
    """
    # --- Resolve settings ---
    lib_stmt = select(Setting.value).where(Setting.key == "music_library_directory")
    lib_result = await db.execute(lib_stmt)
    lib_path_str = lib_result.scalar() or "/music/library"

    threshold_stmt = select(Setting.value).where(Setting.key == "library_albums_subscribe_threshold")
    threshold_result = await db.execute(threshold_stmt)
    threshold_str = threshold_result.scalar() or "2"
    threshold = int(threshold_str)

    lib_path = Path(lib_path_str)
    music_exts = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".wma", ".wav", ".aiff", ".alac"}

    # --- Scan directory ---
    artists_scanned = 0
    artists_subscribed = 0
    details: list[dict[str, object]] = []

    if not lib_path.exists():
        return {
            "artists_scanned": 0,
            "artists_subscribed": 0,
            "details": [],
            "message": f"Library directory does not exist: {lib_path_str}",
        }

    for entry in sorted(lib_path.iterdir()):
        if not entry.is_dir():
            continue

        artist_name = entry.name

        # Count album subdirectories that contain music files
        album_count = 0
        try:
            for sub in sorted(entry.iterdir()):
                if not sub.is_dir():
                    continue
                try:
                    if any(
                        f.is_file() and f.suffix.lower() in music_exts
                        for f in sub.iterdir()
                    ):
                        album_count += 1
                except (PermissionError, OSError):
                    pass
        except (PermissionError, OSError):
            continue

        if album_count == 0:
            continue

        artists_scanned += 1
        details.append({"name": artist_name, "albums": album_count})

        if album_count < threshold:
            continue

        # Find or create Artist record
        artist_stmt = select(Artist).where(func.lower(Artist.name) == artist_name.lower())
        artist_result = await db.execute(artist_stmt)
        artist = artist_result.scalar_one_or_none()

        if artist is None:
            artist = Artist(
                name=artist_name,
                subscribed=True,
                subscription_source="auto_library_size",
                albums_in_library=album_count,
            )
            db.add(artist)
        else:
            artist.subscribed = True
            artist.subscription_source = "auto_library_size"
            artist.albums_in_library = album_count

        artists_subscribed += 1

    await db.commit()

    return {
        "artists_scanned": artists_scanned,
        "artists_subscribed": artists_subscribed,
        "details": details,
    }


# ---------------------------------------------------------------------------
# POST /artists/lookup — Find or create artist by name
# ---------------------------------------------------------------------------
@router.post("/artists/lookup", response_model=ArtistResponse)
async def lookup_artist(
    body: ArtistLookupRequest,
    db: AsyncSession = Depends(get_db),
) -> ArtistResponse:
    """Look up an artist by name (case-insensitive).

    If found, returns the existing record.
    If not found, creates a new Artist record (subscribed=False) and returns it.
    """
    artist = await _find_artist_by_name(db, body.artist_name)
    if artist is None:
        artist = Artist(
            id=uuid.uuid4(),
            name=body.artist_name.strip(),
            subscribed=False,
        )
        db.add(artist)
        await db.commit()
        await db.refresh(artist)
    return ArtistResponse.model_validate(artist)


# ---------------------------------------------------------------------------
# POST /artists/subscribe-by-name — Subscribe by artist name
# ---------------------------------------------------------------------------
@router.post("/artists/subscribe-by-name", response_model=ArtistResponse)
async def subscribe_by_name(
    body: ArtistLookupRequest,
    db: AsyncSession = Depends(get_db),
) -> ArtistResponse:
    """Subscribe to an artist by name (case-insensitive).

    If the artist does not exist, a new record is created.
    Sets subscribed=True and subscription_source="manual".
    """
    artist = await _find_artist_by_name(db, body.artist_name)
    if artist is None:
        artist = Artist(
            id=uuid.uuid4(),
            name=body.artist_name.strip(),
            subscribed=True,
            subscription_source="manual",
        )
        db.add(artist)
    else:
        artist.subscribed = True
        artist.subscription_source = "manual"

    await db.commit()
    await db.refresh(artist)
    return ArtistResponse.model_validate(artist)


# ---------------------------------------------------------------------------
# POST /artists/unsubscribe-by-name — Unsubscribe by artist name
# ---------------------------------------------------------------------------
@router.post("/artists/unsubscribe-by-name", response_model=ArtistResponse)
async def unsubscribe_by_name(
    body: ArtistLookupRequest,
    db: AsyncSession = Depends(get_db),
) -> ArtistResponse:
    """Unsubscribe from an artist by name (case-insensitive).

    Returns 404 if the artist is not found.
    """
    artist = await _find_artist_by_name(db, body.artist_name)
    if artist is None:
        raise HTTPException(
            status_code=404,
            detail=f"Artist '{body.artist_name}' not found",
        )

    artist.subscribed = False
    artist.subscription_source = None
    await db.commit()
    await db.refresh(artist)
    return ArtistResponse.model_validate(artist)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
async def _find_artist_by_name(db: AsyncSession, name: str) -> Artist | None:
    """Find an artist by name (case-insensitive). Returns None if not found."""
    result = await db.execute(
        select(Artist).where(func.lower(Artist.name) == name.strip().lower())
    )
    return result.scalar_one_or_none()
