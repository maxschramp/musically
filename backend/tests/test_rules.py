"""Tests for the rule engine (R1-R7)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.album import Album, AlbumStatus, QueueType
from app.models.artist import Artist
from app.models.playlist import Playlist, PlaylistType
from app.models.playlist_track import PlaylistTrack
from app.models.setting import Setting
from app.models.track_play import TrackPlay
from app.services.rules import RuleEngine, RuleResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_setting(db: AsyncSession, key: str, value: str, category: str = "thresholds") -> None:
    """Insert or update a setting."""
    stmt = select(Setting).where(Setting.key == key)
    result = await db.execute(stmt)
    setting = result.scalar()
    if setting:
        setting.value = value
    else:
        db.add(Setting(key=key, value=value, description="", category=category))
    await db.commit()


async def _seed_thresholds(db: AsyncSession) -> None:
    """Seed the rule engine threshold settings."""
    await _seed_setting(db, "album_play_threshold", "3")
    await _seed_setting(db, "artist_subscribe_play_threshold", "10")
    await _seed_setting(db, "library_albums_subscribe_threshold", "2")


def _make_track_play(
    track_name: str,
    artist_name: str,
    album_name: str,
    played_at: datetime | None = None,
) -> TrackPlay:
    """Create a TrackPlay instance (not persisted)."""
    return TrackPlay(
        track_name=track_name,
        artist_name=artist_name,
        album_name=album_name,
        album_mbid=None,
        artist_mbid=None,
        played_at=played_at or datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# R1: Play count → auto queue
# ---------------------------------------------------------------------------


class TestR1:
    """Tests for R1 — play count threshold triggers auto queue."""

    @pytest.mark.asyncio
    async def test_r1_play_count_triggers_auto_queue(self, db_session: AsyncSession) -> None:
        """Album with enough TrackPlays should be queued."""
        await _seed_thresholds(db_session)

        # Seed 5 TrackPlay records for the same album (threshold=3)
        for i in range(5):
            db_session.add(_make_track_play(f"Track {i}", "Artist A", "Album X"))
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 1
        assert "R1" in result.rules_fired

        # Verify album was created
        stmt = select(Album).where(
            Album.artist_name == "Artist A",
            Album.title == "Album X",
        )
        album_result = await db_session.execute(stmt)
        album = album_result.scalar()
        assert album is not None
        assert album.status == AlbumStatus.QUEUED
        assert album.queue_type == QueueType.AUTO
        assert album.reason == "5 plays"
        assert album.play_count == 5

    @pytest.mark.asyncio
    async def test_r1_below_threshold_no_action(self, db_session: AsyncSession) -> None:
        """Albums below threshold should not be queued."""
        await _seed_thresholds(db_session)

        # Seed only 2 TrackPlays (threshold=3)
        for i in range(2):
            db_session.add(_make_track_play(f"Track {i}", "Artist A", "Album X"))
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 0
        assert result.albums_queued_manual == 0

        # Verify no album was created
        stmt = select(Album).where(
            Album.artist_name == "Artist A",
            Album.title == "Album X",
        )
        album_result = await db_session.execute(stmt)
        album = album_result.scalar()
        assert album is None

    @pytest.mark.asyncio
    async def test_r1_already_queued_skipped(self, db_session: AsyncSession) -> None:
        """Albums already queued should not be re-queued."""
        await _seed_thresholds(db_session)

        # Create an album already in queued state
        existing = Album(
            title="Album X",
            artist_name="Artist A",
            status=AlbumStatus.QUEUED,
            queue_type=QueueType.AUTO,
            reason="existing",
            play_count=3,
        )
        db_session.add(existing)
        await db_session.commit()

        # Add 5 TrackPlays
        for i in range(5):
            db_session.add(_make_track_play(f"Track {i}", "Artist A", "Album X"))
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        # Should not duplicate — album already queued
        assert result.albums_queued_auto == 0

        # Verify only one album row exists
        stmt = select(Album).where(
            Album.artist_name == "Artist A",
            Album.title == "Album X",
        )
        album_result = await db_session.execute(stmt)
        albums = album_result.scalars().all()
        assert len(albums) == 1

    @pytest.mark.asyncio
    async def test_r1_already_downloaded_skipped(self, db_session: AsyncSession) -> None:
        """Albums already downloaded should not be re-queued."""
        await _seed_thresholds(db_session)

        existing = Album(
            title="Album X",
            artist_name="Artist A",
            status=AlbumStatus.DOWNLOADED,
            queue_type=QueueType.AUTO,
            reason="already done",
            play_count=10,
        )
        db_session.add(existing)
        await db_session.commit()

        for i in range(5):
            db_session.add(_make_track_play(f"Track {i}", "Artist A", "Album X"))
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 0  # already downloaded, skip

    @pytest.mark.asyncio
    async def test_r1_rejected_gets_requeued(self, db_session: AsyncSession) -> None:
        """A previously rejected album that now meets threshold should be re-queued."""
        await _seed_thresholds(db_session)

        existing = Album(
            title="Album X",
            artist_name="Artist A",
            status=AlbumStatus.REJECTED,
            queue_type=QueueType.MANUAL,
            reason="was rejected",
            play_count=2,
        )
        db_session.add(existing)
        await db_session.commit()

        for i in range(5):
            db_session.add(_make_track_play(f"Track {i}", "Artist A", "Album X"))
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 1
        assert "R1" in result.rules_fired

        # Refresh and verify status updated
        await db_session.refresh(existing)
        assert existing.status == AlbumStatus.QUEUED
        assert existing.queue_type == QueueType.AUTO
        assert existing.play_count == 5

    @pytest.mark.asyncio
    async def test_r1_empty_album_name_skipped(self, db_session: AsyncSession) -> None:
        """TrackPlays with empty album_name should be ignored."""
        await _seed_thresholds(db_session)

        # TrackPlays with empty album_name (e.g. "now playing")
        for i in range(5):
            tp = _make_track_play(f"Track {i}", "Artist A", "")
            db_session.add(tp)
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 0


# ---------------------------------------------------------------------------
# R2: Seasonal playlist → auto queue
# ---------------------------------------------------------------------------


class TestR2:
    """Tests for R2 — seasonal playlists trigger auto queue."""

    @pytest.mark.asyncio
    async def test_r2_seasonal_playlist_triggers_queue(self, db_session: AsyncSession) -> None:
        """Tracks from an active seasonal playlist should be queued."""
        await _seed_thresholds(db_session)

        # Create a seasonal playlist
        playlist = Playlist(
            spotify_id="spotify:playlist:123",
            name="Winter 2025",
            playlist_type=PlaylistType.SEASONAL,
            is_active=True,
        )
        db_session.add(playlist)
        await db_session.flush()

        # Add tracks to the playlist
        tracks = [
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="Snow Song",
                artist_name="Frosty",
                album_name="Winter Vibes",
                spotify_uri="spotify:track:1",
            ),
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="Cold Nights",
                artist_name="Frosty",
                album_name="Winter Vibes",  # same album
                spotify_uri="spotify:track:2",
            ),
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="Fireplace",
                artist_name="Cozy",
                album_name="Warm Inside",
                spotify_uri="spotify:track:3",
            ),
        ]
        db_session.add_all(tracks)
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        # Two unique albums from the playlist
        assert result.albums_queued_auto == 2
        assert "R2" in result.rules_fired

        # Verify both albums were created
        stmt = select(Album).where(Album.queue_type == QueueType.AUTO)
        albums_result = await db_session.execute(stmt)
        albums = albums_result.scalars().all()
        assert len(albums) == 2
        titles = {a.title for a in albums}
        assert titles == {"Winter Vibes", "Warm Inside"}
        for a in albums:
            assert a.status == AlbumStatus.QUEUED
            assert a.queue_type == QueueType.AUTO
            assert "Winter 2025" in a.reason

    @pytest.mark.asyncio
    async def test_r2_non_seasonal_playlist_ignored(self, db_session: AsyncSession) -> None:
        """Discover/other playlists should NOT trigger R2."""
        await _seed_thresholds(db_session)

        playlist = Playlist(
            spotify_id="spotify:playlist:456",
            name="Discover Weekly",
            playlist_type=PlaylistType.DISCOVER,
            is_active=True,
        )
        db_session.add(playlist)
        await db_session.flush()

        db_session.add(
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="New Hit",
                artist_name="Hot Artist",
                album_name="Debut Album",
                spotify_uri="spotify:track:10",
            )
        )
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        # R2 only triggers on seasonal playlists
        assert result.albums_queued_auto == 0

    @pytest.mark.asyncio
    async def test_r2_inactive_playlist_ignored(self, db_session: AsyncSession) -> None:
        """Inactive seasonal playlists should be ignored."""
        await _seed_thresholds(db_session)

        playlist = Playlist(
            spotify_id="spotify:playlist:789",
            name="Spring 2024",
            playlist_type=PlaylistType.SEASONAL,
            is_active=False,
        )
        db_session.add(playlist)
        await db_session.flush()

        db_session.add(
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="Old Song",
                artist_name="Forgotten",
                album_name="Past Season",
                spotify_uri="spotify:track:99",
            )
        )
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 0

    @pytest.mark.asyncio
    async def test_r2_already_exists_skipped(self, db_session: AsyncSession) -> None:
        """Album already in DB should not be duplicated by R2."""
        await _seed_thresholds(db_session)

        # Pre-create the album
        existing = Album(
            title="Winter Vibes",
            artist_name="Frosty",
            status=AlbumStatus.QUEUED,
            queue_type=QueueType.AUTO,
            reason="5 plays",
            play_count=5,
        )
        db_session.add(existing)
        await db_session.commit()

        playlist = Playlist(
            spotify_id="spotify:playlist:123",
            name="Winter 2025",
            playlist_type=PlaylistType.SEASONAL,
            is_active=True,
        )
        db_session.add(playlist)
        await db_session.flush()

        db_session.add(
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="Snow Song",
                artist_name="Frosty",
                album_name="Winter Vibes",
                spotify_uri="spotify:track:1",
            )
        )
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        # Only one album should exist
        assert result.albums_queued_auto == 0  # skipped because already in pipeline

        stmt = select(Album).where(
            Album.artist_name == "Frosty",
            Album.title == "Winter Vibes",
        )
        albums = (await db_session.execute(stmt)).scalars().all()
        assert len(albums) == 1

    @pytest.mark.asyncio
    async def test_r2_empty_album_name_skipped(self, db_session: AsyncSession) -> None:
        """Playlist tracks with empty album_name should be skipped."""
        await _seed_thresholds(db_session)

        playlist = Playlist(
            spotify_id="spotify:playlist:123",
            name="Winter 2025",
            playlist_type=PlaylistType.SEASONAL,
            is_active=True,
        )
        db_session.add(playlist)
        await db_session.flush()

        db_session.add(
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="Unknown Track",
                artist_name="Mystery",
                album_name="",  # empty
                spotify_uri="spotify:track:0",
            )
        )
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 0


# ---------------------------------------------------------------------------
# R3: Artist play count → subscribe
# ---------------------------------------------------------------------------


class TestR3:
    """Tests for R3 — artist play count triggers subscription."""

    @pytest.mark.asyncio
    async def test_r3_artist_play_count_subscribes(self, db_session: AsyncSession) -> None:
        """Artist with high total_play_count should be subscribed."""
        await _seed_thresholds(db_session)

        artist = Artist(
            name="Prolific Artist",
            subscribed=False,
            total_play_count=15,
        )
        db_session.add(artist)
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.artists_subscribed == 1
        assert "R3" in result.rules_fired

        await db_session.refresh(artist)
        assert artist.subscribed is True
        assert artist.subscription_source == "auto_play_count"

    @pytest.mark.asyncio
    async def test_r3_below_threshold_no_action(self, db_session: AsyncSession) -> None:
        """Artist below threshold should not be subscribed."""
        await _seed_thresholds(db_session)

        artist = Artist(
            name="Niche Artist",
            subscribed=False,
            total_play_count=5,  # below threshold of 10
        )
        db_session.add(artist)
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.artists_subscribed == 0
        await db_session.refresh(artist)
        assert artist.subscribed is False

    @pytest.mark.asyncio
    async def test_r3_already_subscribed_skipped(self, db_session: AsyncSession) -> None:
        """Already-subscribed artist should not be modified."""
        await _seed_thresholds(db_session)

        artist = Artist(
            name="Already Fan",
            subscribed=True,
            subscription_source="manual",
            total_play_count=50,
        )
        db_session.add(artist)
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.artists_subscribed == 0
        await db_session.refresh(artist)
        assert artist.subscription_source == "manual"  # unchanged


# ---------------------------------------------------------------------------
# R4: Library size → subscribe
# ---------------------------------------------------------------------------


class TestR4:
    """Tests for R4 — library size triggers subscription."""

    @pytest.mark.asyncio
    async def test_r4_library_size_subscribes(self, db_session: AsyncSession) -> None:
        """Artist with many albums_in_library should be subscribed."""
        await _seed_thresholds(db_session)

        artist = Artist(
            name="Collector Artist",
            subscribed=False,
            albums_in_library=5,
        )
        db_session.add(artist)
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.artists_subscribed == 1
        assert "R4" in result.rules_fired

        await db_session.refresh(artist)
        assert artist.subscribed is True
        assert artist.subscription_source == "auto_library_size"

    @pytest.mark.asyncio
    async def test_r4_below_threshold_no_action(self, db_session: AsyncSession) -> None:
        """Artist with too few albums should not be subscribed."""
        await _seed_thresholds(db_session)

        artist = Artist(
            name="One Hit Wonder",
            subscribed=False,
            albums_in_library=1,  # below threshold of 2
        )
        db_session.add(artist)
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.artists_subscribed == 0
        await db_session.refresh(artist)
        assert artist.subscribed is False

    @pytest.mark.asyncio
    async def test_r4_already_subscribed_skipped(self, db_session: AsyncSession) -> None:
        """Already-subscribed artist should not be modified by R4."""
        await _seed_thresholds(db_session)

        artist = Artist(
            name="Library Fan",
            subscribed=True,
            subscription_source="auto_play_count",
            albums_in_library=10,
        )
        db_session.add(artist)
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.artists_subscribed == 0
        await db_session.refresh(artist)
        assert artist.subscription_source == "auto_play_count"  # unchanged


# ---------------------------------------------------------------------------
# R5-R7: Stubs
# ---------------------------------------------------------------------------


class TestStubs:
    """Tests for R5/R6/R7 stub behavior."""

    @pytest.mark.asyncio
    async def test_r5_r6_r7_stubs_dont_crash(self, db_session: AsyncSession) -> None:
        """Stubs (R5/R7) should not crash the rule engine. R6 is now implemented."""
        await _seed_thresholds(db_session)

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        # R5 and R7 stubs should add error messages but not crash
        error_texts = " ".join(result.errors)
        assert "R5" in error_texts
        assert "R7" in error_texts
        assert "not yet implemented" in error_texts
        # R6 is implemented — should NOT appear in errors
        assert "R6" not in error_texts


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Tests for case-insensitive deduplication."""

    @pytest.mark.asyncio
    async def test_deduplication_case_insensitive(self, db_session: AsyncSession) -> None:
        """Different casing of the same artist/album should not create duplicates."""
        await _seed_thresholds(db_session)

        # Seed with lowercase
        for i in range(5):
            db_session.add(_make_track_play(
                f"Track {i}", "artist a", "album x",
            ))
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 1
        assert "R1" in result.rules_fired

        # Now add more TrackPlays with different casing
        for i in range(3):
            db_session.add(_make_track_play(
                f"Track {i + 10}", "ARTIST A", "ALBUM X",
            ))
        await db_session.commit()

        # Run again — should not create a second album
        engine2 = RuleEngine(db_session)
        result2 = await engine2.evaluate()

        # The album is already queued, so R1 should not fire again
        assert result2.albums_queued_auto == 0

        # Only one album should exist
        stmt = select(Album).where(Album.title.ilike("album x"))
        albums = (await db_session.execute(stmt)).scalars().all()
        assert len(albums) == 1

    @pytest.mark.asyncio
    async def test_deduplication_cross_rule(self, db_session: AsyncSession) -> None:
        """R1 and R2 should not create duplicate albums for the same artist/album."""
        await _seed_thresholds(db_session)

        # R1: Seed TrackPlays
        for i in range(5):
            db_session.add(_make_track_play(
                f"Track {i}", "Frosty", "Winter Vibes",
            ))
        await db_session.commit()

        # R2: Create seasonal playlist with same album
        playlist = Playlist(
            spotify_id="spotify:playlist:123",
            name="Winter 2025",
            playlist_type=PlaylistType.SEASONAL,
            is_active=True,
        )
        db_session.add(playlist)
        await db_session.flush()

        db_session.add(
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="Snow Song",
                artist_name="Frosty",
                album_name="Winter Vibes",
                spotify_uri="spotify:track:1",
            )
        )
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        # R1 queues it; R2 sees it already queued and skips
        # Total auto queues should be exactly 1
        assert result.albums_queued_auto == 1
        assert "R1" in result.rules_fired
        # R2 should not fire (the album was already queued by R1)
        assert "R2" not in result.rules_fired

        # Only one album should exist
        stmt = select(Album).where(
            Album.artist_name.ilike("frosty"),
            Album.title.ilike("winter vibes"),
        )
        albums = (await db_session.execute(stmt)).scalars().all()
        assert len(albums) == 1


