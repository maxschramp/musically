"""Tests for the download pipeline — Qobuz + beets integration.

Tests the full pipeline with mocked Qobuz and beets services.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.album import Album, AlbumStatus, QueueType
from app.models.setting import Setting
from app.services.beets import BeetsResult
from app.services.notifications import NotificationService
from app.services.pipeline import DownloadPipeline, PipelineResult
from app.services.qobuz import QobuzAlbum, QobuzService, QobuzTrack

# Import the test engine from conftest to create proper async session factories
from tests.conftest import test_engine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_qobuz() -> MagicMock:
    q = MagicMock(spec=QobuzService)
    q.search_album_with_tracks = AsyncMock()
    q.download_album = AsyncMock()
    q.close = AsyncMock()
    return q


@pytest.fixture
def mock_beets() -> MagicMock:
    b = MagicMock()
    b.import_album = AsyncMock()
    return b


@pytest.fixture
def mock_notifier() -> MagicMock:
    n = MagicMock(spec=NotificationService)
    n.notify_download = AsyncMock(return_value=True)
    n.notify_stalled = AsyncMock(return_value=True)
    n.notify_error = AsyncMock(return_value=True)
    n.notify_queued_manual = AsyncMock(return_value=True)
    n.close = AsyncMock()
    return n


def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a test async session factory using the shared test engine."""
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
def pipeline(
    mock_qobuz: MagicMock,
    mock_beets: MagicMock,
    mock_notifier: MagicMock,
) -> DownloadPipeline:
    """Create a pipeline with mocked services and a test DB session factory."""
    return DownloadPipeline(
        db_session_factory=_make_session_factory(),
        qobuz=mock_qobuz,
        beets=mock_beets,
        notifier=mock_notifier,
    )


async def _create_test_album(db: AsyncSession, **overrides) -> Album:
    """Create and return a test Album record."""
    album = Album(
        id=uuid.uuid4(),
        title="Test Album",
        artist_name="Test Artist",
        status=AlbumStatus.QUEUED,
        queue_type=QueueType.AUTO,
        reason="5+ plays",
        play_count=5,
        **overrides,
    )
    db.add(album)
    await db.commit()
    await db.refresh(album)
    return album


async def _seed_setting_value(db: AsyncSession, key: str, value: str) -> None:
    from sqlalchemy import select
    result = await db.execute(select(Setting).where(Setting.key == key))
    s = result.scalar_one_or_none()
    if s:
        s.value = value
    else:
        db.add(Setting(key=key, value=value, category="notifications"))
    await db.commit()


# ---------------------------------------------------------------------------
# Full pipeline success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_album_success(
    mock_qobuz: MagicMock,
    mock_beets: MagicMock,
    mock_notifier: MagicMock,
    db_session: AsyncSession,
) -> None:
    """Full pipeline should download, tag, notify, and mark as downloaded."""
    pipeline = DownloadPipeline(
        db_session_factory=_make_session_factory(),
        qobuz=mock_qobuz,
        beets=mock_beets,
        notifier=mock_notifier,
    )

    album = await _create_test_album(db_session)
    await _seed_setting_value(db_session, "notify_on_download", "true")
    await _seed_setting_value(db_session, "notify_on_stalled", "true")
    await _seed_setting_value(db_session, "notify_on_error", "true")
    await _seed_setting_value(db_session, "qobuz_temp_download_directory", "/tmp/downloads")
    await _seed_setting_value(db_session, "music_library_directory", "/music/library")

    mock_qobuz.search_album_with_tracks.return_value = QobuzAlbum(
        qobuz_id="123",
        title="Test Album",
        artist_name="Test Artist",
        tracks=[
            QobuzTrack(track_id=1, title="Track 1", track_number=1, duration=200),
            QobuzTrack(track_id=2, title="Track 2", track_number=2, duration=250),
        ],
    )
    mock_qobuz.download_album.return_value = True
    mock_beets.import_album.return_value = BeetsResult(
        success=True, matched_album="Test Artist - Test Album", files_imported=2,
    )

    result = await pipeline.process_album(album.id)

    assert result.success is True
    assert result.status == AlbumStatus.DOWNLOADED

    # Verify DB state
    from sqlalchemy import select
    stmt = select(Album).where(Album.id == album.id)
    res = await db_session.execute(stmt)
    updated = res.scalar_one()
    assert updated.status == AlbumStatus.DOWNLOADED
    assert updated.downloaded_at is not None
    assert updated.qobuz_id == "123"

    # Verify notifications
    mock_notifier.notify_download.assert_called_once()


