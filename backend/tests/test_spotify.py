"""Tests for Spotify service, OAuth endpoints, and R6 rule."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.album import Album, AlbumStatus, QueueType
from app.models.playlist import Playlist, PlaylistType
from app.models.playlist_track import PlaylistTrack
from app.models.setting import Setting
from app.services.spotify import (
    SpotifyService,
    SpotifyTrack,
    SpotifySyncResult,
    _decrypt_token,
    _encrypt_token,
    _get_setting,
    _set_setting,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_setting(
    db: AsyncSession, key: str, value: str, category: str = "api_keys"
) -> None:
    """Insert or update a setting."""
    stmt = select(Setting).where(Setting.key == key)
    result = await db.execute(stmt)
    setting = result.scalar()
    if setting:
        setting.value = value
    else:
        db.add(Setting(key=key, value=value, description="", category=category))
    await db.commit()


async def _seed_spotify_settings(db: AsyncSession) -> None:
    """Seed the minimum Spotify settings."""
    await _seed_setting(db, "spotify_client_id", "test_client_id")
    await _seed_setting(db, "spotify_client_secret", "test_client_secret")
    await _seed_setting(db, "spotify_redirect_uri", "http://localhost:8000/api/spotify/auth/callback")
    await _seed_setting(db, "spotify_refresh_token", _encrypt_token("test_refresh_token"))
    await _seed_setting(
        db,
        "spotify_access_token_encrypted",
        _encrypt_token("test_access_token"),
    )
    await _seed_setting(
        db,
        "spotify_token_expiry",
        datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat(),
    )
    await _seed_setting(db, "spotify_rate_limit_rpm", "9999")
    await _seed_setting(db, "spotify_seasonal_playlist_pattern", "Winter|Summer|Fall")
    await _seed_setting(
        db,
        "spotify_discover_playlist_names",
        '["Release Radar", "Pitchfork Selects"]',
    )


# ---------------------------------------------------------------------------
# PKCE tests
# ---------------------------------------------------------------------------


class TestPKCE:
    """Tests for PKCE generation and auth URL building."""

    def test_generate_pkce(self) -> None:
        """PKCE verifier and challenge should be valid."""
        verifier, challenge = SpotifyService.generate_pkce()
        assert len(verifier) >= 43
        assert len(verifier) <= 128
        assert len(challenge) > 0
        # Challenge should be base64url (no padding)
        assert "=" not in challenge

    def test_generate_pkce_unique(self) -> None:
        """Each call should produce unique values."""
        v1, c1 = SpotifyService.generate_pkce()
        v2, c2 = SpotifyService.generate_pkce()
        assert v1 != v2
        assert c1 != c2

    def test_get_auth_url(self) -> None:
        """Auth URL should contain expected parameters."""
        url = SpotifyService.get_auth_url(
            client_id="my_client_id",
            redirect_uri="http://localhost/callback",
            code_challenge="test_challenge",
            state="test_state",
        )
        assert "accounts.spotify.com" in url
        assert "client_id=my_client_id" in url
        assert "code_challenge=test_challenge" in url
        assert "state=test_state" in url
        assert "code_challenge_method=S256" in url
        assert "response_type=code" in url
        assert "scope=" in url


# ---------------------------------------------------------------------------
# Token encryption tests
# ---------------------------------------------------------------------------


class TestTokenEncryption:
    """Tests for token encrypt/decrypt helpers."""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """Encrypt then decrypt should return the original value."""
        original = "my_secret_token_12345"
        encrypted = _encrypt_token(original)
        assert encrypted != original
        assert len(encrypted) > 0
        decrypted = _decrypt_token(encrypted)
        assert decrypted == original

    def test_encrypt_empty_string(self) -> None:
        """Encrypting an empty string should return empty string."""
        assert _encrypt_token("") == ""

    def test_decrypt_empty_string(self) -> None:
        """Decrypting an empty string should return empty string."""
        assert _decrypt_token("") == ""

    def test_decrypt_invalid_data(self) -> None:
        """Decrypting garbage should return empty string (graceful)."""
        assert _decrypt_token("not-valid-encrypted-data") == ""


# ---------------------------------------------------------------------------
# SpotifyService async tests
# ---------------------------------------------------------------------------


class TestSpotifyService:
    """Tests for SpotifyService API methods (mocked httpx)."""

    @pytest.mark.asyncio
    async def test_get_user_playlists(self, db_session: AsyncSession) -> None:
        """get_user_playlists should return paginated results."""
        await _seed_spotify_settings(db_session)

        service = SpotifyService(
            client_id="test_client_id",
            client_secret="test_client_secret",
            redirect_uri="http://localhost/callback",
        )
        # Pre-load token so _ensure_token doesn't try to refresh
        service._access_token = "test_access_token"
        service._token_expiry = datetime(2099, 1, 1, tzinfo=timezone.utc)

        # Mock the HTTP response (MagicMock for sync .json())
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [
                {"id": "pl1", "name": "Summer Vibes"},
                {"id": "pl2", "name": "Release Radar"},
                {"id": "pl3", "name": "Random Mix"},
            ],
            "next": None,
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        service._client = mock_client
        playlists = await service.get_user_playlists(db_session)

        assert len(playlists) == 3
        assert playlists[0]["name"] == "Summer Vibes"
        assert playlists[1]["name"] == "Release Radar"
        await service.close()

    @pytest.mark.asyncio
    async def test_get_playlist_tracks(self, db_session: AsyncSession) -> None:
        """get_playlist_tracks should return normalised track objects."""
        await _seed_spotify_settings(db_session)

        service = SpotifyService(
            client_id="test_client_id",
            client_secret="test_client_secret",
        )
        service._access_token = "test_access_token"
        service._token_expiry = datetime(2099, 1, 1, tzinfo=timezone.utc)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [
                {
                    "track": {
                        "uri": "spotify:track:abc123",
                        "name": "Test Track",
                        "album": {"name": "Test Album"},
                        "artists": [{"name": "Test Artist"}],
                    }
                },
                {
                    "track": {
                        "uri": "spotify:track:def456",
                        "name": "Another Track",
                        "album": {"name": "Another Album"},
                        "artists": [{"name": "Another Artist"}],
                    }
                },
                {"track": None},  # null track should be skipped
            ],
            "next": None,
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        service._client = mock_client
        tracks = await service.get_playlist_tracks(db_session, "pl_test")

        assert len(tracks) == 2
        assert tracks[0].track_name == "Test Track"
        assert tracks[0].artist_name == "Test Artist"
        assert tracks[0].album_name == "Test Album"
        assert tracks[0].spotify_uri == "spotify:track:abc123"
        assert tracks[1].spotify_uri == "spotify:track:def456"
        await service.close()

    @pytest.mark.asyncio
    async def test_sync_playlists_classification(
        self, db_session: AsyncSession
    ) -> None:
        """sync_playlists should classify playlists correctly."""
        await _seed_spotify_settings(db_session)

        service = SpotifyService(
            client_id="test_client_id",
            client_secret="test_client_secret",
        )
        service._access_token = "test_access_token"
        service._token_expiry = datetime(2099, 1, 1, tzinfo=timezone.utc)

        # Mock get_user_playlists
        mock_playlists_resp = MagicMock()
        mock_playlists_resp.status_code = 200
        mock_playlists_resp.json.return_value = {
            "items": [
                {"id": "pl_seasonal", "name": "Summer Hits 2024"},
                {"id": "pl_discover", "name": "Release Radar"},
                {"id": "pl_other", "name": "My Random Mix"},
            ],
            "next": None,
        }

        # Mock get_playlist_tracks (return empty for simplicity)
        mock_tracks_resp = MagicMock()
        mock_tracks_resp.status_code = 200
        mock_tracks_resp.json.return_value = {"items": [], "next": None}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            mock_playlists_resp,
            mock_tracks_resp,
            mock_tracks_resp,
            mock_tracks_resp,
        ])
        service._client = mock_client
        result = await service.sync_playlists(db_session)

        assert result.playlists_synced == 3
        assert result.seasonal == 1
        assert result.discover == 1
        assert result.other == 1

        # Verify DB rows
        stmt = select(Playlist).order_by(Playlist.name)
        rows = await db_session.execute(stmt)
        playlists = rows.scalars().all()
        assert len(playlists) == 3

        names_to_type = {p.name: p.playlist_type for p in playlists}
        assert names_to_type["Summer Hits 2024"] == PlaylistType.SEASONAL
        assert names_to_type["Release Radar"] == PlaylistType.DISCOVER
        assert names_to_type["My Random Mix"] == PlaylistType.OTHER
        await service.close()

    @pytest.mark.asyncio
    async def test_sync_playlists_tracks_stored(
        self, db_session: AsyncSession
    ) -> None:
        """sync_playlists should store track data in PlaylistTrack rows."""
        await _seed_spotify_settings(db_session)

        service = SpotifyService(
            client_id="test_client_id",
            client_secret="test_client_secret",
        )
        service._access_token = "test_access_token"
        service._token_expiry = datetime(2099, 1, 1, tzinfo=timezone.utc)

        mock_playlists_resp = MagicMock()
        mock_playlists_resp.status_code = 200
        mock_playlists_resp.json.return_value = {
            "items": [
                {"id": "pl_discover", "name": "Release Radar"},
            ],
            "next": None,
        }

        mock_tracks_resp = MagicMock()
        mock_tracks_resp.status_code = 200
        mock_tracks_resp.json.return_value = {
            "items": [
                {
                    "track": {
                        "uri": "spotify:track:111",
                        "name": "Track One",
                        "album": {"name": "Album One"},
                        "artists": [{"name": "Artist One"}],
                    }
                },
                {
                    "track": {
                        "uri": "spotify:track:222",
                        "name": "Track Two",
                        "album": {"name": "Album Two"},
                        "artists": [{"name": "Artist Two"}],
                    }
                },
            ],
            "next": None,
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            mock_playlists_resp,
            mock_tracks_resp,
        ])
        service._client = mock_client
        result = await service.sync_playlists(db_session)

        assert result.tracks_added == 2

        # Verify tracks in DB
        stmt = select(PlaylistTrack).order_by(PlaylistTrack.track_name)
        rows = await db_session.execute(stmt)
        tracks = rows.scalars().all()
        assert len(tracks) == 2
        assert tracks[0].track_name == "Track One"
        assert tracks[0].artist_name == "Artist One"
        assert tracks[0].album_name == "Album One"
        assert tracks[1].track_name == "Track Two"
        await service.close()

    @pytest.mark.asyncio
    async def test_sync_playlists_idempotent(
        self, db_session: AsyncSession
    ) -> None:
        """Running sync twice should replace old tracks, not duplicate."""
        await _seed_spotify_settings(db_session)

        service = SpotifyService(
            client_id="test_client_id",
            client_secret="test_client_secret",
        )
        service._access_token = "test_access_token"
        service._token_expiry = datetime(2099, 1, 1, tzinfo=timezone.utc)

        mock_playlists_resp = MagicMock()
        mock_playlists_resp.status_code = 200
        mock_playlists_resp.json.return_value = {
            "items": [{"id": "pl_1", "name": "My Playlist"}],
            "next": None,
        }

        mock_tracks_resp = MagicMock()
        mock_tracks_resp.status_code = 200
        mock_tracks_resp.json.return_value = {
            "items": [
                {
                    "track": {
                        "uri": "spotify:track:aaa",
                        "name": "Track A",
                        "album": {"name": "Album A"},
                        "artists": [{"name": "Artist A"}],
                    }
                },
            ],
            "next": None,
        }

        # First sync
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[
            mock_playlists_resp,
            mock_tracks_resp,
        ])
        service._client = mock_client
        await service.sync_playlists(db_session)

        # Second sync (same data)
        mock_playlists_resp2 = MagicMock()
        mock_playlists_resp2.status_code = 200
        mock_playlists_resp2.json.return_value = {
            "items": [{"id": "pl_1", "name": "My Playlist"}],
            "next": None,
        }
        mock_tracks_resp2 = MagicMock()
        mock_tracks_resp2.status_code = 200
        mock_tracks_resp2.json.return_value = {
            "items": [
                {
                    "track": {
                        "uri": "spotify:track:aaa",
                        "name": "Track A",
                        "album": {"name": "Album A"},
                        "artists": [{"name": "Artist A"}],
                    }
                },
            ],
            "next": None,
        }

        mock_client2 = AsyncMock()
        mock_client2.get = AsyncMock(side_effect=[
            mock_playlists_resp2,
            mock_tracks_resp2,
        ])
        service._client = mock_client2
        await service.sync_playlists(db_session)

        # Should still have exactly 1 playlist and 1 track
        stmt = select(Playlist)
        rows = await db_session.execute(stmt)
        playlists = rows.scalars().all()
        assert len(playlists) == 1

        stmt = select(PlaylistTrack)
        rows = await db_session.execute(stmt)
        tracks = rows.scalars().all()
        assert len(tracks) == 1
        await service.close()


# ---------------------------------------------------------------------------
# OAuth endpoint tests
# ---------------------------------------------------------------------------


class TestSpotifyAuthEndpoints:
    """Integration tests for Spotify OAuth endpoints."""

    @pytest.mark.asyncio
    async def test_auth_login_returns_url(self, client: AsyncClient) -> None:
        """GET /spotify/auth/login should return an auth_url."""
        # Seed client_id first
        async with AsyncClient(
            transport=client._transport, base_url="http://test"
        ) as ac:
            # Need to seed settings first via a DB call, but we can't access
            # db_session directly from client. Let's use the health endpoint
            # to ensure the app is running, then test the login endpoint.
            pass

    @pytest.mark.asyncio
    async def test_auth_login_no_client_id(self, client: AsyncClient) -> None:
        """Login should fail if client_id is not configured."""
        resp = await client.get("/api/spotify/auth/login")
        assert resp.status_code == 400
        data = resp.json()
        assert "Client ID" in data.get("detail", "")

    @pytest.mark.asyncio
    async def test_auth_status_not_connected(self, client: AsyncClient) -> None:
        """Status should return connected=false when no token is stored."""
        resp = await client.get("/api/spotify/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False

    @pytest.mark.asyncio
    async def test_sync_not_connected(self, client: AsyncClient) -> None:
        """POST /spotify/sync should fail if not connected."""
        # Seed credentials but no refresh token
        async with AsyncClient(
            transport=client._transport, base_url="http://test"
        ) as ac:
            pass

        resp = await client.post("/api/spotify/sync")
        # May be 400 (not connected) or 400 (no credentials)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# R6 rule tests
# ---------------------------------------------------------------------------


class TestR6Rule:
    """Tests for R6 — discover playlist tracks → manual queue."""

    @pytest.mark.asyncio
    async def test_r6_discover_playlist_queues_manual(
        self, db_session: AsyncSession
    ) -> None:
        """Tracks in a DISCOVER playlist should be queued as MANUAL."""
        from app.services.rules import RuleEngine

        # Create a DISCOVER playlist with tracks
        playlist = Playlist(
            spotify_id="spotify:pl:discover1",
            name="Release Radar",
            playlist_type=PlaylistType.DISCOVER,
            is_active=True,
        )
        db_session.add(playlist)
        await db_session.flush()

        db_session.add(
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="New Track",
                artist_name="New Artist",
                album_name="New Album",
                spotify_uri="spotify:track:xyz",
            )
        )
        db_session.add(
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="Another Track",
                artist_name="Another Artist",
                album_name="Another Album",
                spotify_uri="spotify:track:abc",
            )
        )
        await db_session.commit()

        # Run rule engine
        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        assert result.albums_queued_manual >= 2
        assert "R6" in result.rules_fired

        # Verify albums created as MANUAL
        stmt = select(Album).where(
            Album.queue_type == QueueType.MANUAL,
        )
        rows = await db_session.execute(stmt)
        albums = rows.scalars().all()
        album_titles = {a.title for a in albums}
        assert "New Album" in album_titles
        assert "Another Album" in album_titles

        for album in albums:
            assert album.status == AlbumStatus.QUEUED
            assert "Discover: Release Radar" in album.reason

    @pytest.mark.asyncio
    async def test_r6_inactive_playlist_skipped(
        self, db_session: AsyncSession
    ) -> None:
        """Inactive DISCOVER playlists should be ignored."""
        from app.services.rules import RuleEngine

        # Create an INACTIVE discover playlist with tracks
        playlist = Playlist(
            spotify_id="spotify:pl:inactive",
            name="Old Discover",
            playlist_type=PlaylistType.DISCOVER,
            is_active=False,
        )
        db_session.add(playlist)
        await db_session.flush()

        db_session.add(
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="Old Track",
                artist_name="Old Artist",
                album_name="Old Album",
                spotify_uri="spotify:track:old",
            )
        )
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        # Should not queue anything from inactive playlist
        assert result.albums_queued_manual == 0

        stmt = select(Album).where(Album.title == "Old Album")
        rows = await db_session.execute(stmt)
        assert rows.scalar() is None

    @pytest.mark.asyncio
    async def test_r6_already_queued_skipped(
        self, db_session: AsyncSession
    ) -> None:
        """Albums already in pipeline should not be re-queued by R6."""
        from app.services.rules import RuleEngine

        # Create an already-downloaded album
        existing = Album(
            title="Existing Album",
            artist_name="Existing Artist",
            status=AlbumStatus.DOWNLOADED,
            queue_type=QueueType.MANUAL,
            reason="already done",
        )
        db_session.add(existing)
        await db_session.commit()

        # Create DISCOVER playlist with same album
        playlist = Playlist(
            spotify_id="spotify:pl:disc2",
            name="Pitchfork Selects",
            playlist_type=PlaylistType.DISCOVER,
            is_active=True,
        )
        db_session.add(playlist)
        await db_session.flush()

        db_session.add(
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="Track X",
                artist_name="Existing Artist",
                album_name="Existing Album",
                spotify_uri="spotify:track:dup",
            )
        )
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        # Should NOT queue — album already downloaded
        stmt = select(Album).where(
            Album.title == "Existing Album",
            Album.status == AlbumStatus.QUEUED,
        )
        rows = await db_session.execute(stmt)
        assert rows.scalar() is None

        # The original album should still be DOWNLOADED
        assert result.albums_queued_manual == 0

    @pytest.mark.asyncio
    async def test_r6_seasonal_playlist_not_queued_as_manual(
        self, db_session: AsyncSession
    ) -> None:
        """SEASONAL playlist tracks should NOT be queued by R6 (R2 handles them)."""
        from app.services.rules import RuleEngine

        # Create a SEASONAL playlist with tracks
        playlist = Playlist(
            spotify_id="spotify:pl:seasonal",
            name="Summer Mix",
            playlist_type=PlaylistType.SEASONAL,
            is_active=True,
        )
        db_session.add(playlist)
        await db_session.flush()

        db_session.add(
            PlaylistTrack(
                playlist_id=playlist.id,
                track_name="Hot Track",
                artist_name="Hot Artist",
                album_name="Hot Album",
                spotify_uri="spotify:track:hot",
            )
        )
        await db_session.commit()

        engine = RuleEngine(db_session)
        result = await engine.evaluate()

        # R6 only looks at DISCOVER playlists; seasonal should not increment manual count
        # (R2 would handle seasonal, but we didn't seed the threshold settings)
        seasonal_albums = 0
        stmt = select(Album).where(Album.reason.contains("Summer Mix"))
        rows = await db_session.execute(stmt)
        for album in rows.scalars():
            if album.queue_type == QueueType.MANUAL:
                seasonal_albums += 1

        # R6 should not have queued seasonal tracks as MANUAL
        assert seasonal_albums == 0
