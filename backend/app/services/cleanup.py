"""Cleanup service for stale download directories, artwork cache, and orphaned temp files."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.album import Album, AlbumStatus

logger = logging.getLogger(__name__)


class CleanupService:
    """Cleans up stale download directories, old artwork cache, and orphaned temp files."""

    def __init__(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        downloads_dir: str = "/downloads",
        cache_dir: str = "data/artwork_cache",
    ) -> None:
        self._db_session_factory = db_session_factory
        self._downloads_dir = Path(downloads_dir)
        self._cache_dir = Path(cache_dir)

    async def cleanup_downloads(self) -> int:
        """Remove empty directories from the downloads staging area.

        Only removes directories that contain NO files (all files already
        moved by beets).  Directories that still have files are left alone
        (download may still be in progress).

        Returns count of directories removed.
        """
        removed = 0
        downloads = self._downloads_dir

        if not downloads.exists() or not downloads.is_dir():
            logger.debug("Downloads directory does not exist: %s", downloads)
            return 0

        for child in downloads.iterdir():
            if not child.is_dir():
                continue
            try:
                # Only remove if the directory contains no files at all
                # (ignore empty subdirectories — beets moves all files out)
                has_files = any(p.is_file() for p in child.rglob("*") if p.is_file())
                if not has_files:
                    shutil.rmtree(child)
                    removed += 1
                    logger.info("Removed empty download directory: %s", child)
            except OSError:
                logger.exception("Failed to remove directory: %s", child)

        return removed

    async def cleanup_artwork_cache(self, max_age_days: int = 30) -> int:
        """Remove artwork cache files older than *max_age_days*.

        Returns count of files removed.
        """
        removed = 0
        cache = self._cache_dir

        if not cache.exists() or not cache.is_dir():
            logger.debug("Artwork cache directory does not exist: %s", cache)
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        for child in cache.iterdir():
            if not child.is_file():
                continue
            try:
                mtime = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    child.unlink()
                    removed += 1
                    logger.info("Removed old artwork cache file: %s (mtime=%s)", child.name, mtime.isoformat())
            except OSError:
                logger.exception("Failed to remove cache file: %s", child)

        return removed

    async def cleanup_stalled_temp_dirs(self) -> int:
        """Remove temp download directories for albums that are already
        downloaded or rejected (no longer need the temp files).

        Checks the database for albums with ``status=downloaded`` or
        ``status=rejected`` and removes the corresponding temp directory
        at ``downloads_dir/<album_id>`` if it exists.

        Returns count of directories removed.
        """
        removed = 0
        downloads = self._downloads_dir

        if not downloads.exists() or not downloads.is_dir():
            logger.debug("Downloads directory does not exist: %s", downloads)
            return 0

        try:
            async with self._db_session_factory() as db:
                stmt = select(Album.id).where(
                    Album.status.in_([AlbumStatus.DOWNLOADED, AlbumStatus.REJECTED])
                )
                result = await db.execute(stmt)
                album_ids = [str(row[0]) for row in result.all()]

            for album_id in album_ids:
                temp_dir = downloads / album_id
                if temp_dir.exists() and temp_dir.is_dir():
                    try:
                        shutil.rmtree(temp_dir)
                        removed += 1
                        logger.info("Removed stalled temp directory for album %s: %s", album_id, temp_dir)
                    except OSError:
                        logger.exception("Failed to remove stalled temp directory: %s", temp_dir)

        except Exception:
            logger.exception("Failed to query albums for stalled temp dir cleanup")

        return removed

    async def run_all(self) -> dict[str, int]:
        """Run all cleanup tasks and return summary."""
        logger.info("Starting cleanup cycle...")

        empty_dirs = await self.cleanup_downloads()
        cache_files = await self.cleanup_artwork_cache()
        stalled_dirs = await self.cleanup_stalled_temp_dirs()

        summary: dict[str, int] = {
            "empty_dirs_removed": empty_dirs,
            "cache_files_removed": cache_files,
            "stalled_dirs_removed": stalled_dirs,
        }

        logger.info(
            "Cleanup cycle complete: empty_dirs=%d cache_files=%d stalled_dirs=%d",
            empty_dirs,
            cache_files,
            stalled_dirs,
        )

        return summary