# ---------------------------------------------------------------------------
# Pipeline: album not found on Qobuz
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_album_not_found_on_qobuz(
    mock_qobuz: MagicMock,
    mock_beets: MagicMock,
    mock_notifier: MagicMock,
    db_session: AsyncSession,
) -> None:
    """When Qobuz can't find the album, should mark as stalled and schedule retry."""
    pipeline = DownloadPipeline(
        db_session_factory=_make_session_factory(),
        qobuz=mock_qobuz,
        beets=mock_beets,
        notifier=mock_notifier,
    )

    album = await _create_test_album(db_session)
    await _seed_setting_value(db_session, "notify_on_stalled", "true")

    mock_qobuz.search_album_with_tracks.return_value = None

    result = await pipeline.process_album(album.id)

    assert result.success is False
    assert result.status == AlbumStatus.STALLED
    assert "not found" in result.message.lower()

    # Verify DB state
    from sqlalchemy import select
    stmt = select(Album).where(Album.id == album.id)
    res = await db_session.execute(stmt)
    updated = res.scalar_one()
    assert updated.status == AlbumStatus.STALLED
    assert updated.next_retry_at is not None

    # Should have called stalled notification
    mock_notifier.notify_stalled.assert_called_once()


# ---------------------------------------------------------------------------
# Pipeline: download fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_album_download_fails(
    mock_qobuz: MagicMock,
    mock_beets: MagicMock,
    mock_notifier: MagicMock,
    db_session: AsyncSession,
) -> None:
    """When download fails, should stall and notify error."""
    pipeline = DownloadPipeline(
        db_session_factory=_make_session_factory(),
        qobuz=mock_qobuz,
        beets=mock_beets,
        notifier=mock_notifier,
    )

    album = await _create_test_album(db_session)
    await _seed_setting_value(db_session, "notify_on_error", "true")

    mock_qobuz.search_album_with_tracks.return_value = QobuzAlbum(
        qobuz_id="123", title="Test Album", artist_name="Test Artist",
    )
    mock_qobuz.download_album.return_value = False

    result = await pipeline.process_album(album.id)

    assert result.success is False
    assert result.status == AlbumStatus.STALLED
    mock_notifier.notify_error.assert_called_once()


# ---------------------------------------------------------------------------
# Pipeline: beets import fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_album_beets_fails(
    mock_qobuz: MagicMock,
    mock_beets: MagicMock,
    mock_notifier: MagicMock,
    db_session: AsyncSession,
) -> None:
    """When beets import fails, should stall and notify error."""
    pipeline = DownloadPipeline(
        db_session_factory=_make_session_factory(),
        qobuz=mock_qobuz,
        beets=mock_beets,
        notifier=mock_notifier,
    )

    album = await _create_test_album(db_session)
    await _seed_setting_value(db_session, "notify_on_error", "true")

    mock_qobuz.search_album_with_tracks.return_value = QobuzAlbum(
        qobuz_id="123", title="Test Album", artist_name="Test Artist",
    )
    mock_qobuz.download_album.return_value = True
    mock_beets.import_album.return_value = BeetsResult(
        success=False, errors=["Tagging failed: no match"],
    )

    result = await pipeline.process_album(album.id)

    assert result.success is False
    assert result.status == AlbumStatus.STALLED
    assert "beets" in result.message.lower()
    mock_notifier.notify_error.assert_called_once()


# ---------------------------------------------------------------------------
# Retry scheduling
# ---------------------------------------------------------------------------

