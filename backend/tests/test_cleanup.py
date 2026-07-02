"""Tests for the CleanupService."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.album import Album, AlbumStatus, QueueType
from app.services.cleanup import CleanupService


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="module")
async def cleanup_engine():
    """Module-scoped in-memory engine shared by all tests in this module."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def cleanup_db_session_factory(cleanup_engine):
    """Create tables fresh for each test, return session factory."""
    async with cleanup_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(cleanup_engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    async with cleanup_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def cleanup_db(cleanup_db_session_factory: async_sessionmaker[AsyncSession]):
    """Provide a DB session pre-populated with test albums."""
    async with cleanup_db_session_factory() as db:
        # Downloaded album — temp dir should be cleaned
        a1 = Album(
            title="Downloaded Album",
            artist_name="Artist A",
            status=AlbumStatus.DOWNLOADED,
            queue_type=QueueType.AUTO,
        )
        # Rejected album — temp dir should be cleaned
        a2 = Album(
            title="Rejected Album",
            artist_name="Artist B",
            status=AlbumStatus.REJECTED,
            queue_type=QueueType.MANUAL,
        )
        # Queued album — temp dir should NOT be cleaned (still needed)
        a3 = Album(
            title="Queued Album",
            artist_name="Artist C",
            status=AlbumStatus.QUEUED,
            queue_type=QueueType.AUTO,
        )
        # Downloading album — temp dir should NOT be cleaned
        a4 = Album(
            title="Downloading Album",
            artist_name="Artist D",
            status=AlbumStatus.DOWNLOADING,
            queue_type=QueueType.AUTO,
        )
        db.add_all([a1, a2, a3, a4])
        await db.commit()

        # Store IDs for use in tests
        yield {
            "downloaded_id": a1.id,
            "rejected_id": a2.id,
            "queued_id": a3.id,
            "downloading_id": a4.id,
        }

        await db.rollback()


class TestCleanupDownloads:
    """Tests for removing empty download directories."""

    @pytest.mark.asyncio
    async def test_remove_empty_dirs(self, cleanup_db_session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Empty directories should be removed; non-empty ones left alone."""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloads = Path(tmpdir) / "downloads"
            downloads.mkdir()

            # Create empty dirs
            empty1 = downloads / "empty-1"
            empty2 = downloads / "empty-2"
            empty1.mkdir()
            empty2.mkdir()

            # Create a dir with a file (should NOT be removed)
            active = downloads / "active-dir"
            active.mkdir()
            (active / "track.flac").write_text("fake audio data")

            # Create a dir with only a subdir (empty subdir — should be removed
            # because rglob finds no files)
            nested = downloads / "nested-empty"
            nested.mkdir()
            (nested / "subdir").mkdir()

            service = CleanupService(
                db_session_factory=cleanup_db_session_factory,
                downloads_dir=str(downloads),
            )
            count = await service.cleanup_downloads()

            assert count == 3  # empty1, empty2, nested-empty
            assert not empty1.exists()
            assert not empty2.exists()
            assert active.exists()  # has files, not removed
            assert not nested.exists()

    @pytest.mark.asyncio
    async def test_no_downloads_dir(self, cleanup_db_session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Should return 0 when download dir doesn't exist."""
        service = CleanupService(
            db_session_factory=cleanup_db_session_factory,
            downloads_dir="/nonexistent/path/12345",
        )
        count = await service.cleanup_downloads()
        assert count == 0

    @pytest.mark.asyncio
    async def test_downloads_is_file_not_dir(self, cleanup_db_session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Should return 0 when download path is a file, not a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "not_a_dir.txt"
            filepath.write_text("hello")

            service = CleanupService(
                db_session_factory=cleanup_db_session_factory,
                downloads_dir=str(filepath),
            )
            count = await service.cleanup_downloads()
            assert count == 0


class TestCleanupArtworkCache:
    """Tests for removing old artwork cache files."""

    @pytest.mark.asyncio
    async def test_remove_old_cache_files(self, cleanup_db_session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Files older than max_age_days should be removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Path(tmpdir) / "artwork_cache"
            cache.mkdir()

            # Create a "recent" file (modified just now)
            recent = cache / "recent.jpg"
            recent.write_bytes(b"fake image data")

            # Create an "old" file (modify mtime to be 60 days ago)
            old = cache / "old.jpg"
            old.write_bytes(b"old image data")
            old_mtime = time.time() - (60 * 86400)  # 60 days ago
            os.utime(str(old), (old_mtime, old_mtime))

            service = CleanupService(
                db_session_factory=cleanup_db_session_factory,
                cache_dir=str(cache),
            )
            count = await service.cleanup_artwork_cache(max_age_days=30)

            assert count == 1
            assert recent.exists()
            assert not old.exists()

    @pytest.mark.asyncio
    async def test_no_cache_dir(self, cleanup_db_session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Should return 0 when cache dir doesn't exist."""
        service = CleanupService(
            db_session_factory=cleanup_db_session_factory,
            cache_dir="/nonexistent/cache/path",
        )
        count = await service.cleanup_artwork_cache()
        assert count == 0

    @pytest.mark.asyncio
    async def test_all_files_recent(self, cleanup_db_session_factory: async_sessionmaker[AsyncSession]) -> None:
        """No files should be removed if all are within max_age_days."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Path(tmpdir) / "artwork_cache"
            cache.mkdir()

            for i in range(3):
                f = cache / f"img_{i}.jpg"
                f.write_bytes(b"data")

            service = CleanupService(
                db_session_factory=cleanup_db_session_factory,
                cache_dir=str(cache),
            )
            count = await service.cleanup_artwork_cache(max_age_days=30)
            assert count == 0


class TestCleanupStalledTempDirs:
    """Tests for removing temp dirs of already-processed albums."""

    @pytest.mark.asyncio
    async def test_remove_downloaded_and_rejected_dirs(
        self,
        cleanup_db_session_factory: async_sessionmaker[AsyncSession],
        cleanup_db: dict,
    ) -> None:
        """Temp dirs for downloaded and rejected albums should be removed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloads = Path(tmpdir) / "downloads"
            downloads.mkdir()

            # Create temp dirs for all albums
            d_id = str(cleanup_db["downloaded_id"])
            r_id = str(cleanup_db["rejected_id"])
            q_id = str(cleanup_db["queued_id"])
            dl_id = str(cleanup_db["downloading_id"])

            (downloads / d_id).mkdir()
            (downloads / r_id).mkdir()
            (downloads / q_id).mkdir()
            (downloads / dl_id).mkdir()

            service = CleanupService(
                db_session_factory=cleanup_db_session_factory,
                downloads_dir=str(downloads),
            )
            count = await service.cleanup_stalled_temp_dirs()

            assert count == 2  # downloaded + rejected
            assert not (downloads / d_id).exists()
            assert not (downloads / r_id).exists()
            assert (downloads / q_id).exists()  # queued — still needed
            assert (downloads / dl_id).exists()  # downloading — still needed

    @pytest.mark.asyncio
    async def test_no_existing_temp_dirs(
        self,
        cleanup_db_session_factory: async_sessionmaker[AsyncSession],
        cleanup_db: dict,
    ) -> None:
        """Should return 0 when no matching temp dirs exist on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloads = Path(tmpdir) / "downloads"
            downloads.mkdir()
            # Don't create any temp dirs

            service = CleanupService(
                db_session_factory=cleanup_db_session_factory,
                downloads_dir=str(downloads),
            )
            count = await service.cleanup_stalled_temp_dirs()
            assert count == 0


class TestRunAll:
    """Integration tests for run_all."""

    @pytest.mark.asyncio
    async def test_run_all_returns_summary(self, cleanup_db_session_factory: async_sessionmaker[AsyncSession]) -> None:
        """run_all should return a dict with all three counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloads = Path(tmpdir) / "downloads"
            downloads.mkdir()
            cache = Path(tmpdir) / "artwork_cache"
            cache.mkdir()

            # Create an empty download dir
            (downloads / "empty-1").mkdir()

            service = CleanupService(
                db_session_factory=cleanup_db_session_factory,
                downloads_dir=str(downloads),
                cache_dir=str(cache),
            )
            result = await service.run_all()

            assert isinstance(result, dict)
            assert "empty_dirs_removed" in result
            assert "cache_files_removed" in result
            assert "stalled_dirs_removed" in result
            assert result["empty_dirs_removed"] == 1
            assert result["cache_files_removed"] == 0
            assert result["stalled_dirs_removed"] == 0