# ---------------------------------------------------------------------------
# Combined rules
# ---------------------------------------------------------------------------


class TestCombined:
    """Tests for multiple rules firing in a single evaluation."""

    @pytest.mark.asyncio
    async def test_r1_and_r3_fire_together(self, db_session: AsyncSession) -> None:
        """R1 (auto queue) and R3 (subscribe) can both fire."""
        await _seed_thresholds(db_session)

        # TrackPlays for album
        for i in range(5):
            db_session.add(_make_track_play(f"Track {i}", "Big Artist", "Hit Album"))
        await db_session.commit()

        # Artist with high play count
        artist = Artist(
            name="Big Artist",
            subscribed=False,
            total_play_count=15,
        )
        db_session.add(artist)
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 1
        assert result.artists_subscribed == 1
        assert "R1" in result.rules_fired
        assert "R3" in result.rules_fired

    @pytest.mark.asyncio
    async def test_empty_db_no_actions(self, db_session: AsyncSession) -> None:
        """Rule engine on an empty DB should produce no actions."""
        await _seed_thresholds(db_session)

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 0
        assert result.albums_queued_manual == 0
        assert result.artists_subscribed == 0
        assert len(result.rules_fired) == 0

    @pytest.mark.asyncio
    async def test_default_thresholds_when_no_settings(self, db_session: AsyncSession) -> None:
        """If no threshold settings exist, defaults should be used."""
        # Do NOT seed thresholds — engine uses built-in defaults

        # Seed 10 TrackPlays (default threshold is 5)
        for i in range(10):
            db_session.add(_make_track_play(f"Track {i}", "Artist A", "Album X"))
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 1
        assert "R1" in result.rules_fired

    @pytest.mark.asyncio
    async def test_invalid_setting_falls_back_to_default(self, db_session: AsyncSession) -> None:
        """A non-integer setting value should fall back to the default."""
        await _seed_setting(db_session, "album_play_threshold", "not_a_number")
        await _seed_setting(db_session, "artist_subscribe_play_threshold", "20")
        await _seed_setting(db_session, "library_albums_subscribe_threshold", "3")

        # Seed 10 TrackPlays (default threshold is 5; "not_a_number" falls back to 5)
        for i in range(10):
            db_session.add(_make_track_play(f"Track {i}", "Artist A", "Album X"))
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_auto == 1  # still works with default of 5
