"""Search router — unified search across MusicBrainz, Spotify, and Qobuz.

Supports:
  - Split-query parsing: when the query has 2+ words, the last word(s)
    are interpreted as the album name and the rest as the artist name
    for a more targeted second search.
  - Artist albums endpoint: ``GET /api/search/artist-albums`` returns
    all albums by a given artist from any configured source.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.album import Album, AlbumStatus
from app.models.setting import Setting
from app.schemas.search import SearchResponse, SearchResult
from app.services.musicbrainz import MusicBrainzService
from app.services.qobuz import QobuzService
from app.services.spotify import SpotifyService

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers — credential reading
# ---------------------------------------------------------------------------

SETTINGS_TO_LOAD = (
    "spotify_client_id",
    "spotify_client_secret",
    "qobuz_email",
    "qobuz_password_encrypted",
)


async def _load_creds_from_db(db: AsyncSession) -> dict[str, str]:
    """Read Spotify and Qobuz credentials from the Settings table."""
    from app.services.spotify import _decrypt_token

    stmt = select(Setting).where(Setting.key.in_(SETTINGS_TO_LOAD))
    rows = await db.execute(stmt)
    raw: dict[str, str] = {s.key: s.value for s in rows.scalars().all()}

    return {
        "spotify_client_id": raw.get("spotify_client_id", ""),
        "spotify_client_secret": raw.get("spotify_client_secret", ""),
        "qobuz_email": raw.get("qobuz_email", ""),
        "qobuz_password": _decrypt_token(raw.get("qobuz_password_encrypted", "")),
    }


# ---------------------------------------------------------------------------
# Normalization helpers
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

# Key used for deduplication: (source, type, artist_name, title, name)
def _dedup_key(r: SearchResult) -> tuple[str, str, str, str, str]:
    """Return a stable deduplication key for a SearchResult."""
    return (
        r.source,
        r.type,
        (r.artist_name or "").lower(),
        (r.title or "").lower(),
        (r.name or "").lower(),
    )


# ---------------------------------------------------------------------------
# Split-query helper
# ---------------------------------------------------------------------------

def _split_query(query: str) -> tuple[str, str] | None:
    """Split a multi-word query into (artist_part, album_part).

    Returns ``None`` if the query is a single word (no split needed).

    Heuristic: the last word is treated as the album name, all preceding
    words as the artist name.  For example:

        "vince staples summertime" → ("vince staples", "summertime")
        "the beatles abbey road"   → ("the beatles", "abbey road")
        "pink floyd dark side of the moon"
            → ("pink floyd dark side of the", "moon")
    """
    words = query.strip().split()
    if len(words) < 2:
        return None
    artist_part = " ".join(words[:-1])
    album_part = words[-1]
    return artist_part, album_part


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
    query: str, search_type: str, db: AsyncSession
) -> tuple[list[SearchResult], str | None]:
    """Search Spotify via client credentials; returns (results, warning_or_none)."""
    creds = await _load_creds_from_db(db)
    if not creds["spotify_client_id"] or not creds["spotify_client_secret"]:
        return [], "Spotify: client_id/client_secret not configured"

    svc = SpotifyService(
        client_id=creds["spotify_client_id"],
        client_secret=creds["spotify_client_secret"],
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
    query: str, search_type: str, db: AsyncSession
) -> tuple[list[SearchResult], str | None]:
    """Search Qobuz; returns (results, warning_or_none).

    Qobuz only supports album search, so artist/both types fall back to
    album search with a note.
    """
    creds = await _load_creds_from_db(db)
    if not creds["qobuz_email"] or not creds["qobuz_password"]:
        return [], "Qobuz: email/password not configured"

    try:
        svc = QobuzService(
            email=creds["qobuz_email"],
            password=creds["qobuz_password"],
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

    When the query has 2+ words, the search also performs a split query:
    the last word is treated as the album name and the preceding words
    as the artist name.  Results from both searches are merged and
    deduplicated.
    """
    sources = [s.strip().lower() for s in source.split(",") if s.strip()]
    search_type = type.strip().lower()
    if search_type not in ("album", "artist", "both"):
        search_type = "album"

    all_results: list[SearchResult] = []
    warnings: list[str] = []

    # ---- Build the primary search coroutines ----
    coros: list = []
    source_names: list[str] = []

    def _add_source_coros(query: str, label: str = "") -> None:
        """Add search coroutines for a given query string."""
        suffix = f" [{label}]" if label else ""
        if "musicbrainz" in sources:
            coros.append(_search_musicbrainz(query, search_type))
            source_names.append(f"musicbrainz{suffix}")
        if "spotify" in sources:
            coros.append(_search_spotify(query, search_type, db))
            source_names.append(f"spotify{suffix}")
        if "qobuz" in sources:
            coros.append(_search_qobuz(query, search_type, db))
            source_names.append(f"qobuz{suffix}")

    # Primary search: full query as-is
    _add_source_coros(q)

    # Split-query search (only for album or both searches with 2+ words)
    split_parts = _split_query(q)
    if split_parts and search_type in ("album", "both"):
        artist_part, album_part = split_parts
        # Use MusicBrainz artist+release syntax for the split search
        split_query = f'artist:"{artist_part}" AND release:"{album_part}"'
        _add_source_coros(split_query, label="split")
        logger.info("Split query: artist=%r album=%r → %s", artist_part, album_part, split_query)

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

    # Deduplicate by (source, type, artist_name, title, name)
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[SearchResult] = []
    for r in all_results:
        key = _dedup_key(r)
        if key not in seen:
            seen.add(key)
            deduped.append(r)
    all_results = deduped

    # Enrich with library / queue status
    await _enrich_library_status(db, all_results)

    return SearchResponse(query=q, results=all_results, warnings=warnings)