def test_schedule_retry_first_retry() -> None:
    """First retry should use the first interval (default 24h)."""
    pipeline = DownloadPipeline.__new__(DownloadPipeline)
    pipeline._settings = {}
    next_retry = pipeline.schedule_retry(retry_count=0)
    expected = datetime.now(timezone.utc) + timedelta(hours=24)
    # Allow a small delta for execution time
    assert abs((next_retry - expected).total_seconds()) < 5


def test_schedule_retry_second_retry() -> None:
    """Second retry uses 72h interval."""
    pipeline = DownloadPipeline.__new__(DownloadPipeline)
    pipeline._settings = {}
    next_retry = pipeline.schedule_retry(retry_count=1)
    expected = datetime.now(timezone.utc) + timedelta(hours=72)
    assert abs((next_retry - expected).total_seconds()) < 5


def test_schedule_retry_exceeds_list() -> None:
    """If retry_count exceeds list length, use last interval (336h)."""
    pipeline = DownloadPipeline.__new__(DownloadPipeline)
    pipeline._settings = {}
    next_retry = pipeline.schedule_retry(retry_count=10)
    expected = datetime.now(timezone.utc) + timedelta(hours=336)
    assert abs((next_retry - expected).total_seconds()) < 5


def test_schedule_retry_custom_intervals() -> None:
    """Custom intervals from settings should be respected."""
    pipeline = DownloadPipeline.__new__(DownloadPipeline)
    pipeline._settings = {"stalled_retry_intervals_hours": "[1, 2, 3]"}
    next_retry = pipeline.schedule_retry(retry_count=0)
    expected = datetime.now(timezone.utc) + timedelta(hours=1)
    assert abs((next_retry - expected).total_seconds()) < 5


def test_schedule_retry_invalid_json_uses_default() -> None:
    """Invalid JSON in settings should fall back to defaults."""
    pipeline = DownloadPipeline.__new__(DownloadPipeline)
    pipeline._settings = {"stalled_retry_intervals_hours": "not-json"}
    next_retry = pipeline.schedule_retry(retry_count=0)
    expected = datetime.now(timezone.utc) + timedelta(hours=24)
    assert abs((next_retry - expected).total_seconds()) < 5


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_transition_queued_to_downloading(
    mock_qobuz: MagicMock,
    mock_beets: MagicMock,
    mock_notifier: MagicMock,
    db_session: AsyncSession,
) -> None:
    """Album should transition queued → downloading → downloaded."""
    pipeline = DownloadPipeline(
        db_session_factory=_make_session_factory(),
        qobuz=mock_qobuz,
        beets=mock_beets,
        notifier=mock_notifier,
    )

    album = await _create_test_album(db_session, status=AlbumStatus.QUEUED)
    assert album.status == AlbumStatus.QUEUED

    mock_qobuz.search_album_with_tracks.return_value = QobuzAlbum(
        qobuz_id="123", title="Test Album", artist_name="Test Artist",
    )
    mock_qobuz.download_album.return_value = True
    mock_beets.import_album.return_value = BeetsResult(success=True, files_imported=1)

    result = await pipeline.process_album(album.id)

    assert result.success is True
    assert result.status == AlbumStatus.DOWNLOADED

    from sqlalchemy import select
    stmt = select(Album).where(Album.id == album.id)
    res = await db_session.execute(stmt)
    updated = res.scalar_one()
    assert updated.status == AlbumStatus.DOWNLOADED
    assert updated.retry_count == 1  # incremented when processing starts


# ---------------------------------------------------------------------------
# Album not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_album_not_found_in_db(
    mock_qobuz: MagicMock,
    mock_beets: MagicMock,
    mock_notifier: MagicMock,
    db_session: AsyncSession,
) -> None:
    """Should return error result when album ID doesn't exist."""
    pipeline = DownloadPipeline(
        db_session_factory=_make_session_factory(),
        qobuz=mock_qobuz,
        beets=mock_beets,
        notifier=mock_notifier,
    )

    result = await pipeline.process_album(uuid.uuid4())

    assert result.success is False
    assert "not found" in result.message.lower()
