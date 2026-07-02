"""Watch folder monitoring service using watchdog.

Detects new files in a configurable watch directory, deduplicates against
the existing library, and queues albums for beets tagging + import via Celery.

Uses a :class:`PollingObserver` (rather than inotify) for reliability on
network / NAS filesystems. A stability timer ensures that files still being
copied are not processed prematurely.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

import watchdog.events
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from watchdog.observers.polling import PollingObserver

from app.models.album import Album, AlbumStatus, QueueType
from app.models.setting import Setting

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Watchdog event handler
# ---------------------------------------------------------------------------


class WatchFolderHandler(watchdog.events.FileSystemEventHandler):
    """watchdog event handler that enqueues new files for processing
    after a configurable stability period.

    When files are being copied into the watch folder (e.g. over a network),
    each new file resets a timer.  Only when no new files have appeared for
    *stability_seconds* does the handler fire the callback with the album
    directory path.
    """

    def __init__(
        self,
        callback: Callable[[str], None],
        stability_seconds: float = 60.0,
        watch_dir: str = "",
    ) -> None:
        super().__init__()
        self._callback = callback
        self._stability_seconds = stability_seconds
        self._watch_dir = os.path.normpath(watch_dir)
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_created(self, event: watchdog.events.FileSystemEvent) -> None:
        """A file or directory was created — reset the stability timer."""
        album_dir = self._resolve_album_dir(event.src_path, event.is_directory)
        if album_dir is not None:
            self._schedule_or_reset(album_dir)

    def on_modified(self, event: watchdog.events.FileSystemEvent) -> None:
        """A file was modified (still being written) — reset the timer."""
        if event.is_directory:
            return
        album_dir = self._resolve_album_dir(event.src_path, False)
        if album_dir is not None:
            self._schedule_or_reset(album_dir)

    def on_moved(self, event: watchdog.events.FileSystemEvent) -> None:
        """A file was moved *into* the watch folder — treat like creation."""
        album_dir = self._resolve_album_dir(event.dest_path, event.is_directory)
        if album_dir is not None:
            self._schedule_or_reset(album_dir)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_album_dir(
        self, path: str, is_directory: bool
    ) -> str | None:
        """Resolve the album directory for a given event path.

        Returns ``None`` when the path is the root watch directory itself
        — we only process *subdirectories*.
        """
        if is_directory:
            album_dir = os.path.normpath(path)
        else:
            album_dir = os.path.normpath(os.path.dirname(path))

        if album_dir == self._watch_dir:
            return None

        return album_dir

    def _schedule_or_reset(self, album_dir: str) -> None:
        """Start or reset the stability timer for *album_dir*."""
        with self._lock:
            existing = self._pending.pop(album_dir, None)
            if existing is not None:
                existing.cancel()

            timer = threading.Timer(
                self._stability_seconds,
                self._on_stable,
                args=[album_dir],
            )
            timer.daemon = True
            self._pending[album_dir] = timer
            timer.start()

            logger.debug(
                "Stability timer %s for %s (%0.1fs)",
                "reset" if existing else "set",
                album_dir,
                self._stability_seconds,
            )

    def _on_stable(self, path: str) -> None:
        """Called by the timer when *path* has been stable."""
        with self._lock:
            self._pending.pop(path, None)

        logger.info("Watch folder path stabilized: %s", path)
        try:
            self._callback(path)
        except Exception:
            logger.exception("Error processing watch folder path: %s", path)


# ---------------------------------------------------------------------------
# Watch folder service
# ---------------------------------------------------------------------------


class WatchFolderService:
    """Monitors a filesystem folder for new music files and queues them
    for beets tagging and import.

    Uses a watchdog :class:`PollingObserver` (rather than inotify) for
    reliability on network / NAS filesystems.

    Lifecycle::

        svc = WatchFolderService(db_factory, beets, notifier)
        await svc.start()   # starts background observer thread
        ...
        await svc.stop()    # stops observer and joins thread
    """

    def __init__(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        beets_service,  # BeetsService
        notification_service,  # NotificationService
    ) -> None:
        self.db_session_factory = db_session_factory
        self.beets_service = beets_service
        self.notification_service = notification_service
        self._observer: PollingObserver | None = None
        self._thread: threading.Thread | None = None
        self._handler: WatchFolderHandler | None = None
        self._watch_dir: str = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the watchdog observer in a background daemon thread.

        Reads ``watch_folder_enabled``, ``music_downloads_watch_directory``,
        and ``watch_folder_check_seconds`` from the database settings table.
        Does nothing if the feature is disabled.
        """
        async with self.db_session_factory() as db:
            enabled = await self._get_setting(db, "watch_folder_enabled", "true")
            if enabled.lower() not in ("true", "1", "yes"):
                logger.info("Watch folder is disabled; not starting observer.")
                return

            self._watch_dir = await self._get_setting(
                db, "music_downloads_watch_directory", "/music/downloads"
            )
            stability_secs = float(
                await self._get_setting(db, "watch_folder_check_seconds", "60")
            )

        watch_path = Path(self._watch_dir)
        if not watch_path.exists():
            logger.warning(
                "Watch directory does not exist: %s. Creating it.",
                self._watch_dir,
            )
            watch_path.mkdir(parents=True, exist_ok=True)

        if not watch_path.is_dir():
            logger.error(
                "Watch path is not a directory: %s. Cannot start observer.",
                self._watch_dir,
            )
            return

        self._handler = WatchFolderHandler(
            callback=self._on_path_stable_sync,
            stability_seconds=stability_secs,
            watch_dir=self._watch_dir,
        )
        self._observer = PollingObserver()
        self._observer.schedule(
            self._handler, str(watch_path), recursive=True
        )

        self._thread = threading.Thread(
            target=self._observer.start,
            daemon=True,
            name="watch-folder-observer",
        )
        self._thread.start()

        logger.info(
            "Watch folder service started: %s (stability=%0.1fs)",
            self._watch_dir,
            stability_secs,
        )

    async def stop(self) -> None:
        """Stop the watchdog observer and join the background thread."""
        if self._observer is not None:
            logger.info("Stopping watch folder observer...")
            self._observer.stop()
            try:
                self._observer.join(timeout=10)
            except Exception:
                logger.warning("Observer join timed out")
            self._observer = None

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
            self._thread = None

        logger.info("Watch folder service stopped.")

    # ------------------------------------------------------------------
    # Path processing
    # ------------------------------------------------------------------

    def _on_path_stable_sync(self, path: str) -> None:
        """Synchronous bridge from the watchdog callback thread.

        Creates a new event loop to run the async handler since the
        watchdog callback fires from a background thread.
        """
        asyncio.run(self._handle_new_path(path))

    async def _handle_new_path(self, path: str) -> None:
        """Process a newly stabilized watch folder path.

        1. Determine the album source directory.
        2. Extract artist / album name from the path.
        3. Deduplicate against existing library albums.
        4. Create an ``Album`` record with ``queue_type=watch_folder``.
        5. Dispatch to the ``process_watch_folder_album`` Celery task.
        6. Send a Discord notification (if enabled).
        """
        source_dir = path if os.path.isdir(path) else os.path.dirname(path)
        source_dir = os.path.normpath(source_dir)

        # Skip root watch directory
        watch_dir_norm = os.path.normpath(self._watch_dir)
        if source_dir == watch_dir_norm:
            logger.debug("Skipping root watch directory: %s", source_dir)
            return

        # Skip non-existent paths (may have been moved / deleted)
        if not os.path.exists(source_dir):
            logger.debug("Path no longer exists, skipping: %s", source_dir)
            return

        artist_name, album_title = self._extract_artist_album(
            source_dir, self._watch_dir
        )

        # --- Deduplicate: skip if album already downloaded ---
        async with self.db_session_factory() as db:
            result = await db.execute(
                select(Album).where(
                    Album.artist_name == artist_name,
                    Album.title == album_title,
                    Album.status == AlbumStatus.DOWNLOADED,
                )
            )
            if result.scalar_one_or_none() is not None:
                logger.info(
                    "Album already in library, skipping: %s — %s",
                    artist_name,
                    album_title,
                )
                return

        # --- Create Album record ---
        async with self.db_session_factory() as db:
            album = Album(
                title=album_title,
                artist_name=artist_name,
                queue_type=QueueType.WATCH_FOLDER,
                status=AlbumStatus.QUEUED,
                reason="watch folder",
            )
            db.add(album)
            await db.commit()
            await db.refresh(album)
            album_id = str(album.id)

        # --- Dispatch Celery task ---
        try:
            from app.services.downloader import process_watch_folder_album_task

            process_watch_folder_album_task.delay(album_id, source_dir)
        except Exception:
            logger.exception(
                "Failed to dispatch Celery task for watch folder album %s",
                album_id,
            )
            # Mark album as stalled so it is visible in the UI
            async with self.db_session_factory() as db:
                result = await db.execute(
                    select(Album).where(Album.id == album.id)
                )
                album_ref = result.scalar_one_or_none()
                if album_ref is not None:
                    album_ref.status = AlbumStatus.STALLED
                    album_ref.reason = "watch folder (Celery dispatch failed)"
                    await db.commit()
            return

        # --- Notify ---
        notify = await self._get_setting_bool("notify_on_watch_folder")
        if notify:
            try:
                await self.notification_service.notify_watch_folder(
                    album_title=album_title,
                    artist_name=artist_name,
                    source_path=source_dir,
                )
            except Exception:
                logger.exception(
                    "Failed to send watch folder notification"
                )

        logger.info(
            "Watch folder album queued: %s — %s (id=%s, path=%s)",
            artist_name,
            album_title,
            album_id,
            source_dir,
        )

    # ------------------------------------------------------------------
    # Path parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_artist_album(
        source_dir: str, watch_dir: str = ""
    ) -> tuple[str, str]:
        """Extract artist name and album title from a directory path.

        Heuristics (tried in order):

        1. ``<watch>/ArtistName/AlbumName/``
           → ``("ArtistName", "AlbumName")``
        2. ``<watch>/ArtistName - AlbumName/``
           → ``("ArtistName", "AlbumName")``
        3. ``<watch>/AlbumName/``
           → ``("Unknown Artist", "AlbumName")``
        """
        dirname = os.path.basename(source_dir.rstrip("/\\"))
        parent_dir = os.path.dirname(source_dir.rstrip("/\\"))
        parent = os.path.basename(parent_dir)

        # Determine whether *parent_dir* is the watch directory itself.
        # If so, there is no artist-level subdirectory — skip heuristic 1.
        if watch_dir:
            is_child_of_watch = (
                os.path.normpath(parent_dir) == os.path.normpath(watch_dir)
            )
        else:
            # Fallback for tests that don't pass watch_dir
            is_child_of_watch = parent in ("", "downloads", "music")

        # Heuristic 1: two-level artist / album structure
        if parent and not is_child_of_watch:
            return parent, dirname

        # Heuristic 2: "Artist - Album" in folder name
        if " - " in dirname:
            parts = dirname.split(" - ", 1)
            artist = parts[0].strip()
            album = parts[1].strip()
            if artist and album:
                return artist, album

        # Heuristic 3: fallback
        return "Unknown Artist", dirname

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _get_setting(
        self, db: AsyncSession, key: str, default: str = ""
    ) -> str:
        """Read a setting value from the database, falling back to built-in
        defaults."""
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()
        if setting is not None:
            return setting.value
        from app.constants import DEFAULT_SETTINGS

        return DEFAULT_SETTINGS.get(key, default)

    async def _get_setting_bool(
        self, key: str, default: bool = True
    ) -> bool:
        """Read a boolean setting, opening its own short-lived session."""
        async with self.db_session_factory() as db:
            val = await self._get_setting(
                db, key, "true" if default else "false"
            )
        return val.lower() in ("true", "1", "yes")
