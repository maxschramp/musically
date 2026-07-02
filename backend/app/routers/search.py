"""Search router — unified search across MusicBrainz, Spotify, and Qobuz."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.album import Album, AlbumStatus
from app.schemas.search import SearchResponse, SearchResult
from app.services.musicbrainz import MusicBrainzService
from app.services.qobuz import QobuzService
from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_musicbrainz(item: dict, source: str = "musicbrainz") -> SearchResult:
    """Convert a MusicBrainz search dict into a SearchResult."""
    if item.get("type") == "artist":
        return SearchResult(
            source=source,
            type="artist",
            artist_name=item.get("name"),
            name=item.get("name"),
            mbid=item.get("mbid"),
        )
    return SearchResult(
        source=source,
        type="album",
        title=item.get("title"),
        artist_name=item.get("artist_name"),
        mbid=item.get("mbid"),
        year=item.get("year"),
    )


def _normalize_spotify(item: dict) -> SearchResult:
    """Convert a Spotify search dict into a SearchResult."""
    if item.get("type") == "artist":
        return SearchResult(
            source="spotify",
            type="artist",
            artist_name=item.get("name"),
            name=item.get("name"),
            spotify_id=item.get("spotify_id"),
        )
    return SearchResult(
        source="spotify",
        type="album",
        title=item.get("title"),
        artist_name=item.get("artist_name"),
        spotify_id=item.get("spotify_id"),
        year=item.get("year"),
    )


def _normalize_qobuz(item: dict) -> SearchResult:
    """Convert a Qobuz search dict into a SearchResult."""
    return SearchResult(
        source="qobuz",
        type="album",
        title=item.get("title"),
        artist_name=item.get("artist_name"),
        qobuz_id=item.get("qobuz_id"),
        year=item.get("year"),
    )


# ---------------------------------------------------------------------------
# Library / queue status checking
# ---------------------------------------------------------------------------


async def _enrich_library_status(
    db: AsyncSession, results: list[SearchResult]
) -> None:
    """For each album result, mark in_library and in_queue by querying the DB.

    Matches are done case-insensitively on (artist_name, title).
    """
    album_results = [r for r in results if r.type == "album" and r.artist_name and r.title]
    if not album_results:
        return

    # Build OR conditions for all artist+title pairs
    conditions = [
        (func.lower(Album.artist_name) == r.artist_name.lower())  # type: ignore[union-attr]
        & (func.lower(Album.title) == r.title.lower())  # type: ignore[union-attr]
        for r in album_results
    ]
    if not conditions:
        return

    stmt = select(Album.artist_name, Album.title, Album.status).where(
        or_(*conditions)
    )
    rows = await db.execute(stmt)
    # Prefer "better" statuses when duplicates exist for the same (artist, title)
    _STATUS_PRIORITY = {
        AlbumStatus.DOWNLOADED: 5,
        AlbumStatus.DOWNLOADING: 3,
        AlbumStatus.QUEUED: 2,
        AlbumStatus.STALLED: 1,
        AlbumStatus.REJECTED: 0,
    }
    db_matches: dict[tuple[str, str], AlbumStatus] = {}
    for row in rows:
        key = (row[0].lower(), row[1].lower())
        new_status = row[2]
        new_prio = _STATUS_PRIORITY.get(new_status, 0)
        existing_prio = _STATUS_PRIORITY.get(db_matches.get(key), -1)
        if new_prio > existing_prio:
            db_matches[key] = new_status

    for r in album_results:
        key = (r.artist_name.lower(), r.title.lower())  # type: ignore[union-attr]
        status = db_matches.get(key)
        if status is None:
            continue
        if status == AlbumStatus.DOWNLOADED:
            r.in_library = True
        elif status in (AlbumStatus.QUEUED, AlbumStatus.DOWNLOADING, AlbumStatus.STALLED):
            r.in_queue = True


# ---------------------------------------------------------------------------
# Per-source search helpers (run concurrently)
# ---------------------------------------------------------------------------


async def _search_musicbrainz(
    query: str, search_type: str
) -> tuple[list[SearchResult], str | None]:
    """Search MusicBrainz; returns (results, warning_or_none)."""
    svc = MusicBrainzService()
    try:
        if search_type == "both":
            album_items, artist_items = await asyncio.gather(
                svc.search(query, "album"),
                svc.search(query, "artist"),
            )
            items = album_items + artist_items
        else:
            items = await svc.search(query, search_type)
        results = [_normalize_musicbrainz(item) for item in items]
        return results, None
    except Exception as exc:
        logger.warning("MusicBrainz search failed: %s", exc)
        return [], f"MusicBrainz: {exc}"
    finally:
        await svc.close()


async def _search_spotify(
    query: str, search_type: str
) -> tuple[list[SearchResult], str | None]:
    """Search Spotify via client credentials; returns (results, warning_or_none)."""
    settings = get_settings()
    if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
        return [], "Spotify: client_id/client_secret not configured"

    svc = SpotifyService(
        client_id=settings.SPOTIFY_CLIENT_ID,
        client_secret=settings.SPOTIFY_CLIENT_SECRET,
    )
    try:
        type_map = {"album": "album", "artist": "artist", "both": "album,artist"}
        sp_type = type_map.get(search_type, "album")
        items = await svc.search(query, sp_type)
        results = [_normalize_spotify(item) for item in items]
        return results, None
    except Exception as exc:
        logger.warning("Spotify search failed: %s", exc)
        return [], f"Spotify: {exc}"
    finally:
        await svc.close()


async def _search_qobuz(
    query: str, search_type: str
) -> tuple[list[SearchResult], str | None]:
    """Search Qobuz; returns (results, warning_or_none).

    Qobuz only supports album search, so artist/both types fall back to
    album search with a note.
    """
    settings = get_settings()
    if not settings.QOBUZ_EMAIL or not settings.QOBUZ_PASSWORD:
        return [], "Qobuz: email/password not configured"

    try:
        svc = QobuzService(
            email=settings.QOBUZ_EMAIL,
            password=settings.QOBUZ_PASSWORD,
        )
    except ValueError as exc:
        return [], f"Qobuz: {exc}"

    try:
        if search_type == "artist":
            # Qobuz doesn't have artist search — skip with warning
            return [], "Qobuz: artist search not supported (album search only)"
        items = await svc.search(query)
        results = [_normalize_qobuz(item) for item in items]
        return results, None
    except Exception as exc:
        logger.warning("Qobuz search failed: %s", exc)
        return [], f"Qobuz: {exc}"
    finally:
        await svc.close()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="Search query string"),
    type: str = Query("album", alias="type", description="Search type: album, artist, or both"),
    source: str = Query("musicbrainz", alias="source", description="Comma-separated sources: musicbrainz,spotify,qobuz"),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Unified search across MusicBrainz, Spotify, and Qobuz.

    Queries each configured source concurrently and returns normalised
    results annotated with library/queue membership flags.
    """
    sources = [s.strip().lower() for s in source.split(",") if s.strip()]
    search_type = type.strip().lower()
    if search_type not in ("album", "artist", "both"):
        search_type = "album"

    all_results: list[SearchResult] = []
    warnings: list[str] = []

    # Build per-source coroutines
    coros: list = []
    source_names: list[str] = []

    if "musicbrainz" in sources:
        coros.append(_search_musicbrainz(q, search_type))
        source_names.append("musicbrainz")

    if "spotify" in sources:
        coros.append(_search_spotify(q, search_type))
        source_names.append("spotify")

    if "qobuz" in sources:
        coros.append(_search_qobuz(q, search_type))
        source_names.append("qobuz")

    if not coros:
        return SearchResponse(query=q, results=[], warnings=["No valid sources specified"])

    # Run all searches concurrently
    gathered = await asyncio.gather(*coros, return_exceptions=True)

    for i, result in enumerate(gathered):
        if isinstance(result, Exception):
            warnings.append(f"{source_names[i]}: {result}")
            continue
        items, warn = result
        all_results.extend(items)
        if warn:
            warnings.append(warn)

    # Enrich with library / queue status
    await _enrich_library_status(db, all_results)

    return SearchResponse(query=q, results=all_results, warnings=warnings)
