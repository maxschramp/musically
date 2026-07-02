"""Tests for the queue router — real DB-backed endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.album import Album, AlbumStatus, QueueType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_album(
    db: AsyncSession,
    title: str = "Test Album",
    artist: str = "Test Artist",
    status: AlbumStatus = AlbumStatus.QUEUED,
    queue_type: QueueType = QueueType.MANUAL,
    reason: str = "",
) -> Album:
    album = Album(
        title=title,
        artist_name=artist,
        status=status,
        queue_type=queue_type,
        reason=reason,
    )
    db.add(album)
    await db.commit()
    await db.refresh(album)
    return album


# ---------------------------------------------------------------------------
# List queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_queue_empty(client: AsyncClient) -> None:
    """GET /api/queue on empty DB should return empty list."""
    response = await client.get("/api/queue")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_list_queue_with_items(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /api/queue should return queued albums."""
    await _create_album(db_session, title="Album A")
    await _create_album(db_session, title="Album B")

    response = await client.get("/api/queue")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_list_queue_filter_by_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Should filter by status."""
    await _create_album(db_session, title="Queued", status=AlbumStatus.QUEUED)
    await _create_album(db_session, title="Downloaded", status=AlbumStatus.DOWNLOADED)

    response = await client.get("/api/queue?status=queued")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Queued"


@pytest.mark.asyncio
async def test_list_queue_filter_by_type(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Should filter by queue type."""
    await _create_album(db_session, title="Auto", queue_type=QueueType.AUTO)
    await _create_album(db_session, title="Manual", queue_type=QueueType.MANUAL)

    response = await client.get("/api/queue?type=auto")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Auto"


