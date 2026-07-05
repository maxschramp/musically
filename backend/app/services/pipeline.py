"""Download pipeline — orchestrates Qobuz download → beets import → notification.

This module contains the core pipeline logic, callable from both Celery tasks
and synchronous code. It is NOT a Celery task itself — see downloader.py for
the Celery task wrapper.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.album import Album, AlbumStatus, QueueType
from app.models.artist import Artist
from app.models.setting import Setting
from app.services.beets import BeetsService
from app.services.event_bus import event_bus
from app.services.notifications import NotificationService
from app.services.qobuz import QobuzService
from app.services.tagger import TaggerService

logger = logging.getLogger(__name__)

# Default stalled retry intervals (hours): 24h, 3d, 7d, 14d
DEFAULT_RETRY_INTERVALS = [24, 72, 168, 336]


def _utcnow() -> datetime:
    """Return the current UTC time as a naive datetime.

    PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns reject timezone-aware
    datetimes via asyncpg.  This helper strips the tzinfo so writes succeed.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class PipelineResult:
    """Result of processing a single album through the download pipeline."""
    album_id: uuid.UUID
    success: bool
    status: AlbumStatus = AlbumStatus.QUEUED
    message: str = ""
    qobuz_album_id: str | None = None
    files_downloaded: int = 0
    files_imported: int = 0
    errors: list[str] = field(default_factory=list)


