"""Tests for the watch folder monitoring service.

Covers path parsing, album creation, deduplication, stability timer,
and the beets-only pipeline for watch folder items.
"""

from __future__ import annotations

import os
import tempfile
import threading
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.album import Album, AlbumStatus, QueueType
from app.models.setting import Setting
from app.services.beets import BeetsResult
from app.services.notifications import NotificationService
from app.services.pipeline import DownloadPipeline, PipelineResult
from app.services.watch_folder import WatchFolderHandler, WatchFolderService

from tests.conftest import test_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a test async session factory using the shared test engine."""
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def _create_album_in_db(
    session_factory: async_sessionmaker[AsyncSession],
    **overrides,
) -> Album:
    """Create and return a test Album record."""
    defaults: dict = {
        "id": uuid.uuid4(),
        "title": "Test Album",
        "artist_name": "Test Artist",
        "status": AlbumStatus.QUEUED,
        "queue_type": QueueType.AUTO,
        "reason": "test",
    }
    defaults.update(overrides)
    async with session_factory() as db:
        album = Album(**defaults)
        db.add(album)
        await db.commit()
        await db.refresh(album)
        return album


async def _seed_setting(
    session_factory: async_sessionmaker[AsyncSession],
    key: str,
    value: str,
) -> None:
    """Insert a setting value into the test DB."""
    async with session_factory() as db:
        setting = Setting(key=key, value=value, category="sources")
        db.add(setting)
        await db.commit()


# ---------------------------------------------------------------------------
# Mock fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_beets() -> MagicMock:
    b = MagicMock()
    b.import_album = AsyncMock()
    return b


@pytest.fixture
def mock_notifier() -> MagicMock:
    n = MagicMock(spec=NotificationService)
    n.notify_watch_folder = AsyncMock(return_value=True)
    n.notify_download = AsyncMock(return_value=True)
    n.notify_error = AsyncMock(return_value=True)
    n.notify_stalled = AsyncMock(return_value=True)
    n.close = AsyncMock()
    return n


@pytest.fixture
def session_factory() -> async_sessionmaker[AsyncSession]:
    return _make_session_factory()


@pytest.fixture
def watch_folder_service(
    mock_beets: MagicMock,
    mock_notifier: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> WatchFolderService:
    """Create a WatchFolderService with mocked beets and notifier."""
    svc = WatchFolderService(
        db_session_factory=session_factory,
        beets_service=mock_beets,
        notification_service=mock_notifier,
    )
    # Set watch dir to a temp path so we can control what exists
    svc._watch_dir = tempfile.mkdtemp(prefix="musically_test_watch_")
    return svc


@pytest.fixture
def watch_folder_pipeline(
    mock_beets: MagicMock,
    mock_notifier: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> DownloadPipeline:
    """Create a DownloadPipeline for watch folder (no Qobuz)."""
    return DownloadPipeline(
        db_session_factory=session_factory,
        qobuz=None,
        beets=mock_beets,
        notifier=mock_notifier,
    )


# ===================================================================
# Path parsing tests
# ===================================================================


class TestExtractArtistAlbum:
    """Tests for WatchFolderService._extract_artist_album()."""

    def test_two_level_artist_album(self):
        artist, album = WatchFolderService._extract_artist_album(
            "/music/downloads/Pink Floyd/Dark Side of the Moon"
        )
        assert artist == "Pink Floyd"
        assert album == "Dark Side of the Moon"

    def test_two_level_with_trailing_slash(self):
        artist, album = WatchFolderService._extract_artist_album(
            "/music/downloads/Radiohead/OK Computer/"
        )
        assert artist == "Radiohead"
        assert album == "OK Computer"

    def test_artist_dash_album_folder(self):
        artist, album = WatchFolderService._extract_artist_album(
            "/music/downloads/The Beatles - Abbey Road"
        )
        assert artist == "The Beatles"
        assert album == "Abbey Road"

    def test_artist_dash_album_with_spaces(self):
        artist, album = WatchFolderService._extract_artist_album(
            "/music/downloads/  Daft Punk  -  Random Access Memories  "
        )
        assert artist == "Daft Punk"
        assert album == "Random Access Memories"

    def test_fallback_unknown_artist(self):
        artist, album = WatchFolderService._extract_artist_album(
            "/music/downloads/SomeRandomAlbum"
        )
        assert artist == "Unknown Artist"
        assert album == "SomeRandomAlbum"

    def test_parent_is_downloads_fallback(self):
        """When parent dir is 'downloads', use artist-album heuristic."""
        artist, album = WatchFolderService._extract_artist_album(
            "/music/downloads/Kendrick Lamar - DAMN."
        )
        assert artist == "Kendrick Lamar"
        assert album == "DAMN."

    def test_windows_paths(self):
        artist, album = WatchFolderService._extract_artist_album(
            r"C:\music\downloads\Massive Attack\Mezzanine"
        )
        assert artist == "Massive Attack"
        assert album == "Mezzanine"


# ===================================================================
# _handle_new_path tests
# ===================================================================


class TestHandleNewPath:
    """Tests for WatchFolderService._handle_new_path()."""

    @pytest.mark.asyncio
    async def test_creates_album_and_dispatches(
        self,
        watch_folder_service: WatchFolderService,
        session_factory: async_sessionmaker[AsyncSession],
        mock_notifier: MagicMock,
    ):
        """A new album directory should create an Album and dispatch the Celery task."""
        # Create a test album directory structure
        album_dir = os.path.join(
            watch_folder_service._watch_dir, "Test Artist", "Test Album"
        )
        os.makedirs(album_dir, exist_ok=True)
        # Create a dummy FLAC file so the dir isn't empty
        Path(album_dir, "01 - Track.flac").touch()

        with patch(
            "app.services.downloader.process_watch_folder_album_task"
        ) as mock_task:
            mock_task.delay = MagicMock()

            await watch_folder_service._handle_new_path(album_dir)

            # Verify Album was created
            async with session_factory() as db:
                result = await db.execute(
                    select(Album).where(
                        Album.artist_name == "Test Artist",
                        Album.title == "Test Album",
                    )
                )
                album = result.scalar_one_or_none()
                assert album is not None
                assert album.queue_type == QueueType.WATCH_FOLDER
                assert album.status == AlbumStatus.QUEUED
                assert album.reason == "watch folder"

            # Verify Celery task was dispatched
            mock_task.delay.assert_called_once()
            call_args = mock_task.delay.call_args[0]
            assert call_args[0] == str(album.id)
            assert call_args[1] == os.path.normpath(album_dir)

    @pytest.mark.asyncio
    async def test_skips_root_watch_directory(
        self,
        watch_folder_service: WatchFolderService,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        """Files dropped directly in the root watch dir should be skipped."""
        with patch(
            "app.services.downloader.process_watch_folder_album_task"
        ) as mock_task:
            mock_task.delay = MagicMock()

            await watch_folder_service._handle_new_path(
                watch_folder_service._watch_dir
            )

            # No Celery dispatch should have happened
            mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_nonexistent_path(
        self,
        watch_folder_service: WatchFolderService,
    ):
        """A path that doesn't exist should be skipped gracefully."""
        nonexistent = os.path.join(
            watch_folder_service._watch_dir, "DoesNotExist"
        )
        with patch(
            "app.services.downloader.process_watch_folder_album_task"
        ) as mock_task:
            mock_task.delay = MagicMock()

            # Should not raise
            await watch_folder_service._handle_new_path(nonexistent)

            mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_already_downloaded_album(
        self,
        watch_folder_service: WatchFolderService,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        """An album that already exists with status=downloaded should be skipped."""
        # Pre-create a downloaded album
        await _create_album_in_db(
            session_factory,
            title="Existing Album",
            artist_name="Existing Artist",
            status=AlbumStatus.DOWNLOADED,
        )

        # Create matching directory
        album_dir = os.path.join(
            watch_folder_service._watch_dir, "Existing Artist", "Existing Album"
        )
        os.makedirs(album_dir, exist_ok=True)
        Path(album_dir, "01.flac").touch()

        with patch(
            "app.services.downloader.process_watch_folder_album_task"
        ) as mock_task:
            mock_task.delay = MagicMock()

            await watch_folder_service._handle_new_path(album_dir)

            # Should NOT dispatch because album already exists
            mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_queued_album_not_considered_duplicate(
        self,
        watch_folder_service: WatchFolderService,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        """An album with status=queued (not downloaded) should still be
        processed — it might have stalled previously."""
        await _create_album_in_db(
            session_factory,
            title="Queued Album",
            artist_name="Queued Artist",
            status=AlbumStatus.QUEUED,
        )

        album_dir = os.path.join(
            watch_folder_service._watch_dir, "Queued Artist", "Queued Album"
        )
        os.makedirs(album_dir, exist_ok=True)
        Path(album_dir, "01.flac").touch()

        with patch(
            "app.services.downloader.process_watch_folder_album_task"
        ) as mock_task:
            mock_task.delay = MagicMock()

            await watch_folder_service._handle_new_path(album_dir)

            # Should still dispatch — only DOWNLOADED status counts as duplicate
            mock_task.delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_notifies_when_enabled(
        self,
        watch_folder_service: WatchFolderService,
        session_factory: async_sessionmaker[AsyncSession],
        mock_notifier: MagicMock,
    ):
        """Should send a Discord notification when notify_on_watch_folder is true."""
        await _seed_setting(session_factory, "notify_on_watch_folder", "true")

        album_dir = os.path.join(
            watch_folder_service._watch_dir, "Notify Artist", "Notify Album"
        )
        os.makedirs(album_dir, exist_ok=True)
        Path(album_dir, "01.flac").touch()

        with patch(
            "app.services.downloader.process_watch_folder_album_task"
        ) as mock_task:
            mock_task.delay = MagicMock()

            await watch_folder_service._handle_new_path(album_dir)

            mock_notifier.notify_watch_folder.assert_called_once_with(
                album_title="Notify Album",
                artist_name="Notify Artist",
                source_path=os.path.normpath(album_dir),
            )

    @pytest.mark.asyncio
    async def test_artist_dash_album_folder_detected(
        self,
        watch_folder_service: WatchFolderService,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        """Folders named 'Artist - Album' should be parsed correctly."""
        album_dir = os.path.join(
            watch_folder_service._watch_dir, "Fleetwood Mac - Rumours"
        )
        os.makedirs(album_dir, exist_ok=True)
        Path(album_dir, "01.flac").touch()

        with patch(
            "app.services.downloader.process_watch_folder_album_task"
        ) as mock_task:
            mock_task.delay = MagicMock()

            await watch_folder_service._handle_new_path(album_dir)

            async with session_factory() as db:
                result = await db.execute(
                    select(Album).where(
                        Album.artist_name == "Fleetwood Mac",
                        Album.title == "Rumours",
                    )
                )
                album = result.scalar_one_or_none()
                assert album is not None
                assert album.queue_type == QueueType.WATCH_FOLDER


# ===================================================================
# Stability timer tests
# ===================================================================


class TestWatchFolderHandler:
    """Tests for the WatchFolderHandler stability timer."""

    def test_timer_fires_after_stability(self):
        """The callback should fire after stability_seconds of no events."""
        callback = MagicMock()
        handler = WatchFolderHandler(
            callback=callback,
            stability_seconds=0.05,  # Very short for tests
            watch_dir="/tmp/watch",
        )

        # Simulate a file creation
        event = MagicMock()
        event.src_path = "/tmp/watch/Artist/Album/01.flac"
        event.is_directory = False
        event.dest_path = "/tmp/watch/Artist/Album/01.flac"

        handler.on_created(event)

        # Callback should NOT have fired yet
        callback.assert_not_called()

        # Wait for the timer to fire
        import time
        time.sleep(0.15)

        # Callback should have fired with the album directory
        callback.assert_called_once()
        called_path = callback.call_args[0][0]
        assert called_path == os.path.normpath("/tmp/watch/Artist/Album")

    def test_timer_resets_on_new_event(self):
        """New events should reset the timer."""
        callback = MagicMock()
        handler = WatchFolderHandler(
            callback=callback,
            stability_seconds=0.1,
            watch_dir="/tmp/watch",
        )

        event = MagicMock()
        event.is_directory = False
        event.dest_path = "/tmp/watch/Artist/Album/01.flac"

        # First event
        event.src_path = "/tmp/watch/Artist/Album/01.flac"
        handler.on_created(event)

        import time
        time.sleep(0.04)

        # Second event before timer fires — should reset
        event.src_path = "/tmp/watch/Artist/Album/02.flac"
        handler.on_created(event)

        # Callback should NOT have fired yet (timer was reset)
        callback.assert_not_called()

        # Wait for the reset timer
        time.sleep(0.15)

        # Now it should have fired exactly once
        callback.assert_called_once()

    def test_different_albums_independent_timers(self):
        """Different albums have independent stability timers."""
        callback = MagicMock()
        handler = WatchFolderHandler(
            callback=callback,
            stability_seconds=0.05,
            watch_dir="/tmp/watch",
        )

        event1 = MagicMock()
        event1.src_path = "/tmp/watch/Artist1/Album1/01.flac"
        event1.is_directory = False
        event1.dest_path = "/tmp/watch/Artist1/Album1/01.flac"

        event2 = MagicMock()
        event2.src_path = "/tmp/watch/Artist2/Album2/01.flac"
        event2.is_directory = False
        event2.dest_path = "/tmp/watch/Artist2/Album2/01.flac"

        handler.on_created(event1)
        handler.on_created(event2)

        import time
        time.sleep(0.10)

        # Both should have fired
        assert callback.call_count == 2
        called_paths = {
            callback.call_args_list[0][0][0],
            callback.call_args_list[1][0][0],
        }
        assert os.path.normpath("/tmp/watch/Artist1/Album1") in called_paths
        assert os.path.normpath("/tmp/watch/Artist2/Album2") in called_paths

    def test_ignores_root_watch_directory(self):
        """Events on the root watch directory should be ignored."""
        callback = MagicMock()
        handler = WatchFolderHandler(
            callback=callback,
            stability_seconds=0.05,
            watch_dir="/tmp/watch",
        )

        event = MagicMock()
        event.src_path = "/tmp/watch/some_file.flac"
        event.is_directory = False
        event.dest_path = "/tmp/watch/some_file.flac"

        handler.on_created(event)

        import time
        time.sleep(0.10)

        # Root-level files should be ignored
        callback.assert_not_called()


# ===================================================================
# Service lifecycle tests
# ===================================================================


class TestWatchFolderServiceLifecycle:
    """Tests for WatchFolderService start / stop."""

    @pytest.mark.asyncio
    async def test_start_skips_when_disabled(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        mock_beets: MagicMock,
        mock_notifier: MagicMock,
    ):
        """When watch_folder_enabled=false, start() should return without
        starting an observer."""
        await _seed_setting(session_factory, "watch_folder_enabled", "false")

        svc = WatchFolderService(
            db_session_factory=session_factory,
            beets_service=mock_beets,
            notification_service=mock_notifier,
        )
        await svc.start()

        # Observer should not be created
        assert svc._observer is None
        assert svc._thread is None

    @pytest.mark.asyncio
    async def test_stop_does_nothing_when_not_started(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        mock_beets: MagicMock,
        mock_notifier: MagicMock,
    ):
        """stop() should be a no-op if start() was never called."""
        svc = WatchFolderService(
            db_session_factory=session_factory,
            beets_service=mock_beets,
            notification_service=mock_notifier,
        )
        await svc.stop()  # Should not raise


# ===================================================================
# Pipeline tests
# ===================================================================


class TestWatchFolderPipeline:
    """Tests for DownloadPipeline.process_watch_folder_album()."""

    @pytest.mark.asyncio
    async def test_successful_beets_import(
        self,
        watch_folder_pipeline: DownloadPipeline,
        session_factory: async_sessionmaker[AsyncSession],
        mock_beets: MagicMock,
        mock_notifier: MagicMock,
    ):
        """A successful beets import should mark album as downloaded."""
        album = await _create_album_in_db(
            session_factory,
            title="Pipeline Album",
            artist_name="Pipeline Artist",
            queue_type=QueueType.WATCH_FOLDER,
            status=AlbumStatus.QUEUED,
        )

        mock_beets.import_album.return_value = BeetsResult(
            success=True,
            matched_album="Pipeline Artist - Pipeline Album",
            files_imported=10,
        )

        result = await watch_folder_pipeline.process_watch_folder_album(
            album.id, "/tmp/source"
        )

        assert result.success is True
        assert result.status == AlbumStatus.DOWNLOADED
        assert result.files_imported == 10

        # Verify album status in DB
        async with session_factory() as db:
            refreshed = await db.get(Album, album.id)
            assert refreshed is not None
            assert refreshed.status == AlbumStatus.DOWNLOADED
            assert refreshed.downloaded_at is not None
            assert refreshed.next_retry_at is None

        # Verify beets was called with move=True
        mock_beets.import_album.assert_called_once()
        call_kwargs = mock_beets.import_album.call_args[1]
        assert call_kwargs["move"] is True
        assert call_kwargs["source_dir"] == "/tmp/source"

        # Verify notification
        mock_notifier.notify_download.assert_called_once()

    @pytest.mark.asyncio
    async def test_beets_failure_marks_stalled(
        self,
        watch_folder_pipeline: DownloadPipeline,
        session_factory: async_sessionmaker[AsyncSession],
        mock_beets: MagicMock,
        mock_notifier: MagicMock,
    ):
        """A failed beets import should mark album as stalled."""
        album = await _create_album_in_db(
            session_factory,
            title="Fail Album",
            artist_name="Fail Artist",
            queue_type=QueueType.WATCH_FOLDER,
            status=AlbumStatus.QUEUED,
        )

        mock_beets.import_album.return_value = BeetsResult(
            success=False,
            errors=["No matching release found"],
        )

        await _seed_setting(session_factory, "notify_on_error", "true")

        result = await watch_folder_pipeline.process_watch_folder_album(
            album.id, "/tmp/source"
        )

        assert result.success is False
        assert result.status == AlbumStatus.STALLED
        assert "No matching release found" in result.errors

        async with session_factory() as db:
            refreshed = await db.get(Album, album.id)
            assert refreshed is not None
            assert refreshed.status == AlbumStatus.STALLED
            assert refreshed.next_retry_at is not None

        mock_notifier.notify_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_album_not_found(
        self,
        watch_folder_pipeline: DownloadPipeline,
    ):
        """An invalid album_id should return a failure result."""
        fake_id = uuid.uuid4()
        result = await watch_folder_pipeline.process_watch_folder_album(
            fake_id, "/tmp/source"
        )

        assert result.success is False
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_increments_artist_library_count(
        self,
        watch_folder_pipeline: DownloadPipeline,
        session_factory: async_sessionmaker[AsyncSession],
        mock_beets: MagicMock,
    ):
        """After a successful import, artist's albums_in_library should increment."""
        album = await _create_album_in_db(
            session_factory,
            title="Count Album",
            artist_name="Count Artist",
            queue_type=QueueType.WATCH_FOLDER,
            status=AlbumStatus.QUEUED,
        )

        mock_beets.import_album.return_value = BeetsResult(
            success=True,
            matched_album="Count Artist - Count Album",
            files_imported=3,
        )

        await watch_folder_pipeline.process_watch_folder_album(
            album.id, "/tmp/source"
        )

        async with session_factory() as db:
            from app.models.artist import Artist
            result = await db.execute(
                select(Artist).where(Artist.name == "Count Artist")
            )
            artist = result.scalar_one_or_none()
            assert artist is not None
            assert artist.albums_in_library == 1

    @pytest.mark.asyncio
    async def test_handles_unexpected_exception(
        self,
        watch_folder_pipeline: DownloadPipeline,
        session_factory: async_sessionmaker[AsyncSession],
        mock_beets: MagicMock,
    ):
        """An unexpected exception should mark album as stalled."""
        album = await _create_album_in_db(
            session_factory,
            title="Crash Album",
            artist_name="Crash Artist",
            queue_type=QueueType.WATCH_FOLDER,
            status=AlbumStatus.QUEUED,
        )

        mock_beets.import_album.side_effect = RuntimeError("Boom!")

        result = await watch_folder_pipeline.process_watch_folder_album(
            album.id, "/tmp/source"
        )

        assert result.success is False
        assert result.status == AlbumStatus.STALLED

        async with session_factory() as db:
            refreshed = await db.get(Album, album.id)
            assert refreshed is not None
            assert refreshed.status == AlbumStatus.STALLED
