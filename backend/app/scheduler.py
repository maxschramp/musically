"""APScheduler job definitions for periodic sync tasks."""

from __future__ import annotations

import logging

import app.database
from app.config import get_settings
from app.services.sync_orchestrator import SyncOrchestrator

logger = logging.getLogger(__name__)


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

    Processes 1 album per run to avoid overwhelming Qobuz. The Celery
    worker handles the actual download (if running); otherwise we call
    the pipeline directly.
    """
    try:
        from app.models.album import Album, AlbumStatus, QueueType
        from sqlalchemy import select

        async with app.database.async_session_factory() as db:
            # Find one auto-queued album ready for download
            stmt = select(Album).where(
                Album.status == AlbumStatus.QUEUED,
                Album.queue_type == QueueType.AUTO,
            ).order_by(Album.created_at.asc()).limit(1)
            result = await db.execute(stmt)
            album = result.scalar_one_or_none()

            if album is None:
                return

            # Try Celery first, fall back to direct call
            try:
                from app.services.downloader import download_album_task
                download_album_task.delay(str(album.id))
                logger.info("Dispatched download for %s - %s (Celery)", album.artist_name, album.title)
            except Exception:
                # Celery/Redis not available — run directly
                logger.info("Celery unavailable, running download directly for %s - %s", album.artist_name, album.title)
                try:
                    from app.services.downloader import _build_pipeline_async
                    pipeline = await _build_pipeline_async()
                    result = await pipeline.process_album(album.id)
                    if result.success:
                        logger.info("Download complete: %s - %s", album.artist_name, album.title)
                    else:
                        logger.warning("Download failed: %s - %s: %s", album.artist_name, album.title, result.message)
                    await pipeline.qobuz.close()
                    await pipeline.notifier.close()
                except Exception as inner:
                    logger.exception("Direct download failed for %s - %s", album.artist_name, album.title)

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