# ---------------------------------------------------------------------------
# Artist albums endpoint
# ---------------------------------------------------------------------------


async def _search_artist_albums_musicbrainz(
    artist_name: str,
) -> tuple[list[SearchResult], str | None]:
    """Search MusicBrainz for all releases by an artist."""
    svc = MusicBrainzService()
    try:
        query = f'artist:"{artist_name}"'
        items = await svc.search(query, "album")
        # Re-normalize: override artist_name to keep query artist consistent
        results: list[SearchResult] = []
        for item in items:
            sr = _normalize_musicbrainz(item, source="musicbrainz")
            sr.artist_name = artist_name
            results.append(sr)
        return results, None
    except Exception as exc:
        logger.warning("MusicBrainz artist-albums search failed: %s", exc)
        return [], f"MusicBrainz: {exc}"
    finally:
        await svc.close()


async def _search_artist_albums_spotify(
    artist_name: str, db: AsyncSession
) -> tuple[list[SearchResult], str | None]:
    """Search Spotify for albums by an artist."""
    creds = await _load_creds_from_db(db)
    if not creds["spotify_client_id"] or not creds["spotify_client_secret"]:
        return [], "Spotify: client_id/client_secret not configured"

    svc = SpotifyService(
        client_id=creds["spotify_client_id"],
        client_secret=creds["spotify_client_secret"],
    )
    try:
        items = await svc.search(f'artist:"{artist_name}"', "album")
        results: list[SearchResult] = []
        for item in items:
            sr = _normalize_spotify(item)
            sr.artist_name = artist_name
            results.append(sr)
        return results, None
    except Exception as exc:
        logger.warning("Spotify artist-albums search failed: %s", exc)
        return [], f"Spotify: {exc}"
    finally:
        await svc.close()


async def _search_artist_albums_qobuz(
    artist_name: str, db: AsyncSession
) -> tuple[list[SearchResult], str | None]:
    """Search Qobuz for albums by an artist."""
    creds = await _load_creds_from_db(db)
    if not creds["qobuz_email"] or not creds["qobuz_password"]:
        return [], "Qobuz: email/password not configured"

    try:
        svc = QobuzService(
            email=creds["qobuz_email"],
            password=creds["qobuz_password"],
        )
    except ValueError as exc:
        return [], f"Qobuz: {exc}"

    try:
        items = await svc.search(artist_name)
        results: list[SearchResult] = []
        for item in items:
            sr = _normalize_qobuz(item)
            sr.artist_name = artist_name
            results.append(sr)
        return results, None
    except Exception as exc:
        logger.warning("Qobuz artist-albums search failed: %s", exc)
        return [], f"Qobuz: {exc}"
    finally:
        await svc.close()


@router.get("/search/artist-albums", response_model=SearchResponse)
async def artist_albums(
    artist_name: str = Query(..., min_length=1, description="Artist name to search for"),
    source: str = Query("musicbrainz", alias="source", description="Comma-separated sources: musicbrainz,spotify,qobuz"),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Search for all albums by a given artist across configured sources.

    Returns a flat list of ``SearchResult`` objects enriched with
    ``in_library`` and ``in_queue`` flags.

    Example: ``GET /api/search/artist-albums?artist_name=Radiohead&source=musicbrainz,spotify``
    """
    sources = [s.strip().lower() for s in source.split(",") if s.strip()]
    all_results: list[SearchResult] = []
    warnings: list[str] = []

    coros: list = []
    source_names: list[str] = []

    if "musicbrainz" in sources:
        coros.append(_search_artist_albums_musicbrainz(artist_name))
        source_names.append("musicbrainz")
    if "spotify" in sources:
        coros.append(_search_artist_albums_spotify(artist_name, db))
        source_names.append("spotify")
    if "qobuz" in sources:
        coros.append(_search_artist_albums_qobuz(artist_name, db))
        source_names.append("qobuz")

    if not coros:
        return SearchResponse(
            query=f"artist:{artist_name}",
            results=[],
            warnings=["No valid sources specified"],
        )

    gathered = await asyncio.gather(*coros, return_exceptions=True)

    for i, result in enumerate(gathered):
        if isinstance(result, Exception):
            warnings.append(f"{source_names[i]}: {result}")
            continue
        items, warn = result
        all_results.extend(items)
        if warn:
            warnings.append(warn)

    # Deduplicate
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[SearchResult] = []
    for r in all_results:
        key = _dedup_key(r)
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    await _enrich_library_status(db, deduped)

    return SearchResponse(
        query=f"artist:{artist_name}",
        results=deduped,
        warnings=warnings,
    )
