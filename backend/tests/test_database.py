"""Tests for the database explorer router."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.album import Album, AlbumStatus, QueueType
from app.models.track_play import TrackPlay


# ---------------------------------------------------------------------------
# GET /api/database/tables
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tables_returns_allowed_tables(client: AsyncClient) -> None:
    """GET /api/database/tables should return only whitelisted tables."""
    response = await client.get("/api/database/tables")
    assert response.status_code == 200
    data = response.json()

    assert "tables" in data
    table_names = [t["name"] for t in data["tables"]]

    # All whitelisted tables should be present
    expected = {
        "albums", "artists", "track_plays", "playlists",
        "playlist_tracks", "settings", "sync_history", "task_runs",
    }
    for name in expected:
        assert name in table_names, f"Expected table '{name}' in response"

    # Each table should have a row count (integer)
    for t in data["tables"]:
        assert isinstance(t["name"], str)
        assert isinstance(t["rows"], int)


@pytest.mark.asyncio
async def test_list_tables_includes_row_counts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Row counts should reflect actual data."""
    # Insert some albums
    for i in range(3):
        album = Album(
            title=f"Test Album {i}",
            artist_name="Test Artist",
            status=AlbumStatus.QUEUED,
            queue_type=QueueType.MANUAL,
        )
        db_session.add(album)
    await db_session.commit()

    response = await client.get("/api/database/tables")
    assert response.status_code == 200
    data = response.json()

    albums_entry = next(t for t in data["tables"] if t["name"] == "albums")
    assert albums_entry["rows"] == 3


# ---------------------------------------------------------------------------
# GET /api/database/table/{table_name}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browse_table_disallowed_returns_400(client: AsyncClient) -> None:
    """Browsing a non-whitelisted table should return 400."""
    response = await client.get("/api/database/table/secret_table")
    assert response.status_code == 400
    data = response.json()
    assert "not allowed" in data["detail"]


@pytest.mark.asyncio
async def test_browse_table_sql_injection_rejected(client: AsyncClient) -> None:
    """SQL injection attempts via table name should be rejected."""
    # Various SQL injection payloads
    payloads = [
        "albums; DROP TABLE albums;--",
        "albums' OR '1'='1",
        "albums UNION SELECT * FROM users",
        "albums--",
        "1=1",
    ]
    for payload in payloads:
        response = await client.get(f"/api/database/table/{payload}")
        assert response.status_code == 400, (
            f"Payload '{payload}' should be rejected with 400, "
            f"got {response.status_code}: {response.json().get('detail', '')}"
        )


@pytest.mark.asyncio
async def test_browse_table_returns_empty(client: AsyncClient) -> None:
    """Browsing an empty table should return empty rows with column names."""
    response = await client.get("/api/database/table/albums")
    assert response.status_code == 200
    data = response.json()

    assert data["table_name"] == "albums"
    assert isinstance(data["columns"], list)
    assert len(data["columns"]) > 0
    assert data["rows"] == []
    assert data["total_rows"] == 0
    assert data["page"] == 1
    assert data["total_pages"] == 1


@pytest.mark.asyncio
async def test_browse_table_with_data(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Browsing a table with data should return rows."""
    # Insert a track play
    track = TrackPlay(
        track_name="Test Track",
        artist_name="Test Artist",
        album_name="Test Album",
        album_mbid=None,
        artist_mbid=None,
        played_at=datetime.now(timezone.utc),
    )
    db_session.add(track)
    await db_session.commit()

    response = await client.get("/api/database/table/track_plays")
    assert response.status_code == 200
    data = response.json()

    assert data["table_name"] == "track_plays"
    assert data["total_rows"] == 1
    assert len(data["rows"]) == 1

    row = data["rows"][0]
    assert row["track_name"] == "Test Track"
    assert row["artist_name"] == "Test Artist"
    assert row["album_name"] == "Test Album"


@pytest.mark.asyncio
async def test_browse_table_pagination(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Pagination should work correctly."""
    # Insert 5 track plays
    for i in range(5):
        track = TrackPlay(
            track_name=f"Track {i}",
            artist_name="Test Artist",
            album_name="Test Album",
            album_mbid=None,
            artist_mbid=None,
            played_at=datetime.now(timezone.utc),
        )
        db_session.add(track)
    await db_session.commit()

    # Page 1, limit 2
    response = await client.get("/api/database/table/track_plays?page=1&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert data["total_rows"] == 5
    assert len(data["rows"]) == 2
    assert data["page"] == 1
    assert data["total_pages"] == 3

    # Page 2, limit 2
    response = await client.get("/api/database/table/track_plays?page=2&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["rows"]) == 2
    assert data["page"] == 2

    # Page 3, limit 2 (last page, 1 item)
    response = await client.get("/api/database/table/track_plays?page=3&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["rows"]) == 1
    assert data["page"] == 3


@pytest.mark.asyncio
async def test_browse_table_serializes_special_types(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """UUID and datetime values should be serialized as strings."""
    track = TrackPlay(
        track_name="Serialization Test",
        artist_name="Test Artist",
        album_name="Test Album",
        album_mbid=None,
        artist_mbid=None,
        played_at=datetime.now(timezone.utc),
    )
    db_session.add(track)
    await db_session.commit()
    await db_session.refresh(track)

    response = await client.get("/api/database/table/track_plays")
    assert response.status_code == 200
    data = response.json()

    row = data["rows"][0]
    # UUID should be serialized as a string
    assert isinstance(row["id"], str)
    # datetime should be serialized as a string
    assert isinstance(row["played_at"], str)
    assert isinstance(row["created_at"], str)
