"""Tests for LastFM API client."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import HTTPStatusError, Request, Response

from app.services.lastfm import (
    LastFMTrack,
    LastFMPagination,
    LastFMResponse,
    LastFMService,
    BASE_URL,
)


# ---------------------------------------------------------------------------
# Sample LastFM API JSON responses
# ---------------------------------------------------------------------------

def _make_track_json(
    name: str = "Test Track",
    artist: str = "Test Artist",
    album: str = "Test Album",
    uts: str = "1688166600",  # 2023-07-01T00:30:00
    nowplaying: bool = False,
    track_mbid: str = "",
    artist_mbid: str = "",
) -> dict:
    track: dict = {
        "name": name,
        "artist": {"#text": artist, "mbid": artist_mbid},
        "album": {"#text": album},
        "mbid": track_mbid,
    }
    if nowplaying:
        track["@attr"] = {"nowplaying": "true"}
    else:
        track["date"] = {"#text": "01 Jul 2023, 00:30", "uts": uts}
    return track


def _make_recent_tracks_json(
    tracks: list[dict],
    page: int = 1,
    total_pages: int = 1,
    per_page: int = 200,
    total: int = 0,
    user: str = "testuser",
) -> dict:
    if total == 0:
        total = len(tracks)
    return {
        "recenttracks": {
            "track": tracks,
            "@attr": {
                "user": user,
                "page": str(page),
                "totalPages": str(total_pages),
                "perPage": str(per_page),
                "total": str(total),
            },
        }
    }


class TestLastFMTrack:
    """Unit tests for LastFMTrack dataclass."""

    def test_create_track(self) -> None:
        played = datetime(2023, 7, 1, 0, 30, tzinfo=timezone.utc)
        track = LastFMTrack(
            track_name="Bohemian Rhapsody",
            artist_name="Queen",
            album_name="A Night at the Opera",
            track_mbid="abc-123",
            artist_mbid="def-456",
            played_at=played,
        )
        assert track.track_name == "Bohemian Rhapsody"
        assert track.artist_name == "Queen"
        assert track.album_name == "A Night at the Opera"
        assert track.track_mbid == "abc-123"
        assert track.artist_mbid == "def-456"
        assert track.played_at == played

    def test_album_name_none(self) -> None:
        played = datetime(2023, 7, 1, 0, 30, tzinfo=timezone.utc)
        track = LastFMTrack(
            track_name="Song",
            artist_name="Artist",
            album_name=None,
            track_mbid=None,
            artist_mbid=None,
            played_at=played,
        )
        assert track.album_name is None


class TestFetchRecentTracks:
    """Tests for LastFMService.fetch_recent_tracks."""

    @pytest.fixture
    def service(self) -> LastFMService:
        return LastFMService(api_key="test_key", user="testuser")

    @pytest.mark.asyncio
    async def test_single_page(self, service: LastFMService) -> None:
        """Fetch a single page with basic tracks."""
        json_resp = _make_recent_tracks_json(
            tracks=[
                _make_track_json("Song 1", "Artist 1", "Album 1", "1688171400"),
                _make_track_json("Song 2", "Artist 2", "Album 2", "1688171500"),
            ],
            page=1,
            total_pages=1,
            total=2,
        )
        mock_response = Response(200, json=json_resp, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", return_value=mock_response) as mock_get:
            result = await service.fetch_recent_tracks(page=1)

        mock_get.assert_called_once()
        assert isinstance(result, LastFMResponse)
        assert len(result.tracks) == 2
        assert result.pagination.page == 1
        assert result.pagination.total_pages == 1
        assert result.pagination.total == 2

        assert result.tracks[0].track_name == "Song 1"
        assert result.tracks[0].artist_name == "Artist 1"
        assert result.tracks[0].album_name == "Album 1"
        assert result.tracks[0].played_at == datetime(2023, 7, 1, 0, 30, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_skip_now_playing(self, service: LastFMService) -> None:
        """Now-playing tracks (no played_at) should be skipped."""
        json_resp = _make_recent_tracks_json(
            tracks=[
                _make_track_json("Now Playing", "Artist", "Album", nowplaying=True),
                _make_track_json("Real Song", "Artist", "Album", "1688166600"),
            ],
            page=1,
            total_pages=1,
            total=1,
        )
        mock_response = Response(200, json=json_resp, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", return_value=mock_response):
            result = await service.fetch_recent_tracks()

        assert len(result.tracks) == 1
        assert result.tracks[0].track_name == "Real Song"

    @pytest.mark.asyncio
    async def test_empty_album_name(self, service: LastFMService) -> None:
        """Album name empty string -> None."""
        json_resp = _make_recent_tracks_json(
            tracks=[
                _make_track_json("Song", "Artist", "", "1688166600"),
            ],
            page=1,
            total_pages=1,
            total=1,
        )
        mock_response = Response(200, json=json_resp, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", return_value=mock_response):
            result = await service.fetch_recent_tracks()

        assert len(result.tracks) == 1
        assert result.tracks[0].album_name is None

    @pytest.mark.asyncio
    async def test_track_mbid_handling(self, service: LastFMService) -> None:
        """Track MBID should be captured; empty string -> None."""
        json_resp = _make_recent_tracks_json(
            tracks=[
                _make_track_json("Song", "Artist", "Album", "1688166600", track_mbid="valid-mbid-123"),
            ],
            page=1,
            total_pages=1,
            total=1,
        )
        mock_response = Response(200, json=json_resp, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", return_value=mock_response):
            result = await service.fetch_recent_tracks()

        assert result.tracks[0].track_mbid == "valid-mbid-123"

    @pytest.mark.asyncio
    async def test_missing_recenttracks_key(self, service: LastFMService) -> None:
        """Gracefully handle missing 'recenttracks' key."""
        json_resp = {"error": "something went wrong"}
        mock_response = Response(200, json=json_resp, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", return_value=mock_response):
            result = await service.fetch_recent_tracks()

        assert len(result.tracks) == 0
        assert result.pagination.total_pages == 0

    @pytest.mark.asyncio
    async def test_http_error(self, service: LastFMService) -> None:
        """HTTP errors should raise."""
        mock_response = Response(500, json={}, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", return_value=mock_response):
            with pytest.raises(HTTPStatusError):
                await service.fetch_recent_tracks()

    @pytest.mark.asyncio
    async def test_single_track_not_list(self, service: LastFMService) -> None:
        """When LastFM returns a single track as a dict, not a list."""
        track = _make_track_json("Solo", "Artist", "Album", "1688166600")
        json_resp = {
            "recenttracks": {
                "track": track,  # single dict, not list
                "@attr": {"user": "testuser", "page": "1", "totalPages": "1", "perPage": "200", "total": "1"},
            }
        }
        mock_response = Response(200, json=json_resp, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", return_value=mock_response):
            result = await service.fetch_recent_tracks()

        assert len(result.tracks) == 1
        assert result.tracks[0].track_name == "Solo"

    @pytest.mark.asyncio
    async def test_from_to_params(self, service: LastFMService) -> None:
        """Verify from/to params are passed in the request."""
        json_resp = _make_recent_tracks_json(tracks=[], total=0)
        mock_response = Response(200, json=json_resp, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", return_value=mock_response) as mock_get:
            await service.fetch_recent_tracks(from_ts=1000000, to_ts=2000000)

        call_args = mock_get.call_args
        params = call_args[1]["params"]
        assert params["from"] == 1000000
        assert params["to"] == 2000000


class TestFetchAllRecent:
    """Tests for paginated fetch_all_recent."""

    @pytest.fixture
    def service(self) -> LastFMService:
        return LastFMService(api_key="test_key", user="testuser", rate_limit_rps=10.0)

    @pytest.mark.asyncio
    async def test_single_page(self, service: LastFMService) -> None:
        """Only one page available."""
        json_resp = _make_recent_tracks_json(
            tracks=[_make_track_json("Song", "Artist", "Album", "1688166600")],
            page=1,
            total_pages=1,
            total=1,
        )
        mock_response = Response(200, json=json_resp, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", return_value=mock_response):
            tracks = await service.fetch_all_recent(max_pages=5)

        assert len(tracks) == 1

    @pytest.mark.asyncio
    async def test_multiple_pages(self, service: LastFMService) -> None:
        """Fetch across 3 pages."""
        page1 = _make_recent_tracks_json(
            tracks=[_make_track_json("Song 1", "Artist", "Album", "1688166600")],
            page=1,
            total_pages=3,
            total=3,
            per_page=1,
        )
        page2 = _make_recent_tracks_json(
            tracks=[_make_track_json("Song 2", "Artist", "Album", "1688166700")],
            page=2,
            total_pages=3,
            total=3,
            per_page=1,
        )
        page3 = _make_recent_tracks_json(
            tracks=[_make_track_json("Song 3", "Artist", "Album", "1688166800")],
            page=3,
            total_pages=3,
            total=3,
            per_page=1,
        )

        mock_resp1 = Response(200, json=page1, request=Request("GET", BASE_URL))
        mock_resp2 = Response(200, json=page2, request=Request("GET", BASE_URL))
        mock_resp3 = Response(200, json=page3, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", side_effect=[mock_resp1, mock_resp2, mock_resp3]) as mock_get:
            tracks = await service.fetch_all_recent(max_pages=5)

        assert len(tracks) == 3
        assert mock_get.call_count == 3
        track_names = [t.track_name for t in tracks]
        assert track_names == ["Song 1", "Song 2", "Song 3"]

    @pytest.mark.asyncio
    async def test_rate_limiting(self, service: LastFMService) -> None:
        """Verify asyncio.sleep is called between pages."""
        service.rate_limit_rps = 5.0
        page1 = _make_recent_tracks_json(
            tracks=[_make_track_json("Song 1", "A", "B", "1688166600")],
            page=1,
            total_pages=2,
            total=2,
            per_page=1,
        )
        page2 = _make_recent_tracks_json(
            tracks=[_make_track_json("Song 2", "A", "B", "1688166700")],
            page=2,
            total_pages=2,
            total=2,
            per_page=1,
        )

        mock_resp1 = Response(200, json=page1, request=Request("GET", BASE_URL))
        mock_resp2 = Response(200, json=page2, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", side_effect=[mock_resp1, mock_resp2]):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                tracks = await service.fetch_all_recent(max_pages=5)

        assert len(tracks) == 2
        # Should call sleep exactly once (between page 1 and page 2)
        mock_sleep.assert_called_once_with(1.0 / 5.0)

    @pytest.mark.asyncio
    async def test_partial_failure_mid_pages(self, service: LastFMService) -> None:
        """If page 2 fails, return page 1's tracks gracefully."""
        page1 = _make_recent_tracks_json(
            tracks=[_make_track_json("Song 1", "A", "B", "1688166600")],
            page=1,
            total_pages=3,
            total=3,
            per_page=1,
        )

        mock_resp1 = Response(200, json=page1, request=Request("GET", BASE_URL))
        mock_resp2 = Response(500, json={}, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", side_effect=[mock_resp1, mock_resp2]):
            tracks = await service.fetch_all_recent(max_pages=5)

        # Should still return page 1 tracks
        assert len(tracks) == 1
        assert tracks[0].track_name == "Song 1"

    @pytest.mark.asyncio
    async def test_max_pages_respected(self, service: LastFMService) -> None:
        """max_pages should cap the number of pages fetched."""
        page1 = _make_recent_tracks_json(
            tracks=[_make_track_json("Song", "A", "B", "1688166600")],
            page=1,
            total_pages=10,
            total=10,
            per_page=1,
        )
        mock_resp = Response(200, json=page1, request=Request("GET", BASE_URL))

        with patch.object(service.client, "get", return_value=mock_resp) as mock_get:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                tracks = await service.fetch_all_recent(max_pages=2)

        # Should only call get for pages 1 and 2 (2 calls)
        assert mock_get.call_count == 2
        assert len(tracks) <= 2


class TestClose:
    """Test close method."""

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        service = LastFMService(api_key="key", user="user")
        with patch.object(service.client, "aclose", new_callable=AsyncMock) as mock_close:
            await service.close()
        mock_close.assert_called_once()