@pytest.mark.asyncio
async def test_list_queue_invalid_status(client: AsyncClient) -> None:
    """Invalid status should return 400."""
    response = await client.get("/api/queue?status=invalid_status")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_queue_invalid_type(client: AsyncClient) -> None:
    """Invalid queue type should return 400."""
    response = await client.get("/api/queue?type=invalid_type")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_queue_pagination(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Should respect page and limit params."""
    for i in range(5):
        await _create_album(db_session, title=f"Album {i}")

    response = await client.get("/api/queue?page=1&limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 5
    assert data["total_pages"] == 3


# ---------------------------------------------------------------------------
# Get single queue item
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_queue_item_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /api/queue/{id} should return the album."""
    album = await _create_album(db_session)

    response = await client.get(f"/api/queue/{album.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(album.id)
    assert data["title"] == "Test Album"


@pytest.mark.asyncio
async def test_get_queue_item_not_found(client: AsyncClient) -> None:
    """GET /api/queue/{id} should return 404 for missing album."""
    response = await client.get(f"/api/queue/{uuid.uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Create queue item
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_queue_item(client: AsyncClient, db_session: AsyncSession) -> None:
    """POST /api/queue should create a new album queue entry."""
    response = await client.post("/api/queue", json={
        "title": "New Album",
        "artist_name": "New Artist",
        "reason": "test",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "New Album"
    assert data["status"] == "queued"
    assert data["queue_type"] == "manual"  # default


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_queue_item(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/queue/{id}/approve should set queue_type=auto."""
    album = await _create_album(db_session, queue_type=QueueType.MANUAL)

    response = await client.post(f"/api/queue/{album.id}/approve")
    assert response.status_code == 200
    data = response.json()
    assert data["queue_type"] == "auto"


@pytest.mark.asyncio
async def test_approve_stalled_resets(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Approving a stalled album should reset status to queued."""
    album = await _create_album(
        db_session,
        status=AlbumStatus.STALLED,
        queue_type=QueueType.MANUAL,
    )

    response = await client.post(f"/api/queue/{album.id}/approve")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["queue_type"] == "auto"


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reject_queue_item(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/queue/{id}/reject should set status=rejected."""
    album = await _create_album(db_session)

    response = await client.post(f"/api/queue/{album.id}/reject")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rejected"


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_queue_item(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/queue/{id}/retry should reset for retry."""
    album = await _create_album(
        db_session,
        status=AlbumStatus.STALLED,
    )

    response = await client.post(f"/api/queue/{album.id}/retry")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["retry_count"] == 0
    assert data["next_retry_at"] is not None


# ---------------------------------------------------------------------------
# Bulk approve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_approve(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/queue/bulk-approve should approve multiple items."""
    a1 = await _create_album(db_session, title="A1", queue_type=QueueType.MANUAL)
    a2 = await _create_album(db_session, title="A2", queue_type=QueueType.MANUAL)

    response = await client.post("/api/queue/bulk-approve", json={
        "ids": [str(a1.id), str(a2.id)],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["approved"] == 2


@pytest.mark.asyncio
async def test_bulk_approve_empty_ids(client: AsyncClient) -> None:
    """Should return 400 for empty ids list."""
    response = await client.post("/api/queue/bulk-approve", json={"ids": []})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_bulk_approve_invalid_uuid(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Should report errors for invalid UUIDs."""
    a1 = await _create_album(db_session)

    response = await client.post("/api/queue/bulk-approve", json={
        "ids": [str(a1.id), "not-a-uuid"],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["approved"] == 1
    assert len(data["errors"]) == 1


# ---------------------------------------------------------------------------
# Bulk reject
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_reject(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/queue/bulk-reject should reject multiple items."""
    a1 = await _create_album(db_session, title="R1")
    a2 = await _create_album(db_session, title="R2")

    response = await client.post("/api/queue/bulk-reject", json={
        "ids": [str(a1.id), str(a2.id)],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["rejected"] == 2


# ---------------------------------------------------------------------------
# Bulk create albums
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_create_albums(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/queue/bulk should create multiple album queue entries."""
    response = await client.post("/api/queue/bulk", json={
        "albums": [
            {"title": "OK Computer", "artist_name": "Radiohead", "reason": "Manual add"},
            {"title": "Kid A", "artist_name": "Radiohead", "reason": "Manual add"},
            {"title": "Discovery", "artist_name": "Daft Punk", "reason": "Recommendation"},
        ],
    })
    assert response.status_code == 201
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3

    titles = {item["title"] for item in data}
    assert titles == {"OK Computer", "Kid A", "Discovery"}

    for item in data:
        assert item["status"] == "queued"
        assert item["queue_type"] == "manual"


@pytest.mark.asyncio
async def test_bulk_create_defaults(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/queue/bulk should apply defaults for queue_type and reason."""
    response = await client.post("/api/queue/bulk", json={
        "albums": [
            {"title": "Lonerism", "artist_name": "Tame Impala"},
        ],
    })
    assert response.status_code == 201
    data = response.json()
    assert len(data) == 1
    assert data[0]["queue_type"] == "manual"
    assert data[0]["reason"] == "Manual add"


@pytest.mark.asyncio
async def test_bulk_create_empty_albums_422(client: AsyncClient) -> None:
    """POST /api/queue/bulk should return 422 for empty albums list."""
    response = await client.post("/api/queue/bulk", json={"albums": []})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bulk_create_auto_creates_artists(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/queue/bulk should auto-create Artist records for new artists."""
    from app.models.artist import Artist
    from sqlalchemy import func, select

    response = await client.post("/api/queue/bulk", json={
        "albums": [
            {"title": "In Rainbows", "artist_name": "Radiohead"},
            {"title": "Random Access Memories", "artist_name": "Daft Punk"},
        ],
    })
    assert response.status_code == 201

    # Verify artists were created
    result = await db_session.execute(
        select(Artist).where(func.lower(Artist.name).in_(["radiohead", "daft punk"]))
    )
    artists = result.scalars().all()
    assert len(artists) == 2
    artist_names = {a.name for a in artists}
    assert "Radiohead" in artist_names
    assert "Daft Punk" in artist_names


# ---------------------------------------------------------------------------
# Artist auto-creation on single queue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_queue_item_auto_creates_artist(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/queue should auto-create an Artist when the artist doesn't exist."""
    from app.models.artist import Artist
    from sqlalchemy import func, select

    response = await client.post("/api/queue", json={
        "title": "Hail to the Thief",
        "artist_name": "Radiohead",
    })
    assert response.status_code == 201

    # Verify artist was created
    result = await db_session.execute(
        select(Artist).where(func.lower(Artist.name) == "radiohead")
    )
    artist = result.scalar_one_or_none()
    assert artist is not None
    assert artist.name == "Radiohead"


@pytest.mark.asyncio
async def test_create_queue_item_existing_artist_not_duplicated(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/queue should reuse existing Artist instead of creating duplicate."""
    from app.models.artist import Artist
    from sqlalchemy import func, select

    # Create artist first
    await client.post("/api/artists", json={"name": "Radiohead"})

    # Queue an album — should not create a second artist
    response = await client.post("/api/queue", json={
        "title": "Amnesiac",
        "artist_name": "Radiohead",
    })
    assert response.status_code == 201

    # Verify only one artist exists
    result = await db_session.execute(
        select(Artist).where(func.lower(Artist.name) == "radiohead")
    )
    artists = result.scalars().all()
    assert len(artists) == 1
