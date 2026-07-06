"""Albums router — library album listing and detail."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from httpx import ConnectError, TimeoutException, NetworkError
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.album import Album, AlbumStatus
from app.models.setting import Setting
from app.schemas.album import (
    AlbumResponse,
    AlbumTrackItem,
    AlbumTracksResponse,
    MusicBrainzAlbumResponse,
    MusicBrainzTrackItem,
)
from app.schemas.common import PaginatedResponse

router = APIRouter()

# Supported audio file extensions for filesystem track counting
MUSIC_EXTENSIONS: set[str] = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".wma", ".wav", ".aiff", ".alac"}


def _enrich_track_counts(albums: list[Album], lib_path: Path) -> None:
    """Best-effort: count audio files in each album's folder on disk."""
    for album in albums:
        track_count = 0
        for folder in [
            lib_path / album.artist_name / album.title,
            lib_path / f"{album.artist_name} - {album.title}",
        ]:
            if folder.is_dir():
                try:
                    track_count = sum(
                        1 for f in folder.iterdir()
                        if f.is_file() and f.suffix.lower() in MUSIC_EXTENSIONS
                    )
                    break
                except (PermissionError, OSError):
                    pass
        album.track_count = track_count


# ---------------------------------------------------------------------------
# GET /albums — List library albums (downloaded only)
# ---------------------------------------------------------------------------
@router.get("/albums", response_model=PaginatedResponse[AlbumResponse])
async def list_albums(
    artist: str | None = Query(None, description="Filter by artist name (case-insensitive contains)"),
    search: str | None = Query(None, description="Search title and artist name"),
    sort: str = Query("created_at", description="Sort field; prefix with - for descending"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    min_tracks: int | None = Query(None, description="Minimum track count"),
    max_tracks: int | None = Query(None, description="Maximum track count"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AlbumResponse]:
    """List albums in the library.

    Only returns albums with status=downloaded (the user's library).
    Supports filtering by artist name, free-text search across title
    and artist, sorting, and pagination.
    """
    stmt = select(Album).where(Album.status == AlbumStatus.DOWNLOADED)

    if artist:
        stmt = stmt.where(func.lower(Album.artist_name).contains(artist.lower()))

    if search:
        stmt = stmt.where(
            func.lower(Album.title).contains(search.lower())
            | func.lower(Album.artist_name).contains(search.lower())
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

    # Resolve library path and supported extensions (used in both branches)
    lib_stmt = select(Setting.value).where(Setting.key == "music_library_directory")
    lib_result = await db.execute(lib_stmt)
    lib_path = Path(lib_result.scalar() or "/music/library")

    # -------------------------------------------------------------------
    # When track-count filters are active, we must fetch ALL matching DB
    # rows, enrich with filesystem track counts, filter in memory, and
    # only then paginate.  Otherwise only a fraction of each DB page
    # survives the filter, breaking pagination.
    # -------------------------------------------------------------------
    filter_by_tracks = min_tracks is not None or max_tracks is not None

    if filter_by_tracks:
        # Fetch all matching albums (no pagination)
        result = await db.execute(stmt.order_by(sort_column))
        albums = list(result.scalars().all())

        # Enrich with track counts
        _enrich_track_counts(albums, lib_path)

        # Apply track-count filter
        if min_tracks is not None:
            albums = [a for a in albums if getattr(a, "track_count", 0) >= min_tracks]
        if max_tracks is not None:
            albums = [a for a in albums if getattr(a, "track_count", 0) <= max_tracks]

        # Now paginate the filtered results
        filtered_total = len(albums)
        offset = (page - 1) * limit
        page_albums = albums[offset : offset + limit]

        return PaginatedResponse(
            items=[AlbumResponse.model_validate(a) for a in page_albums],
            total=filtered_total,
            page=page,
            page_size=limit,
            total_pages=max(1, (filtered_total + limit - 1) // limit),
        )

    # -------------------------------------------------------------------
    # No track-count filter — standard DB-level pagination
    # -------------------------------------------------------------------

    # Apply pagination
    offset = (page - 1) * limit
    result = await db.execute(
        stmt.order_by(sort_column).offset(offset).limit(limit)
    )
    albums = list(result.scalars().all())

    # Enrich with track counts from filesystem (best-effort)
    _enrich_track_counts(albums, lib_path)

    total_pages = max(1, (total + limit - 1) // limit)

    return PaginatedResponse(
        items=[AlbumResponse.model_validate(a) for a in albums],
        total=total,
        page=page,
        page_size=limit,
        total_pages=total_pages,
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _find_cover_art(lib_path: Path, artist: str, title: str) -> tuple[Path | None, bytes | None, str | None]:
    """Find cover art for an album. Returns (file_path, image_bytes, mime_type).
    
    Tries in order:
      1. Named cover files (cover.jpg, folder.jpg, etc.)
      2. Any .jpg or .png in the album folder
      3. Embedded art from FLAC files (via mutagen)
    """
    candidates = [
        lib_path / artist / title,
        lib_path / f"{artist} - {title}",
    ]
    
    # Priority cover names
    cover_names = ["cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg", "front.png", "Cover.jpg", "Cover.png"]
    
    for folder in candidates:
        if not folder.is_dir():
            continue
        
        # 1. Try named cover files
        for name in cover_names:
            fp = folder / name
            if fp.is_file():
                return (fp, None, None)
        
        # 2. Try any jpg/png in the folder (alphabetically first)
        try:
            images = sorted([f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png')])
            if images:
                return (images[0], None, None)
        except (PermissionError, OSError):
            pass
        
        # 3. Try embedded art from FLAC files
        try:
            flacs = sorted([f for f in folder.iterdir() if f.is_file() and f.suffix.lower() == '.flac'])
            for flac_file in flacs:
                try:
                    from mutagen.flac import FLAC
                    audio = FLAC(str(flac_file))
                    pictures = audio.pictures
                    if pictures:
                        pic = pictures[0]
                        mime = pic.mime or 'image/jpeg'
                        return (None, pic.data, mime)
                except Exception:
                    continue
        except (PermissionError, OSError):
            pass
    
    return (None, None, None)


# GET /albums/scan - Scan filesystem library directory
# ---------------------------------------------------------------------------
@router.get("/albums/scan", response_model=PaginatedResponse[AlbumResponse])
async def scan_library(
    search: str | None = Query(None, description="Search artist and album name"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(100, ge=1, le=500, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AlbumResponse]:
    """Scan the configured music library directory and return album folders.

    Reads music_library_directory from settings, walks the directory tree,
    and returns album-like entries merged with existing DB records.
    """
    stmt = select(Setting.value).where(Setting.key == "music_library_directory")
    result = await db.execute(stmt)
    lib_path_str = result.scalar() or "/music/library"
    lib_path = Path(lib_path_str)

    if not lib_path.exists():
        return PaginatedResponse(items=[], total=0, page=page, page_size=limit, total_pages=0)

    found: list[dict[str, str]] = []
    music_exts = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".wma", ".wav", ".aiff", ".alac"}

    try:
        for entry in sorted(lib_path.iterdir()):
            if not entry.is_dir():
                continue
            # ArtistName/AlbumName structure
            for sub in sorted(entry.iterdir()):
                if sub.is_dir():
                    try:
                        has_music = any(f.is_file() and f.suffix.lower() in music_exts for f in sub.iterdir())
                    except (PermissionError, OSError):
                        has_music = False
                    if has_music:
                        found.append({"artist_name": entry.name, "title": sub.name, "path": str(sub)})
            # ArtistName - AlbumName structure
            if " - " in entry.name:
                try:
                    has_music = any(f.is_file() and f.suffix.lower() in music_exts for f in entry.iterdir())
                except (PermissionError, OSError):
                    has_music = False
                if has_music:
                    parts = entry.name.split(" - ", 1)
                    found.append({"artist_name": parts[0].strip(), "title": parts[1].strip(), "path": str(entry)})
    except PermissionError:
        pass

    db_stmt = select(Album).where(Album.status == AlbumStatus.DOWNLOADED)
    db_result = await db.execute(db_stmt)
    db_albums = db_result.scalars().all()
    db_keys = {(a.artist_name.lower(), a.title.lower()) for a in db_albums}
    items: list[AlbumResponse] = [AlbumResponse.model_validate(a) for a in db_albums]

    for fs_album in found:
        key = (fs_album["artist_name"].lower(), fs_album["title"].lower())
        if key not in db_keys:
            h = hashlib.md5(fs_album["path"].encode()).hexdigest()
            items.append(AlbumResponse(
                id=uuid.UUID(h), title=fs_album["title"], artist_name=fs_album["artist_name"],
                album_mbid=None, qobuz_id=None, status=AlbumStatus.DOWNLOADED,
                queue_type="watch_folder", reason=fs_album["path"],
                play_count=0, retry_count=0, next_retry_at=None, downloaded_at=None, created_at=datetime.min.replace(tzinfo=timezone.utc),
            ))

    if search:
        s = search.lower()
        items = [a for a in items if s in a.artist_name.lower() or s in a.title.lower()]

    items.sort(key=lambda a: (a.artist_name.lower(), a.title.lower()))
    total = len(items)
    total_pages = max(1, (total + limit - 1) // limit) if total > 0 else 1
    start = (page - 1) * limit
    paged = items[start : start + limit]

    return PaginatedResponse(items=paged, total=total, page=page, page_size=limit, total_pages=total_pages)



# ---------------------------------------------------------------------------
# POST /library/import - Import filesystem albums into DB
# ---------------------------------------------------------------------------
@router.post("/library/import")
async def import_library(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Scan the library directory and create DB records for any album
    not already tracked. Prevents the rule engine from re-downloading
    albums you already own.
    """
    from app.scheduler import do_library_import

    imported = await do_library_import(db)
    if imported:
        print(f"Imported {imported} albums into DB")
    return {"imported": imported, "message": f"Imported {imported} albums"}



# ---------------------------------------------------------------------------
# GET /albums/{album_id}/artwork - Serve cover art from local files
# ---------------------------------------------------------------------------
@router.get("/albums/{album_id}/artwork")
async def get_album_artwork(
    album_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Serve cover art for an album from the local library folder.
    Searches for cover.jpg, folder.jpg, front.jpg, etc. in the album directory.
    Falls back to 404 if no artwork found.
    """
    from fastapi.responses import FileResponse

    # Get library path from settings
    stmt = select(Setting.value).where(Setting.key == "music_library_directory")
    result = await db.execute(stmt)
    lib_path = Path(result.scalar() or "/music/library")

    # Try to find the album in DB first
    album_stmt = select(Album).where(Album.id == album_id)
    album_result = await db.execute(album_stmt)
    album = album_result.scalar_one_or_none()

    if album is not None:
        artist = album.artist_name
        title = album.title
    else:
        # Filesystem-only album with synthetic UUID - can not resolve
        raise HTTPException(status_code=404, detail="Album not found")

    cover_path, embedded_data, embedded_mime = _find_cover_art(lib_path, artist, title)
    
    if embedded_data is not None:
        from fastapi.responses import Response
        return Response(content=embedded_data, media_type=embedded_mime or "image/jpeg")
    
    if cover_path is None:
        # Check artwork cache
        cache_path = Path("data") / "artwork_cache" / f"{album_id}.jpg"
        if cache_path.exists():
            return FileResponse(str(cache_path), media_type="image/jpeg")

        # Try Spotify fallback for cover art
        try:
            import base64, urllib.parse
            cid_r = await db.execute(select(Setting.value).where(Setting.key == "spotify_client_id"))
            cid = cid_r.scalar() or ""
            secret_r = await db.execute(select(Setting.value).where(Setting.key == "spotify_client_secret"))
            csecret = secret_r.scalar() or ""
            if cid and csecret:
                async with httpx.AsyncClient(timeout=15.0) as sc:
                    auth = base64.b64encode(f"{cid}:{csecret}".encode()).decode()
                    tr_r = await sc.post(
                        "https://accounts.spotify.com/api/token",
                        headers={"Authorization": f"Basic {auth}","Content-Type": "application/x-www-form-urlencoded"},
                        data={"grant_type": "client_credentials"},
                    )
                    if tr_r.status_code == 200:
                        token = tr_r.json().get("access_token", "")
                        if token:
                            q = f"album:{title} artist:{artist}"
                            sr_r = await sc.get(
                                f"https://api.spotify.com/v1/search?q={urllib.parse.quote(q)}&type=album&limit=1",
                                headers={"Authorization": f"Bearer {token}"},
                            )
                            if sr_r.status_code == 200:
                                items = sr_r.json().get("albums",{}).get("items",[])
                                if items:
                                    images = items[0].get("images", [])
                                    if images:
                                        img_url = images[0].get("url", "")
                                        if img_url:
                                            img_r = await sc.get(img_url)
                                            if img_r.status_code == 200:
                                                from fastapi.responses import Response
                                                return Response(
                                                    content=img_r.content,
                                                    media_type=img_r.headers.get("content-type", "image/jpeg"),
                                                )
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="No artwork found")

    media_type = "image/jpeg" if cover_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return FileResponse(str(cover_path), media_type=media_type)


# ---------------------------------------------------------------------------
# GET /albums/{album_id}/tracks — List audio files in album folder
# ---------------------------------------------------------------------------
MUSIC_EXTENSIONS = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".wma", ".wav", ".aiff", ".alac"}


def _find_album_folder(lib_path: Path, artist: str, title: str) -> Path | None:
    """Find the album folder on disk, trying common naming patterns."""
    candidates = [
        lib_path / artist / title,
        lib_path / f"{artist} - {title}",
    ]
    for folder in candidates:
        if folder.is_dir():
            return folder
    return None


@router.get("/albums/{album_id}/tracks", response_model=AlbumTracksResponse)
async def get_album_tracks(
    album_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AlbumTracksResponse:
    """List audio files in the album folder on disk."""
    # 1. Find album in DB
    album_stmt = select(Album).where(Album.id == album_id)
    album_result = await db.execute(album_stmt)
    album = album_result.scalar_one_or_none()

    if album is None:
        raise HTTPException(status_code=404, detail=f"Album {album_id} not found")

    # 2. Read library path from settings
    stmt = select(Setting.value).where(Setting.key == "music_library_directory")
    result = await db.execute(stmt)
    lib_path = Path(result.scalar() or "/music/library")

    # 3. Find the album folder
    folder = _find_album_folder(lib_path, album.artist_name, album.title)

    if folder is None:
        return AlbumTracksResponse(
            album_id=album.id,
            artist=album.artist_name,
            title=album.title,
            folder_path=None,
            tracks=[],
            track_count=0,
        )

    # 4. List audio files
    tracks: list[AlbumTrackItem] = []
    try:
        for f in sorted(folder.iterdir()):
            if f.is_file() and f.suffix.lower() in MUSIC_EXTENSIONS:
                tracks.append(AlbumTrackItem(
                    filename=f.name,
                    size=f.stat().st_size,
                    format=f.suffix.lower().lstrip("."),
                    path=str(f),
                ))
    except (PermissionError, OSError):
        pass

    return AlbumTracksResponse(
        album_id=album.id,
        artist=album.artist_name,
        title=album.title,
        folder_path=str(folder),
        tracks=tracks,
        track_count=len(tracks),
    )


# ---------------------------------------------------------------------------
# GET /albums/{album_id}/musicbrainz — Look up expected track listing
# ---------------------------------------------------------------------------
@router.get("/albums/{album_id}/musicbrainz", response_model=MusicBrainzAlbumResponse)
async def get_album_musicbrainz(
    album_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MusicBrainzAlbumResponse:
    """Get the expected track listing from MusicBrainz for comparison."""
    # 1. Find album in DB
    album_stmt = select(Album).where(Album.id == album_id)
    album_result = await db.execute(album_stmt)
    album = album_result.scalar_one_or_none()

    if album is None:
        raise HTTPException(status_code=404, detail=f"Album {album_id} not found")

    mb_failed = False

    # 2. Query MusicBrainz
    from app.services.musicbrainz import MusicBrainzService

    mb_service = MusicBrainzService()
    mb_failed = False

    try:
        if album.album_mbid:
            # Direct lookup by MBID
            release_tracks = await mb_service.get_release_tracks(album.album_mbid)
            tracks = [
                MusicBrainzTrackItem(
                    position=t["position"],
                    title=t["title"],
                    length_ms=t["length_ms"],
                    mbid=t["id"],
                )
                for t in release_tracks
            ]
            return MusicBrainzAlbumResponse(
                found=True,
                mbid=album.album_mbid,
                title=album.title,
                artist=album.artist_name,
                tracks=tracks,
                track_count=len(tracks),
            )
        else:
            # Search by artist + title
            result = await mb_service.get_album_tracklist(
                album.artist_name, album.title
            )
            if result is None:
                mb_failed = True
            else:
                tracks = [
                    MusicBrainzTrackItem(
                        position=t["position"],
                        title=t["title"],
                        length_ms=t["length_ms"],
                        mbid=t["id"],
                    )
                    for t in result["tracks"]
                ]
                return MusicBrainzAlbumResponse(
                    found=True,
                    mbid=result["mbid"],
                    title=result["title"],
                    artist=result["artist"],
                    tracks=tracks,
                    track_count=result["track_count"],
                )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            mb_failed = True
        elif exc.response.status_code == 503:
            raise HTTPException(
                status_code=503,
                detail="MusicBrainz is currently unavailable. Please try again later.",
            )
        else:
            raise HTTPException(
                status_code=502,
                detail=f"MusicBrainz API error: {exc.response.status_code}",
            )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError):
        mb_failed = True
    finally:
        await mb_service.close()

    # 3. Fallback: try Spotify if MusicBrainz failed or returned no results
    if mb_failed:
        spotify_result = None
        try:
            import base64, urllib.parse

            # Read Spotify client credentials from settings
            cid_result = await db.execute(select(Setting.value).where(Setting.key == "spotify_client_id"))
            cid = cid_result.scalar() or ""
            secret_result = await db.execute(select(Setting.value).where(Setting.key == "spotify_client_secret"))
            csecret = secret_result.scalar() or ""

            if cid and csecret:
                # Get a client-credentials token (doesn't need user OAuth)
                async with httpx.AsyncClient(timeout=15.0) as spotify_client:
                    auth_header = base64.b64encode(f"{cid}:{csecret}".encode()).decode()
                    token_resp = await spotify_client.post(
                        "https://accounts.spotify.com/api/token",
                        data={"grant_type": "client_credentials"},
                        headers={
                            "Authorization": f"Basic {auth_header}",
                            "Content-Type": "application/x-www-form-urlencoded",
                        },
                    )
                    if token_resp.status_code != 200:
                        raise ValueError(f"Spotify auth failed: {token_resp.status_code}")

                    token_data = token_resp.json()
                    access_token = token_data.get("access_token", "")

                    if access_token:
                        # Search for the album
                        query = f"album:{album.title} artist:{album.artist_name}"
                        url = f"https://api.spotify.com/v1/search?q={urllib.parse.quote(query)}&type=album&limit=1"
                        resp = await spotify_client.get(
                            url,
                            headers={"Authorization": f"Bearer {access_token}"},
                        )
                        if resp.status_code == 200:
                            search_data = resp.json()
                            albums = search_data.get("albums", {}).get("items", [])
                            if albums:
                                spotify_album = albums[0]
                                tracks_url = spotify_album["href"] + "/tracks?limit=50"
                                track_resp = await spotify_client.get(
                                    tracks_url,
                                    headers={"Authorization": f"Bearer {access_token}"},
                                )
                                if track_resp.status_code == 200:
                                    track_data = track_resp.json()
                                    spotify_result = [
                                        MusicBrainzTrackItem(
                                            position=t.get("track_number", i),
                                            title=t.get("name", ""),
                                            length_ms=t.get("duration_ms", 0),
                                            mbid="",
                                        )
                                        for i, t in enumerate(track_data.get("items", []), 1)
                                    ]
        except Exception:
            pass

        if spotify_result:
            return MusicBrainzAlbumResponse(
                found=True,
                mbid=None,
                title=album.title,
                artist=album.artist_name,
                tracks=spotify_result,
                track_count=len(spotify_result),
                source="spotify",
            )

    # 4. Neither MusicBrainz nor Spotify found anything
    return MusicBrainzAlbumResponse(
        found=False,
        mbid=None,
        title=None,
        artist=None,
        tracks=[],
        track_count=0,
        source="spotify",  # tried both, neither found
    )


# GET /albums/{album_id} — Single album detail
# ---------------------------------------------------------------------------
@router.get("/albums/{album_id}", response_model=AlbumResponse)
async def get_album(
    album_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> AlbumResponse:
    """Get a single album by ID."""
    result = await db.execute(select(Album).where(Album.id == album_id))
    album = result.scalar_one_or_none()
    if album is None:
        raise HTTPException(status_code=404, detail=f"Album {album_id} not found")
    return AlbumResponse.model_validate(album)


# ---------------------------------------------------------------------------
# Bulk delete
# ---------------------------------------------------------------------------

class BulkDeleteRequest(BaseModel):
    album_ids: list[uuid.UUID]
    delete_files: bool = False


@router.post("/library/bulk-delete")
async def bulk_delete_library(
    body: BulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete multiple albums from the library.

    Removes DB records and optionally deletes files from disk.
    """
    deleted = 0
    errors: list[str] = []

    for album_id in body.album_ids:
        album = await db.get(Album, album_id)
        if album is None:
            errors.append(f"Album {album_id} not found")
            continue

        # Optionally delete files
        if body.delete_files:
            lib_stmt = select(Setting.value).where(Setting.key == "music_library_directory")
            lib_result = await db.execute(lib_stmt)
            lib_path = Path(lib_result.scalar() or "/music/library")

            for folder in [
                lib_path / album.artist_name / album.title,
                lib_path / f"{album.artist_name} - {album.title}",
            ]:
                if folder.is_dir():
                    try:
                        shutil.rmtree(str(folder))
                    except Exception as e:
                        errors.append(f"Failed to delete files for {album.title}: {e}")

        await db.delete(album)
        deleted += 1

    await db.commit()
    return {"deleted": deleted, "errors": errors}
