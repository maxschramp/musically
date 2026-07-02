"""Tests for the sync orchestrator and sync router."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting
from app.models.sync_history import SyncHistory
from app.models.track_play import TrackPlay
from app.services.lastfm import LastFMTrack, LastFMResponse, LastFMPagination


# ---------------------------------------------------------------------------
# Helper: seed settings into the DB
# ---------------------------------------------------------------------------

async def _seed_setting(db: AsyncSession, key: str, value: str, category: str = "api_keys") -> None:
    stmt = select(Setting).where(Setting.key == key)
    result = await db.execute(stmt)
    setting = result.scalar()
    if setting:
        setting.value = value
    else:
        db.add(Setting(key=key, value=value, description="", category=category))
    await db.commit()


async def _seed_required_settings(db: AsyncSession) -> None:
    """Seed the minimum settings needed for sync to run."""
    await _seed_setting(db, "lastfm_enabled", "true", "sources")
    await _seed_setting(db, "lastfm_api_key", "test_api_key", "api_keys")
    await _seed_setting(db, "lastfm_username", "testuser", "api_keys")
    await _seed_setting(db, "lastfm_rate_limit_rps", "10.0", "scheduling")
    await _seed_setting(db, "backfill_days", "30", "scheduling")


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_lastfm_track(
    track_name: str,
    artist_name: str,
    album_name: str | None = None,
    played_at: datetime | None = None,
) -> LastFMTrack:
    return LastFMTrack(
        track_name=track_name,
        artist_name=artist_name,
        album_name=album_name,
        track_mbid=None,
        artist_mbid=None,
        played_at=played_at or datetime(2023, 7, 1, 0, 30, tzinfo=timezone.utc),
    )


class TestSyncRouter:
    """Integration tests for sync endpoints."""

    @pytest.mark.asyncio
    async def test_trigger_sync_skipped_no_api_key(self, client: AsyncClient) -> None:
        """Sync should be skipped when no API key is configured."""
        resp = await client.post("/api/sync/trigger")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"
        assert "api" in (data.get("error_message") or "").lower()
        # Rule engine fields should default to 0/null
        assert data["albums_queued_auto"] == 0
        assert data["albums_queued_manual"] == 0
        assert data["artists_subscribed"] == 0
        assert data["rules_fired"] is None

    @pytest.mark.asyncio
    async def test_trigger_sync_skipped_disabled(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Sync should be skipped when lastfm_enabled is false."""
        await _seed_setting(db_session, "lastfm_enabled", "false", "sources")
        await _seed_setting(db_session, "lastfm_api_key", "some_key", "api_keys")

        resp = await client.post("/api/sync/trigger")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"
        assert "enabled" in (data.get("error_message") or "").lower()
        assert data["albums_queued_auto"] == 0
        assert data["albums_queued_manual"] == 0
        assert data["artists_subscribed"] == 0
        assert data["rules_fired"] is None

    @pytest.mark.asyncio
    async def test_trigger_sync_skipped_no_username(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Sync should be skipped when no username is configured."""
        await _seed_setting(db_session, "lastfm_enabled", "true", "sources")
        await _seed_setting(db_session, "lastfm_api_key", "some_key", "api_keys")
        # username stays empty

        resp = await client.post("/api/sync/trigger")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "skipped"
        assert "username" in (data.get("error_message") or "").lower()
        assert data["albums_queued_auto"] == 0
        assert data["albums_queued_manual"] == 0
        assert data["artists_subscribed"] == 0
        assert data["rules_fired"] is None

    @pytest.mark.asyncio
    async def test_trigger_sync_runs_with_credentials(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """With valid settings, sync should attempt to run (may fail gracefully on network)."""
        await _seed_required_settings(db_session)

        # Mock LastFM to return empty tracks (no actual network call)
        with patch(
            "app.services.lastfm.LastFMService.fetch_recent_tracks",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = LastFMResponse(
                tracks=[],
                pagination=LastFMPagination(page=1, total_pages=0, per_page=200, total=0),
            )

            resp = await client.post("/api/sync/trigger")

        assert resp.status_code == 200
        data = resp.json()
        # Should complete with 0 tracks
        assert data["status"] == "completed"
        assert data["tracks_fetched"] == 0
        # Rule engine metrics should be present
        assert "albums_queued_auto" in data
        assert "albums_queued_manual" in data
        assert "artists_subscribed" in data
        assert "rules_fired" in data
        assert data["albums_queued_auto"] == 0
        assert data["albums_queued_manual"] == 0
        assert data["artists_subscribed"] == 0

    @pytest.mark.asyncio
    async def test_sync_history_empty(self, client: AsyncClient) -> None:
        """GET /api/sync/history should return empty list with pagination."""
        resp = await client.get("/api/sync/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["total_pages"] == 1

    @pytest.mark.asyncio
    async def test_sync_history_with_entries(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """After a sync, history should show entries."""
        # Insert a sync history entry directly
        entry = SyncHistory(
            started_at=datetime(2023, 7, 1, 0, 0, tzinfo=timezone.utc),
            completed_at=datetime(2023, 7, 1, 0, 1, tzinfo=timezone.utc),
            status="completed",
            tracks_fetched=50,
            tracks_new=30,
            albums_updated=5,
            artists_updated=3,
            albums_queued_auto=2,
            albums_queued_manual=1,
            artists_subscribed=3,
            rules_fired='["R1","R3","R4"]',
            error_message=None,
        )
        db_session.add(entry)
        await db_session.commit()

        resp = await client.get("/api/sync/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["status"] == "completed"
        assert data["items"][0]["tracks_fetched"] == 50
        assert data["items"][0]["tracks_new"] == 30
        assert data["items"][0]["albums_queued_auto"] == 2
        assert data["items"][0]["albums_queued_manual"] == 1
        assert data["items"][0]["artists_subscribed"] == 3
        assert data["items"][0]["rules_fired"] == ["R1", "R3", "R4"]

    @pytest.mark.asyncio
    async def test_sync_history_pagination(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """Test pagination on sync history."""
        # Insert 5 entries
        for i in range(5):
            entry = SyncHistory(
                started_at=datetime(2023, 7, 1, i, 0, tzinfo=timezone.utc),
                completed_at=datetime(2023, 7, 1, i, 1, tzinfo=timezone.utc),
                status="completed",
                tracks_fetched=i * 10,
                tracks_new=i * 5,
                albums_updated=0,
                artists_updated=0,
                error_message=None,
            )
            db_session.add(entry)
        await db_session.commit()

        # Page 1 with limit 3
        resp = await client.get("/api/sync/history?page=1&limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 3
        assert data["page"] == 1
        assert data["total_pages"] == 2

        # Page 2 with limit 3
        resp = await client.get("/api/sync/history?page=2&limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["page"] == 2


class TestAggregation:
    """Tests for aggregate_plays logic."""

    @pytest.mark.asyncio
    async def test_deduplication(self, db_session: AsyncSession) -> None:
        """New TrackPlay records should be deduplicated against existing ones."""
        from app.services.aggregator import aggregate_plays
        from app.services.lastfm import LastFMService

        # Pre-insert an existing track play
        played_at = datetime(2023, 7, 1, 0, 30, tzinfo=timezone.utc)
        existing = TrackPlay(
            track_name="Existing Song",
            artist_name="Existing Artist",
            album_name="Existing Album",
            album_mbid=None,
            artist_mbid=None,
            played_at=played_at,
        )
        db_session.add(existing)
        await db_session.commit()

        # Mock LastFM service returning one duplicate and one new track
        mock_service = LastFMService(api_key="key", user="user", rate_limit_rps=10.0)
        mock_service.fetch_all_recent = AsyncMock(
            return_value=[
                _make_lastfm_track("Existing Song", "Existing Artist", "Existing Album", played_at),
                _make_lastfm_track("New Song", "New Artist", "New Album", datetime(2023, 7, 1, 1, 0, tzinfo=timezone.utc)),
            ]
        )

        result = await aggregate_plays(db=db_session, lastfm=mock_service)

        assert result.tracks_fetched == 2
        assert result.tracks_new == 1  # only the new one

        # Verify only 2 total (1 existing + 1 new)
        stmt = select(func.count(TrackPlay.id))
        count_result = await db_session.execute(stmt)
        total_plays = count_result.scalar()
        assert total_plays == 2

    @pytest.mark.asyncio
    async def test_album_play_count_update(self, db_session: AsyncSession) -> None:
        """Aggregation should update Album.play_count for matching albums."""
        from app.services.aggregator import aggregate_plays
        from app.services.lastfm import LastFMService
        from app.models.album import Album, AlbumStatus, QueueType

        # Pre-create an album
        album = Album(
            title="Test Album",
            artist_name="Test Artist",
            status=AlbumStatus.QUEUED,
            queue_type=QueueType.AUTO,
            reason="test",
            play_count=3,
        )
        db_session.add(album)
        await db_session.commit()

        # Mock LastFM returning 2 plays on this album
        mock_service = LastFMService(api_key="key", user="user", rate_limit_rps=10.0)
        mock_service.fetch_all_recent = AsyncMock(
            return_value=[
                _make_lastfm_track("Song 1", "Test Artist", "Test Album"),
                _make_lastfm_track("Song 2", "Test Artist", "Test Album"),
            ]
        )

        result = await aggregate_plays(db=db_session, lastfm=mock_service)

        assert result.albums_updated == 1

        # Verify album play_count was incremented
        await db_session.refresh(album)
        assert album.play_count == 5  # 3 + 2

    @pytest.mark.asyncio
    async def test_artist_play_count_update(self, db_session: AsyncSession) -> None:
        """Aggregation should update Artist.total_play_count for matching artists."""
        from app.services.aggregator import aggregate_plays
        from app.services.lastfm import LastFMService
        from app.models.artist import Artist

        # Pre-create an artist
        artist = Artist(
            name="Test Artist",
            subscribed=False,
            total_play_count=10,
        )
        db_session.add(artist)
        await db_session.commit()

        # Mock LastFM returning 5 plays by this artist
        mock_service = LastFMService(api_key="key", user="user", rate_limit_rps=10.0)
        mock_service.fetch_all_recent = AsyncMock(
            return_value=[
                _make_lastfm_track(f"Song {i}", "Test Artist", f"Album {i}")
                for i in range(5)
            ]
        )

        result = await aggregate_plays(db=db_session, lastfm=mock_service)

        assert result.artists_updated == 1

        # Verify artist total_play_count was incremented
        await db_session.refresh(artist)
        assert artist.total_play_count == 15  # 10 + 5

    @pytest.mark.asyncio
    async def test_empty_fetch(self, db_session: AsyncSession) -> None:
        """Empty LastFM fetch should produce zero results."""
        from app.services.aggregator import aggregate_plays
        from app.services.lastfm import LastFMService

        mock_service = LastFMService(api_key="key", user="user", rate_limit_rps=10.0)
        mock_service.fetch_all_recent = AsyncMock(return_value=[])

        result = await aggregate_plays(db=db_session, lastfm=mock_service)

        assert result.tracks_fetched == 0
        assert result.tracks_new == 0
        assert result.albums_updated == 0
        assert result.artists_updated == 0


class TestOrchestratorBackfill:
    """Tests for backfill mode detection."""

    @pytest.mark.asyncio
    async def test_backfill_mode_no_track_plays(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """When no TrackPlay records exist, backfill mode should be used."""
        await _seed_required_settings(db_session)

        # No TrackPlay records — should trigger backfill
        with patch(
            "app.services.lastfm.LastFMService.fetch_recent_tracks",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.return_value = LastFMResponse(
                tracks=[],
                pagination=LastFMPagination(page=1, total_pages=0, per_page=200, total=0),
            )

            resp = await client.post("/api/sync/trigger")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_sync_history_recorded_on_skip(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Skipped syncs should still record a SyncHistory entry."""
        # Don't seed required settings — should skip

        resp = await client.post("/api/sync/trigger")
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

        # Verify a history entry exists
        stmt = select(func.count(SyncHistory.id))
        result = await db_session.execute(stmt)
        count = result.scalar()
        assert count == 1

    @pytest.mark.asyncio
    async def test_sync_history_recorded_on_failure(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Failed syncs should record a SyncHistory entry with status 'failed'."""
        await _seed_required_settings(db_session)

        # Make LastFM throw an exception
        with patch(
            "app.services.lastfm.LastFMService.fetch_recent_tracks",
            new_callable=AsyncMock,
        ) as mock_fetch:
            mock_fetch.side_effect = RuntimeError("Network unavailable")

            resp = await client.post("/api/sync/trigger")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert "Network unavailable" in (data.get("error_message") or "")

        # Verify history entry
        stmt = select(SyncHistory).order_by(SyncHistory.started_at.desc()).limit(1)
        result = await db_session.execute(stmt)
        entry = result.scalar()
        assert entry is not None
        assert entry.status == "failed"
        assert "Network unavailable" in (entry.error_message or "")


class TestSettingEndpoint:
    """Verify lastfm settings appear in /api/settings."""

    @pytest.mark.asyncio
    async def test_lastfm_settings_appear(self, client: AsyncClient) -> None:
        """GET /api/settings should include lastfm_username and lastfm_api_key."""
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()

        # Flatten all settings into a key lookup
        all_keys: set[str] = set()
        for category_items in data.values():
            for item in category_items:
                all_keys.add(item["key"])

        assert "lastfm_api_key" in all_keys
        assert "lastfm_username" in all_keys
