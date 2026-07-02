"""Tests for the unified search endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from pytest_httpx import HTTPXMock

from app.models.album import Album, AlbumStatus, QueueType


# ---------------------------------------------------------------------------
# MusicBrainz album search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_musicbrainz_album(
    client: AsyncClient, httpx_mock: HTTPXMock
) -> None:
    """GET /api/search?q=radiohead&source=musicbrainz returns MusicBrainz results."""
    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/release/?query=release%3A%22radiohead%22&fmt=json&limit=10",
        json={
            "releases": [
                {
                    "id": "mbid-okc",
                    "title": "OK Computer",
                    "date": "1997-05-28",
                    "artist-credit": [{"name": "Radiohead"}],
                },
                {
                    "id": "mbid-ka",
                    "title": "Kid A",
                    "date": "2000",
                    "artist-credit": [{"name": "Radiohead"}],
                },
            ]
        },
    )

    resp = await client.get("/api/search?q=radiohead&source=musicbrainz")
    assert resp.status_code == 200

    data = resp.json()
    assert data["query"] == "radiohead"
    assert len(data["results"]) == 2

    r0 = data["results"][0]
    assert r0["source"] == "musicbrainz"
    assert r0["type"] == "album"
    assert r0["title"] == "OK Computer"
    assert r0["artist_name"] == "Radiohead"
    assert r0["mbid"] == "mbid-okc"
    assert r0["year"] == 1997
    assert r0["in_library"] is False
    assert r0["in_queue"] is False

    r1 = data["results"][1]
    assert r1["title"] == "Kid A"
    assert r1["year"] == 2000


# ---------------------------------------------------------------------------
# MusicBrainz artist search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_musicbrainz_artist(
    client: AsyncClient, httpx_mock: HTTPXMock
) -> None:
    """GET /api/search?q=radiohead&type=artist&source=musicbrainz returns artists."""
    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/artist/?query=artist%3A%22radiohead%22&fmt=json&limit=10",
        json={
            "artists": [
                {"id": "mbid-rh", "name": "Radiohead"},
            ]
        },
    )

    resp = await client.get("/api/search?q=radiohead&type=artist&source=musicbrainz")
    assert resp.status_code == 200

    data = resp.json()
    assert len(data["results"]) == 1
    r = data["results"][0]
    assert r["source"] == "musicbrainz"
    assert r["type"] == "artist"
    assert r["name"] == "Radiohead"
    assert r["mbid"] == "mbid-rh"


# ---------------------------------------------------------------------------
# Multiple sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_multiple_sources(
    client: AsyncClient, httpx_mock: HTTPXMock, monkeypatch
) -> None:
    """Searching musicbrainz + spotify returns merged results."""
    # Ensure Spotify credentials are set
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "SPOTIFY_CLIENT_ID", "test-id")
    monkeypatch.setattr(settings, "SPOTIFY_CLIENT_SECRET", "test-secret")

    # MusicBrainz mock
    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/release/?query=release%3A%22daft+punk%22&fmt=json&limit=10",
        json={
            "releases": [
                {
                    "id": "mbid-dp",
                    "title": "Discovery",
                    "date": "2001",
                    "artist-credit": [{"name": "Daft Punk"}],
                },
            ]
        },
    )
    # Spotify client credentials mock
    httpx_mock.add_response(
        url="https://accounts.spotify.com/api/token",
        method="POST",
        json={"access_token": "fake-cc-token", "expires_in": 3600},
    )
    # Spotify search mock
    httpx_mock.add_response(
        url="https://api.spotify.com/v1/search?q=daft+punk&type=album&limit=10",
        json={
            "albums": {
                "items": [
                    {
                        "id": "sp-dp",
                        "name": "Discovery",
                        "release_date": "2001-03-12",
                        "artists": [{"name": "Daft Punk"}],
                    },
                ]
            }
        },
    )

    resp = await client.get("/api/search?q=daft+punk&source=musicbrainz,spotify")
    assert resp.status_code == 200

    data = resp.json()
    assert data["query"] == "daft punk"
    assert len(data["results"]) == 2

    sources = {r["source"] for r in data["results"]}
    assert sources == {"musicbrainz", "spotify"}


# ---------------------------------------------------------------------------
# in_library / in_queue flags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_in_library_flag(
    client: AsyncClient, httpx_mock: HTTPXMock, db_session
) -> None:
    """Albums already in the library are flagged with in_library=True."""
    # Add an album to the DB
    from app.database import async_session_factory
    album = Album(
        title="Discovery",
        artist_name="Daft Punk",
        status=AlbumStatus.DOWNLOADED,
        queue_type=QueueType.AUTO,
        reason="test",
    )
    db_session.add(album)
    await db_session.commit()

    # MusicBrainz mock
    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/release/?query=release%3A%22daft+punk%22&fmt=json&limit=10",
        json={
            "releases": [
                {
                    "id": "mbid-dp",
                    "title": "Discovery",
                    "date": "2001",
                    "artist-credit": [{"name": "Daft Punk"}],
                },
                {
                    "id": "mbid-hw",
                    "title": "Homework",
                    "date": "1997",
                    "artist-credit": [{"name": "Daft Punk"}],
                },
            ]
        },
    )

    resp = await client.get("/api/search?q=daft+punk&source=musicbrainz")
    assert resp.status_code == 200

    data = resp.json()
    results = {r["title"]: r for r in data["results"]}

    assert results["Discovery"]["in_library"] is True
    assert results["Discovery"]["in_queue"] is False
    assert results["Homework"]["in_library"] is False
    assert results["Homework"]["in_queue"] is False


@pytest.mark.asyncio
async def test_search_in_queue_flag(
    client: AsyncClient, httpx_mock: HTTPXMock, db_session
) -> None:
    """Albums queued for download are flagged with in_queue=True."""
    album = Album(
        title="Discovery",
        artist_name="Daft Punk",
        status=AlbumStatus.QUEUED,
        queue_type=QueueType.AUTO,
        reason="test",
    )
    db_session.add(album)
    await db_session.commit()

    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/release/?query=release%3A%22daft+punk%22&fmt=json&limit=10",
        json={
            "releases": [
                {
                    "id": "mbid-dp",
                    "title": "Discovery",
                    "date": "2001",
                    "artist-credit": [{"name": "Daft Punk"}],
                },
            ]
        },
    )

    resp = await client.get("/api/search?q=daft+punk&source=musicbrainz")
    assert resp.status_code == 200

    data = resp.json()
    assert data["results"][0]["in_library"] is False
    assert data["results"][0]["in_queue"] is True


# ---------------------------------------------------------------------------
# Handle unavailable source gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_spotify_not_configured(
    client: AsyncClient, monkeypatch
) -> None:
    """When Spotify credentials are missing, a warning is returned."""
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "SPOTIFY_CLIENT_ID", None)
    monkeypatch.setattr(settings, "SPOTIFY_CLIENT_SECRET", None)

    resp = await client.get("/api/search?q=test&source=spotify")
    assert resp.status_code == 200

    data = resp.json()
    assert data["results"] == []
    assert any("not configured" in w for w in data["warnings"])


@pytest.mark.asyncio
async def test_search_qobuz_not_configured(
    client: AsyncClient, monkeypatch
) -> None:
    """When Qobuz credentials are missing, a warning is returned."""
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "QOBUZ_EMAIL", None)
    monkeypatch.setattr(settings, "QOBUZ_PASSWORD", None)

    resp = await client.get("/api/search?q=test&source=qobuz")
    assert resp.status_code == 200

    data = resp.json()
    assert data["results"] == []
    assert any("not configured" in w for w in data["warnings"])


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_empty_query_rejected(client: AsyncClient) -> None:
    """An empty query returns a 422 validation error."""
    resp = await client.get("/api/search?q=")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_invalid_source_returns_empty(
    client: AsyncClient,
) -> None:
    """An unknown source results in no results and no error."""
    resp = await client.get("/api/search?q=test&source=nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []


@pytest.mark.asyncio
async def test_search_type_both(
    client: AsyncClient, httpx_mock: HTTPXMock
) -> None:
    """type=both returns both albums and artists."""
    # MusicBrainz album
    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/release/?query=release%3A%22test%22&fmt=json&limit=10",
        json={
            "releases": [
                {
                    "id": "mbid-1",
                    "title": "Test Album",
                    "date": "2020",
                    "artist-credit": [{"name": "Test Artist"}],
                },
            ]
        },
    )
    # MusicBrainz artist
    httpx_mock.add_response(
        url="https://musicbrainz.org/ws/2/artist/?query=artist%3A%22test%22&fmt=json&limit=10",
        json={
            "artists": [
                {"id": "mbid-2", "name": "Test Artist"},
            ]
        },
    )

    resp = await client.get("/api/search?q=test&type=both&source=musicbrainz")
    assert resp.status_code == 200

    data = resp.json()
    types = {r["type"] for r in data["results"]}
    assert types == {"album", "artist"}


@pytest.mark.asyncio
async def test_search_musicbrainz_network_error(
    client: AsyncClient, httpx_mock: HTTPXMock
) -> None:
    """When MusicBrainz is unreachable, a warning is returned."""
    httpx_mock.add_exception(
        url="https://musicbrainz.org/ws/2/release/?query=release%3A%22test%22&fmt=json&limit=10",
        exception=Exception("Connection refused"),
    )

    resp = await client.get("/api/search?q=test&source=musicbrainz")
    assert resp.status_code == 200

    data = resp.json()
    assert data["results"] == []
    assert any("MusicBrainz" in w for w in data["warnings"])
