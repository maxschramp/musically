"""APScheduler job definitions for periodic sync tasks."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.database
from app.config import get_settings
from app.models.album import Album, AlbumStatus
from app.models.setting import Setting
from app.services.sync_orchestrator import SyncOrchestrator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared library import logic (used by both the scheduled job and the API endpoint)
# ---------------------------------------------------------------------------

MUSIC_EXTENSIONS: set[str] = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".wma", ".wav", ".aiff", ".alac"}


async def do_library_import(db: AsyncSession) -> int:
    """Scan the configured music library directory and create DB records
    for any album not already tracked.

    Returns the number of newly imported albums.
    """
    result = await db.execute(select(Setting.value).where(Setting.key == "music_library_directory"))
    lib_path_str = result.scalar() or "/music/library"
    lib_path = Path(lib_path_str)

    if not lib_path.exists():
        logger.warning("Library import: directory not found: %s", lib_path)
        return 0

    found: list[dict[str, str]] = []
    try:
        for entry in sorted(lib_path.iterdir()):
            if not entry.is_dir():
                continue
            # ArtistName/AlbumName structure
            for sub in sorted(entry.iterdir()):
                if sub.is_dir():
                    try:
                        has_music = any(
                            f.is_file() and f.suffix.lower() in MUSIC_EXTENSIONS
                            for f in sub.iterdir()
                        )
                    except (PermissionError, OSError):
                        has_music = False
                    if has_music:
                        found.append({"artist_name": entry.name, "title": sub.name, "path": str(sub)})
            # ArtistName - AlbumName structure
            if " - " in entry.name:
                try:
                    has_music = any(
                        f.is_file() and f.suffix.lower() in MUSIC_EXTENSIONS
                        for f in entry.iterdir()
                    )
                except (PermissionError, OSError):
                    has_music = False
                if has_music:
                    parts = entry.name.split(" - ", 1)
                    found.append({"artist_name": parts[0].strip(), "title": parts[1].strip(), "path": str(entry)})
    except PermissionError:
        pass

    # Get existing DB keys
    db_stmt = select(Album)
    db_result = await db.execute(db_stmt)
    db_albums = db_result.scalars().all()
    db_keys = {(a.artist_name.lower(), a.title.lower()) for a in db_albums}

    imported = 0
    for fs_album in found:
        artist_name = fs_album["artist_name"]
        album_title = fs_album["title"]
        key = (artist_name.lower(), album_title.lower())
        if key not in db_keys:
            existing_stmt = select(Album).where(
                func.lower(Album.artist_name) == artist_name.lower(),
                func.lower(Album.title) == album_title.lower(),
            )
            existing = (await db.execute(existing_stmt)).scalar()
            if existing is not None:
                db_keys.add(key)
                continue

            album = Album(
                title=album_title,
                artist_name=artist_name,
                status=AlbumStatus.DOWNLOADED,
                queue_type="watch_folder",
                reason=f"Imported from library: {fs_album['path']}",
                play_count=0,
            )
            db.add(album)
            db_keys.add(key)
            imported += 1

    if imported:
        await db.commit()

    return imported


# ---------------------------------------------------------------------------
# Scheduled job: periodic library import
# ---------------------------------------------------------------------------

async def run_library_import_job() -> None:
    """Scheduled job: scan the library directory and import any new albums.

    Runs on a configurable interval. Only imports albums that are not
    already tracked in the database. Safe to run frequently — it's
    idempotent.
    """
    try:
        async with app.database.async_session_factory() as db:
            imported = await do_library_import(db)
            if imported:
                logger.info("Library import: %d new albums imported", imported)
    except Exception:
        logger.exception("Library import job failed")


async def run_sync_job() -> None:
    """Scheduled job: create an orchestrator and run a full sync cycle.

    This function is intended to be called by APScheduler on a cron/interval
    trigger. It creates its own DB session and handles all errors gracefully
    so a failed sync never crashes the scheduler.
    """
    try:
        settings = get_settings()
        orchestrator = SyncOrchestrator(
            db_session_factory=app.database.async_session_factory,
            settings=settings,
        )
        result = await orchestrator.run_sync()
        logger.info(
            "Scheduled sync finished: status=%s tracks_fetched=%d tracks_new=%d",
            result.status,
            result.tracks_fetched,
            result.tracks_new,
        )
    except Exception:
        logger.exception("Scheduled sync job failed with an unhandled exception.")


async def run_mb_enrichment_job() -> None:
    import asyncio
    from app.services.musicbrainz import MusicBrainzService
    from app.models.album import Album
    from sqlalchemy import select
    BATCH_SIZE = 10
    DELAY = 1.5
    try:
        mb = MusicBrainzService()
        async with app.database.async_session_factory() as db:
            stmt = select(Album).where(Album.album_mbid.is_(None), Album.status == 'downloaded').limit(BATCH_SIZE)
            result = await db.execute(stmt)
            albums = result.scalars().all()
            if not albums:
                await mb.close()
                return
            enriched = 0
            for a in albums:
                try:
                    r = await mb.search_album(a.artist_name, a.title)
                    if r:
                        a.album_mbid = r.get('id', '')
                        db.add(a)
                        enriched += 1
                    await asyncio.sleep(DELAY)
                except Exception:
                    await asyncio.sleep(DELAY)
            if enriched:
                await db.commit()
        await mb.close()
    except Exception:
        pass


def _compress_image(data: bytes, max_size: int = 300) -> bytes:
    """Resize and compress image to ~200KB for thumbnails."""
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(data))
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.LANCZOS)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        out = BytesIO()
        img.save(out, 'JPEG', quality=75, optimize=True)
        return out.getvalue()
    except Exception:
        return data  # return original if compression fails


async def run_artwork_cache_job() -> None:
    """Pre-fetch and compress artwork for downloaded and queued albums.

    For DOWNLOADED albums: reads local cover art, compresses, caches.
    For QUEUED albums: fetches from Spotify, compresses, caches.
    """
    import asyncio, base64, urllib.parse
    from pathlib import Path
    from app.models.album import Album, AlbumStatus
    from app.models.setting import Setting
    from app.routers.albums import _find_cover_art
    from sqlalchemy import select

    BATCH_SIZE = 5
    DELAY = 2.0  # seconds between albums

    try:
        async with app.database.async_session_factory() as db:
            cache_dir = Path("data") / "artwork_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)

            # Get library path for local artwork lookups
            lib_r = await db.execute(select(Setting.value).where(Setting.key == "music_library_directory"))
            lib_path = Path(lib_r.scalar() or "/music/library")

            # Process both DOWNLOADED (local art) and QUEUED (Spotify art) albums
            stmt = select(Album).where(
                Album.status.in_([AlbumStatus.DOWNLOADED, AlbumStatus.QUEUED])
            ).limit(BATCH_SIZE)
            result = await db.execute(stmt)
            albums = result.scalars().all()

            if not albums:
                return

            # Get Spotify credentials (needed for QUEUED albums)
            cid_r = await db.execute(select(Setting.value).where(Setting.key == "spotify_client_id"))
            cid = cid_r.scalar() or ""
            secret_r = await db.execute(select(Setting.value).where(Setting.key == "spotify_client_secret"))
            csecret = secret_r.scalar() or ""

            cached = 0
            for album in albums:
                cache_path = cache_dir / f"{album.id}.jpg"
                if cache_path.exists():
                    continue  # already cached

                try:
                    if album.status == AlbumStatus.DOWNLOADED:
                        # Try to get local artwork
                        cover_path, embedded_data, _embedded_mime = _find_cover_art(
                            lib_path, album.artist_name, album.title
                        )
                        if embedded_data:
                            compressed = _compress_image(embedded_data)
                            cache_path.write_bytes(compressed)
                            cached += 1
                            logger.debug("Cached local artwork for %s - %s", album.artist_name, album.title)
                        elif cover_path and cover_path.exists():
                            raw = cover_path.read_bytes()
                            compressed = _compress_image(raw)
                            cache_path.write_bytes(compressed)
                            cached += 1
                            logger.debug("Cached local artwork for %s - %s", album.artist_name, album.title)

                    elif album.status == AlbumStatus.QUEUED:
                        if not cid or not csecret:
                            continue

                        import httpx
                        async with httpx.AsyncClient(timeout=15.0) as client:
                            # Get Spotify token
                            auth = base64.b64encode(f"{cid}:{csecret}".encode()).decode()
                            token_r = await client.post(
                                "https://accounts.spotify.com/api/token",
                                headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
                                data={"grant_type": "client_credentials"},
                            )
                            if token_r.status_code != 200:
                                continue
                            token = token_r.json().get("access_token", "")
                            if not token:
                                continue

                            # Search album
                            q = f"album:{album.title} artist:{album.artist_name}"
                            url = f"https://api.spotify.com/v1/search?q={urllib.parse.quote(q)}&type=album&limit=1"
                            sr = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                            if sr.status_code != 200:
                                continue
                            items = sr.json().get("albums", {}).get("items", [])
                            if not items:
                                continue
                            images = items[0].get("images", [])
                            if not images:
                                continue
                            img_url = images[0].get("url", "")
                            if not img_url:
                                continue

                            # Download, compress, and cache
                            img_r = await client.get(img_url)
                            if img_r.status_code == 200:
                                compressed = _compress_image(img_r.content)
                                cache_path.write_bytes(compressed)
                                cached += 1
                                logger.debug("Cached Spotify artwork for %s - %s", album.artist_name, album.title)

                except Exception:
                    pass

                await asyncio.sleep(DELAY)

            if cached:
                logger.info("Artwork cache: %d/%d albums cached", cached, len(albums))

    except Exception:
        logger.exception("Artwork cache job failed")


async def run_download_dispatcher() -> None:
    """Pick up auto-queued albums and dispatch them for download.

    Processes up to 3 albums per run.  Tries the Celery worker first
    (if a worker container is running), otherwise runs the download
    pipeline directly in-process.
    """
    try:
        from app.models.album import Album, AlbumStatus, QueueType
        from sqlalchemy import select

        # Check whether a Celery worker is actually available
        celery_available = False
        try:
            from app.celery_app import celery_app
            workers = celery_app.control.ping(timeout=2.0)
            celery_available = bool(workers)
        except Exception:
            celery_available = False

        BATCH_SIZE = 3

        async with app.database.async_session_factory() as db:
            # -------------------------------------------------------------------
            # Reset albums stuck in 'downloading' for > 30 minutes
            # -------------------------------------------------------------------
            stuck_cutoff = datetime.utcnow() - timedelta(minutes=30)
            stuck_stmt = (
                select(Album)
                .where(
                    Album.status == AlbumStatus.DOWNLOADING,
                    Album.created_at < stuck_cutoff,
                )
                .limit(5)
            )
            stuck_result = await db.execute(stuck_stmt)
            stuck_albums = stuck_result.scalars().all()
            for album in stuck_albums:
                album.status = AlbumStatus.QUEUED
                album.retry_count = 0
                logger.warning(
                    "Reset stuck download: %s - %s",
                    album.artist_name,
                    album.title,
                )
            if stuck_albums:
                await db.commit()

            # -------------------------------------------------------------------
            # Pick up queued auto albums for dispatch
            # -------------------------------------------------------------------
            stmt = (
                select(Album)
                .where(
                    Album.status == AlbumStatus.QUEUED,
                    Album.queue_type == QueueType.AUTO,
                )
                .order_by(Album.created_at.asc())
                .limit(BATCH_SIZE)
            )
            result = await db.execute(stmt)
            albums = result.scalars().all()

            if not albums:
                return

            for album in albums:
                if celery_available:
                    try:
                        from app.services.downloader import download_album_task
                        download_album_task.delay(str(album.id))
                        logger.info(
                            "Dispatched download for %s - %s (Celery)",
                            album.artist_name,
                            album.title,
                        )
                        continue
                    except Exception:
                        logger.warning(
                            "Celery dispatch failed, falling back to direct for %s - %s",
                            album.artist_name,
                            album.title,
                        )

                # No Celery worker — run the pipeline directly
                logger.info(
                    "Running download directly for %s - %s",
                    album.artist_name,
                    album.title,
                )
                try:
                    from app.services.downloader import _build_pipeline_async
                    pipeline = await _build_pipeline_async()
                    pipeline_result = await pipeline.process_album(album.id)
                    if pipeline_result.success:
                        logger.info(
                            "Download complete: %s - %s",
                            album.artist_name,
                            album.title,
                        )
                    else:
                        logger.warning(
                            "Download failed: %s - %s: %s",
                            album.artist_name,
                            album.title,
                            pipeline_result.message,
                        )
                    await pipeline.qobuz.close()
                    await pipeline.notifier.close()
                except Exception as inner:
                    logger.exception(
                        "Direct download failed for %s - %s",
                        album.artist_name,
                        album.title,
                    )

    except Exception:
        logger.exception("Download dispatcher failed")


async def run_cleanup_job() -> None:
    """Scheduled job: clean up stale downloads, old artwork cache, and orphaned temp files."""
    try:
        from app.services.cleanup import CleanupService
        from app.constants import DEFAULT_SETTINGS

        downloads_dir = DEFAULT_SETTINGS.get("qobuz_temp_download_directory", "/downloads")
        cache_dir = "data/artwork_cache"

        cleaner = CleanupService(
            db_session_factory=app.database.async_session_factory,
            downloads_dir=downloads_dir,
            cache_dir=cache_dir,
        )
        result = await cleaner.run_all()
        logger.info(
            "Cleanup finished: empty_dirs=%d cache_files=%d stalled_dirs=%d",
            result.get("empty_dirs_removed", 0),
            result.get("cache_files_removed", 0),
            result.get("stalled_dirs_removed", 0),
        )
    except Exception:
        logger.exception("Cleanup job failed.")