class DownloadPipeline:
    """Orchestrates the full download → tag → notify pipeline for an album.

    This is the core business logic, callable from both Celery tasks
    and the sync orchestrator. It manages:
      1. Album status transitions
      2. Qobuz search and download
      3. beets tagging and import
      4. Artist library count updates
      5. Discord notifications
      6. Retry scheduling for stalled albums
    """

    def __init__(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        qobuz: QobuzService | None = None,
        beets: BeetsService | None = None,
        notifier: NotificationService | None = None,
        settings: dict[str, str] | None = None,
    ) -> None:
        self.db_session_factory = db_session_factory
        self.qobuz = qobuz
        self.beets = beets
        self.notifier = notifier
        self.tagger = TaggerService()
        self._settings = settings or {}

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------
    async def _get_setting(self, db: AsyncSession, key: str, default: str = "") -> str:
        """Read a setting value from the database."""
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()
        if setting is not None:
            return setting.value
        return self._settings.get(key, default)

    async def _get_setting_bool(self, db: AsyncSession, key: str, default: bool = True) -> bool:
        val = await self._get_setting(db, key, "true" if default else "false")
        return val.lower() in ("true", "1", "yes")

    def _get_retry_intervals(self) -> list[int]:
        """Parse stalled_retry_intervals_hours from settings, falling back to defaults."""
        raw = self._settings.get("stalled_retry_intervals_hours", "")
        if not raw:
            return DEFAULT_RETRY_INTERVALS
        try:
            intervals = json.loads(raw)
            if isinstance(intervals, list) and all(isinstance(i, (int, float)) for i in intervals):
                return [int(i) for i in intervals]
        except (json.JSONDecodeError, TypeError):
            pass
        return DEFAULT_RETRY_INTERVALS

    def schedule_retry(self, retry_count: int) -> datetime:
        """Calculate next_retry_at based on retry_count and configured intervals.

        Uses stalled_retry_intervals_hours (e.g. [24, 72, 168, 336]).
        If retry_count exceeds the list length, the last interval is reused.
        """
        intervals = self._get_retry_intervals()
        idx = min(retry_count, len(intervals) - 1)
        hours = intervals[idx]
        return datetime.now(timezone.utc) + timedelta(hours=hours)

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------
    async def process_album(self, album_id: uuid.UUID) -> PipelineResult:
        """Process a single album through the full download pipeline.

        Steps:
          1. Load album from DB
          2. Set status → downloading
          3. Search Qobuz for the album
          4. Download FLACs to temp directory
          5. Run beets import
          6. Update status → downloaded
          7. Update artist library count
          8. Send Discord notification
          9. Clean up temp directory

        On failure at any step:
          - Set status → stalled
          - Schedule retry
          - Notify error

        Requires ``self.qobuz`` to be set (raises :exc:`RuntimeError` otherwise).
        """
        if self.qobuz is None:
            raise RuntimeError(
                "QobuzService is required for process_album; "
                "use process_watch_folder_album for watch folder items"
            )
        if self.beets is None:
            raise RuntimeError("BeetsService is required for process_album")
        if self.notifier is None:
            raise RuntimeError("NotificationService is required for process_album")

        async with self.db_session_factory() as db:
            try:
                # Step 1: Load album
                result_stmt = await db.execute(select(Album).where(Album.id == album_id))
                album = result_stmt.scalar_one_or_none()
                if album is None:
                    return PipelineResult(
                        album_id=album_id,
                        success=False,
                        message=f"Album {album_id} not found",
                    )

                # Read notification settings
                notify_download = await self._get_setting_bool(db, "notify_on_download")
                notify_stalled = await self._get_setting_bool(db, "notify_on_stalled")
                notify_error = await self._get_setting_bool(db, "notify_on_error")

                # Step 2: Set status → downloading
                album.status = AlbumStatus.DOWNLOADING
                album.retry_count += 1
                await db.commit()

                event_bus.publish("album_status", {"album_id": str(album_id), "status": "downloading"})

                temp_dir = await self._get_setting(db, "qobuz_temp_download_directory", "/downloads")
                dest_path = Path(temp_dir) / str(album_id)

                # Step 3: Search Qobuz
                qobuz_album = await self.qobuz.search_album_with_tracks(
                    album.artist_name, album.title
                )

                if qobuz_album is None:
                    # Not found on Qobuz → stall
                    album.status = AlbumStatus.STALLED
                    album.next_retry_at = self.schedule_retry(album.retry_count)
                    await db.commit()

                    event_bus.publish("album_status", {"album_id": str(album_id), "status": "stalled", "reason": "Not found on Qobuz"})

                    if notify_stalled:
                        await self.notifier.notify_stalled(
                            album_title=album.title,
                            artist_name=album.artist_name,
                            reason="Not found on Qobuz",
                            retry_count=album.retry_count,
                            next_retry_at=album.next_retry_at.isoformat() if album.next_retry_at else None,
                        )

                    return PipelineResult(
                        album_id=album_id,
                        success=False,
                        status=AlbumStatus.STALLED,
                        message="Album not found on Qobuz",
                    )

                # Store Qobuz ID
                album.qobuz_id = qobuz_album.qobuz_id
                await db.commit()

                # Step 4: Download FLACs
                download_ok = await self.qobuz.download_album(
                    qobuz_album.qobuz_id, dest_path
                )

                if not download_ok:
                    album.status = AlbumStatus.STALLED
                    album.next_retry_at = self.schedule_retry(album.retry_count)
                    await db.commit()

                    event_bus.publish("album_status", {"album_id": str(album_id), "status": "stalled", "reason": "Download failed"})

                    if notify_error:
                        await self.notifier.notify_error(
                            "Download failed",
                            f"{album.artist_name} — {album.title}",
                        )

                    # Clean up temp dir on download failure (no files to review)
                    if dest_path.exists():
                        try:
                            shutil.rmtree(str(dest_path))
                            logger.info("Cleaned up temp dir after download failure: %s", dest_path)
                        except Exception:
                            logger.warning("Failed to clean up temp dir: %s", dest_path)

                    return PipelineResult(
                        album_id=album_id,
                        success=False,
                        status=AlbumStatus.STALLED,
                        message="Download failed",
                        qobuz_album_id=qobuz_album.qobuz_id,
                    )

                # Step 4.5: Tag FLAC files with metadata
                logger.info(
                    "Tagging FLAC files for %s - %s (%d tracks)",
                    album.artist_name, album.title, len(qobuz_album.tracks),
                )
                tagged_count = await self.tagger.tag_album(
                    album_dir=str(dest_path),
                    artist=album.artist_name,
                    album=album.title,
                    tracks=[
                        {"track_number": t.track_number, "title": t.title, "isrc": t.isrc}
                        for t in qobuz_album.tracks
                    ],
                )
                logger.info(
                    "Tagged %d FLAC files for %s - %s",
                    tagged_count, album.artist_name, album.title,
                )

                # Step 5: Run beets import
                music_library = await self._get_setting(db, "music_library_directory", "/music/library")
                beets_result = await self.beets.import_album(
                    source_dir=str(dest_path),
                    dest_base=music_library,
                    move=False,  # copy mode, safer for NAS
                )

                if not beets_result.success:
                    album.reason = f"[REVIEW] beets import failed: {'; '.join(beets_result.errors[:3])}"
                    album.status = AlbumStatus.STALLED
                    album.next_retry_at = None  # Don't auto-retry — needs human review
                    await db.commit()

                    event_bus.publish("album_status", {"album_id": str(album_id), "status": "stalled", "reason": "beets import failed"})

                    if notify_error:
                        await self.notifier.notify_error(
                            "beets import failed (manual review needed)",
                            f"{album.artist_name} — {album.title}: {'; '.join(beets_result.errors)}",
                        )

                    # Keep temp files for manual review
                    logger.warning(
                        "beets import failed for %s — %s, keeping temp dir %s for manual review",
                        album.artist_name, album.title, dest_path,
                    )

                    return PipelineResult(
                        album_id=album_id,
                        success=False,
                        status=AlbumStatus.STALLED,
                        message="beets import failed — manual review needed",
                        qobuz_album_id=qobuz_album.qobuz_id,
                        errors=beets_result.errors,
                    )

                # Step 6: Mark as downloaded
                album.status = AlbumStatus.DOWNLOADED
                album.downloaded_at = _utcnow()
                album.next_retry_at = None
                await db.commit()

                event_bus.publish("album_status", {"album_id": str(album_id), "status": "downloaded"})

                # Step 7: Update artist library count
                await self._increment_artist_albums(db, album.artist_name)

                # Step 8: Notify
                if notify_download:
                    await self.notifier.notify_download(
                        album_title=album.title,
                        artist_name=album.artist_name,
                        reason=album.reason,
                    )

                # Step 9: Clean up temp directory
                if dest_path.exists():
                    try:
                        shutil.rmtree(dest_path)
                    except OSError:
                        logger.warning("Failed to clean up temp dir: %s", dest_path)

                return PipelineResult(
                    album_id=album_id,
                    success=True,
                    status=AlbumStatus.DOWNLOADED,
                    message="Download and import successful",
                    qobuz_album_id=qobuz_album.qobuz_id,
                    files_downloaded=len(qobuz_album.tracks),
                    files_imported=beets_result.files_imported,
                )

            except Exception:
                logger.exception("Unhandled error in pipeline for album %s", album_id)
                # Try to update status to stalled
                try:
                    result_stmt = await db.execute(select(Album).where(Album.id == album_id))
                    album = result_stmt.scalar_one_or_none()
                    if album is not None:
                        album.status = AlbumStatus.STALLED
                        album.next_retry_at = self.schedule_retry(album.retry_count)
                        await db.commit()

                        event_bus.publish("album_status", {"album_id": str(album_id), "status": "stalled", "reason": "Unexpected error"})
                except Exception:
                    logger.exception("Failed to update album status after error")

                return PipelineResult(
                    album_id=album_id,
                    success=False,
                    status=AlbumStatus.STALLED,
                    message="Unexpected error in pipeline",
                )

    # ------------------------------------------------------------------
    # Artist library count
    # ------------------------------------------------------------------
    @staticmethod
    async def _increment_artist_albums(db: AsyncSession, artist_name: str) -> None:
        """Increment the albums_in_library count for an artist.

        Creates the artist record if it doesn't exist.
        """
        result = await db.execute(
            select(Artist).where(Artist.name == artist_name)
        )
        artist = result.scalar_one_or_none()

        if artist is not None:
            artist.albums_in_library += 1
            await db.commit()
        else:
            # Create a new artist record
            artist = Artist(
                name=artist_name,
                subscribed=False,
                albums_in_library=1,
                total_play_count=0,
            )
            db.add(artist)
            await db.commit()

    # ------------------------------------------------------------------
    # Watch folder pipeline (beets-only, no Qobuz)
    # ------------------------------------------------------------------
    async def process_watch_folder_album(
        self, album_id: uuid.UUID, source_path: str
    ) -> PipelineResult:
        """Process a watch folder album — beets import only, no Qobuz download.

        This is the simplified pipeline for albums that already have FLAC
        files in the watch folder.  It runs beets import directly, moves
        the files to the music library, and sends notifications.

        Steps:
          1. Load album from DB
          2. Set status → downloading
          3. Run beets import from *source_path* (move=True)
          4. Update status → downloaded
          5. Update artist library count
          6. Send Discord notification
        """
        if self.beets is None:
            raise RuntimeError("BeetsService is required for process_watch_folder_album")
        if self.notifier is None:
            raise RuntimeError("NotificationService is required for process_watch_folder_album")

        async with self.db_session_factory() as db:
            try:
                # Step 1: Load album
                result_stmt = await db.execute(
                    select(Album).where(Album.id == album_id)
                )
                album = result_stmt.scalar_one_or_none()
                if album is None:
                    return PipelineResult(
                        album_id=album_id,
                        success=False,
                        message=f"Album {album_id} not found",
                    )

                notify_download = await self._get_setting_bool(db, "notify_on_download")
                notify_error = await self._get_setting_bool(db, "notify_on_error")

                # Step 2: Set status → downloading
                album.status = AlbumStatus.DOWNLOADING
                album.retry_count += 1
                await db.commit()

                # Step 2.5: Attempt lenient tagging (watch folder files may
                # already have tags, but we try to fill in what we can).
                logger.info(
                    "Attempting lenient tagging for watch folder album: %s - %s",
                    album.artist_name, album.title,
                )
                try:
                    tagged_count = await self.tagger.tag_album(
                        album_dir=source_path,
                        artist=album.artist_name,
                        album=album.title,
                        tracks=[],  # We don't have track-level metadata for watch folder
                    )
                    logger.info(
                        "Tagged %d watch folder files for %s - %s",
                        tagged_count, album.artist_name, album.title,
                    )
                except Exception:
                    logger.warning(
                        "Lenient tagging failed for watch folder album %s - %s "
                        "(continuing with beets import anyway)",
                        album.artist_name, album.title,
                        exc_info=True,
                    )

                # Step 3: Run beets import
                music_library = await self._get_setting(
                    db, "music_library_directory", "/music/library"
                )
                beets_result = await self.beets.import_album(
                    source_dir=source_path,
                    dest_base=music_library,
                    move=True,  # Move files from watch dir to library
                )

                if not beets_result.success:
                    album.status = AlbumStatus.STALLED
                    album.next_retry_at = self.schedule_retry(album.retry_count)
                    await db.commit()

                    if notify_error:
                        await self.notifier.notify_error(
                            "Watch folder beets import failed",
                            f"{album.artist_name} — {album.title}: "
                            f"{'; '.join(beets_result.errors)}",
                        )

                    return PipelineResult(
                        album_id=album_id,
                        success=False,
                        status=AlbumStatus.STALLED,
                        message="beets import failed for watch folder album",
                        errors=beets_result.errors,
                    )

                # Step 4: Mark as downloaded
                album.status = AlbumStatus.DOWNLOADED
                album.downloaded_at = _utcnow()
                album.next_retry_at = None
                await db.commit()

                # Step 5: Update artist library count
                await self._increment_artist_albums(db, album.artist_name)

                # Step 6: Notify
                if notify_download:
                    await self.notifier.notify_download(
                        album_title=album.title,
                        artist_name=album.artist_name,
                        reason=album.reason,
                    )

                return PipelineResult(
                    album_id=album_id,
                    success=True,
                    status=AlbumStatus.DOWNLOADED,
                    message="Watch folder import successful",
                    files_imported=beets_result.files_imported,
                )

            except Exception:
                logger.exception(
                    "Unhandled error in watch folder pipeline for album %s",
                    album_id,
                )
                try:
                    result_stmt = await db.execute(
                        select(Album).where(Album.id == album_id)
                    )
                    album = result_stmt.scalar_one_or_none()
                    if album is not None:
                        album.status = AlbumStatus.STALLED
                        album.next_retry_at = self.schedule_retry(album.retry_count)
                        await db.commit()
                except Exception:
                    logger.exception(
                        "Failed to update album status after error"
                    )

                return PipelineResult(
                    album_id=album_id,
                    success=False,
                    status=AlbumStatus.STALLED,
                    message="Unexpected error in watch folder pipeline",
                )

    # ------------------------------------------------------------------
    # Stalled album processing
    # ------------------------------------------------------------------
    async def process_stalled_albums(self) -> int:
        """Find stalled albums where next_retry_at <= now, and retry them.

        Returns the number of albums queued for retry.
        """
        now = datetime.now(timezone.utc)
        count = 0

        async with self.db_session_factory() as db:
            result = await db.execute(
                select(Album)
                .where(
                    Album.status == AlbumStatus.STALLED,
                    Album.next_retry_at.is_not(None),
                    Album.next_retry_at <= now,
                )
                .limit(10)  # Process in batches
            )
            stalled_albums = result.scalars().all()

            for album in stalled_albums:
                album.status = AlbumStatus.QUEUED
                album.next_retry_at = None
                count += 1

            if stalled_albums:
                await db.commit()
                logger.info("Re-queued %d stalled albums for retry", count)

        return count

    # ------------------------------------------------------------------
    # Queue helpers (used by rule engine / sync orchestrator)
    # ------------------------------------------------------------------
    async def queue_album(
        self,
        title: str,
        artist_name: str,
        queue_type: QueueType = QueueType.AUTO,
        reason: str = "",
        play_count: int = 0,
    ) -> Album:
        """Create a new album queue entry and optionally notify."""
        async with self.db_session_factory() as db:
            album = Album(
                title=title,
                artist_name=artist_name,
                queue_type=queue_type,
                reason=reason,
                play_count=play_count,
                status=AlbumStatus.QUEUED,
            )
            db.add(album)
            await db.commit()
            await db.refresh(album)

            # Notify for manual queue items
            if queue_type == QueueType.MANUAL:
                notify_manual = await self._get_setting_bool(db, "notify_on_queued_manual")
                if notify_manual:
                    await self.notifier.notify_queued_manual(
                        album_title=title,
                        artist_name=artist_name,
                        reason=reason,
                    )

            return album
