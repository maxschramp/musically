"""Tests for the MusicBrainz API service."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from app.services.musicbrainz import MusicBrainzService


# ---------------------------------------------------------------------------
# search_album
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_search_album_found(httpx_mock: HTTPXMock) -> None:
    """search_album returns the first release when MusicBrainz returns results."""
    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/release/?query=artist%3A%22The+Beatles%22+AND+release%3A%22Abbey+Road%22&fmt=json&limit=1",
        json={
            "releases": [
                {
                    "id": "055be099-3d35-4e34-be6a-956b08e14d7c",
                    "title": "Abbey Road",
                    "artist-credit": [{"name": "The Beatles"}],
                }
            ]
        },
    )

    svc = MusicBrainzService()
    result = await svc.search_album("The Beatles", "Abbey Road")
    await svc.close()

    assert result is not None
    assert result["id"] == "055be099-3d35-4e34-be6a-956b08e14d7c"
    assert result["title"] == "Abbey Road"


@pytest.mark.asyncio
async def test_search_album_not_found(httpx_mock: HTTPXMock) -> None:
    """search_album returns None when MusicBrainz returns no results."""
    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/release/?query=artist%3A%22Nobody%22+AND+release%3A%22Nothing%22&fmt=json&limit=1",
        json={"releases": []},
    )

    svc = MusicBrainzService()
    result = await svc.search_album("Nobody", "Nothing")
    await svc.close()

    assert result is None


# ---------------------------------------------------------------------------
# get_release_tracks
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_release_tracks(httpx_mock: HTTPXMock) -> None:
    """get_release_tracks returns parsed track listing."""
    mbid = "055be099-3d35-4e34-be6a-956b08e14d7c"
    httpx_mock.add_response(
        url=f"https://musicbrainz.org/ws/2/release/{mbid}?inc=recordings&fmt=json",
        json={
            "media": [
                {
                    "tracks": [
                        {
                            "position": "1",
                            "title": "Come Together",
                            "length": 259000,
                            "recording": {"id": "track-mbid-1", "title": "Come Together", "length": 259000},
                        },
                        {
                            "position": "2",
                            "title": "Something",
                            "length": 182000,
                            "recording": {"id": "track-mbid-2", "title": "Something", "length": 182000},
                        },
                    ]
                }
            ]
        },
    )

    svc = MusicBrainzService()
    tracks = await svc.get_release_tracks(mbid)
    await svc.close()

    assert len(tracks) == 2
    assert tracks[0]["position"] == 1
    assert tracks[0]["title"] == "Come Together"
    assert tracks[0]["length_ms"] == 259000
    assert tracks[0]["id"] == "track-mbid-1"
    assert tracks[1]["title"] == "Something"


# ---------------------------------------------------------------------------
# get_album_tracklist
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_album_tracklist(httpx_mock: HTTPXMock) -> None:
    """get_album_tracklist combines search + track lookup."""
    # Mock search
    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/release/?query=artist%3A%22The+Beatles%22+AND+release%3A%22Abbey+Road%22&fmt=json&limit=1",
        json={
            "releases": [
                {
                    "id": "055be099-3d35-4e34-be6a-956b08e14d7c",
                    "title": "Abbey Road",
                    "artist-credit": [{"name": "The Beatles"}],
                }
            ]
        },
    )
    # Mock release lookup
    mbid = "055be099-3d35-4e34-be6a-956b08e14d7c"
    httpx_mock.add_response(
        url=f"https://musicbrainz.org/ws/2/release/{mbid}?inc=recordings&fmt=json",
        json={
            "media": [
                {
                    "tracks": [
                        {
                            "position": "1",
                            "title": "Come Together",
                            "length": 259000,
                            "recording": {"id": "t1", "title": "Come Together", "length": 259000},
                        },
                    ]
                }
            ]
        },
    )

    svc = MusicBrainzService()
    result = await svc.get_album_tracklist("The Beatles", "Abbey Road")
    await svc.close()

    assert result is not None
    assert result["mbid"] == mbid
    assert result["track_count"] == 1
    assert result["tracks"][0]["title"] == "Come Together"


@pytest.mark.asyncio
async def test_get_album_tracklist_not_found(httpx_mock: HTTPXMock) -> None:
    """get_album_tracklist returns None when search finds nothing."""
    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/release/?query=artist%3A%22Nobody%22+AND+release%3A%22Nothing%22&fmt=json&limit=1",
        json={"releases": []},
    )

    svc = MusicBrainzService()
    result = await svc.get_album_tracklist("Nobody", "Nothing")
    await svc.close()

    assert result is None


# ---------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rate_limit_enforced(httpx_mock: HTTPXMock) -> None:
    """Two rapid calls should not trigger more than one request per second.

    Because the rate limiter sleeps, the second mock URL must match
    the actual (delayed) request.
    """
    import time

    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/release/?query=artist%3A%22A%22+AND+release%3A%22B%22&fmt=json&limit=1",
        json={"releases": []},
    )
    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/release/?query=artist%3A%22C%22+AND+release%3A%22D%22&fmt=json&limit=1",
        json={"releases": []},
    )

    svc = MusicBrainzService()
    t0 = time.monotonic()
    await svc.search_album("A", "B")
    await svc.search_album("C", "D")
    elapsed = time.monotonic() - t0
    await svc.close()

    # Should have waited at least ~1.1s between calls
    assert elapsed >= 1.0, f"Expected at least 1.0s elapsed, got {elapsed:.2f}s"
