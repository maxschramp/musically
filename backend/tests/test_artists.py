"""Tests for artist lookup, subscribe-by-name, unsubscribe-by-name, and auto-follow endpoints."""

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artist import Artist
from app.models.setting import Setting


async def _create_artist(db_session, name: str, subscribed: bool = False) -> Artist:
    """Helper to create an Artist row directly in the test DB."""
    artist = Artist(
        id=uuid.uuid4(),
        name=name,
        subscribed=subscribed,
        subscription_source="manual" if subscribed else None,
    )
    db_session.add(artist)
    await db_session.commit()
    await db_session.refresh(artist)
    return artist


# ---------------------------------------------------------------------------
# POST /api/artists/lookup
# ---------------------------------------------------------------------------
class TestLookupArtist:
    async def test_lookup_existing_artist(self, client: AsyncClient, db_session):
        """Lookup should return the existing artist record."""
        artist = await _create_artist(db_session, "Radiohead", subscribed=True)

        resp = await client.post("/api/artists/lookup", json={"artist_name": "Radiohead"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(artist.id)
        assert data["name"] == "Radiohead"
        assert data["subscribed"] is True

    async def test_lookup_existing_case_insensitive(self, client: AsyncClient, db_session):
        """Lookup should be case-insensitive."""
        artist = await _create_artist(db_session, "Radiohead")

        resp = await client.post("/api/artists/lookup", json={"artist_name": "radiohead"})
        assert resp.status_code == 200
        assert resp.json()["id"] == str(artist.id)

    async def test_lookup_new_artist_creates_record(self, client: AsyncClient, db_session):
        """Lookup for unknown artist should create a new record with subscribed=False."""
        resp = await client.post("/api/artists/lookup", json={"artist_name": "New Artist"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "New Artist"
        assert data["subscribed"] is False
        assert data["subscription_source"] is None
        assert "id" in data

        # Verify it's actually persisted
        from sqlalchemy import func, select

        result = await db_session.execute(
            select(Artist).where(func.lower(Artist.name) == "new artist")
        )
        persisted = result.scalar_one_or_none()
        assert persisted is not None
        assert persisted.subscribed is False

    async def test_lookup_strips_whitespace(self, client: AsyncClient, db_session):
        """Lookup should strip leading/trailing whitespace from artist_name."""
        artist = await _create_artist(db_session, "Radiohead")

        resp = await client.post("/api/artists/lookup", json={"artist_name": "  Radiohead  "})
        assert resp.status_code == 200
        assert resp.json()["id"] == str(artist.id)


# ---------------------------------------------------------------------------
# POST /api/artists/subscribe-by-name
# ---------------------------------------------------------------------------
class TestSubscribeByName:
    async def test_subscribe_new_artist(self, client: AsyncClient, db_session):
        """Subscribing by name should create and subscribe a new artist."""
        resp = await client.post(
            "/api/artists/subscribe-by-name", json={"artist_name": "New Artist"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "New Artist"
        assert data["subscribed"] is True
        assert data["subscription_source"] == "manual"

    async def test_subscribe_existing_artist(self, client: AsyncClient, db_session):
        """Subscribing an existing unsubscribed artist should update it."""
        artist = await _create_artist(db_session, "Radiohead", subscribed=False)

        resp = await client.post(
            "/api/artists/subscribe-by-name", json={"artist_name": "Radiohead"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(artist.id)
        assert data["subscribed"] is True
        assert data["subscription_source"] == "manual"

    async def test_subscribe_already_subscribed(self, client: AsyncClient, db_session):
        """Subscribing an already-subscribed artist should be idempotent."""
        artist = await _create_artist(db_session, "Radiohead", subscribed=True)

        resp = await client.post(
            "/api/artists/subscribe-by-name", json={"artist_name": "Radiohead"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(artist.id)
        assert data["subscribed"] is True
        assert data["subscription_source"] == "manual"


# ---------------------------------------------------------------------------
# POST /api/artists/unsubscribe-by-name
# ---------------------------------------------------------------------------
class TestUnsubscribeByName:
    async def test_unsubscribe_existing_artist(self, client: AsyncClient, db_session):
        """Unsubscribing an existing subscribed artist should work."""
        artist = await _create_artist(db_session, "Radiohead", subscribed=True)

        resp = await client.post(
            "/api/artists/unsubscribe-by-name", json={"artist_name": "Radiohead"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(artist.id)
        assert data["subscribed"] is False
        assert data["subscription_source"] is None

    async def test_unsubscribe_not_found(self, client: AsyncClient):
        """Unsubscribing a nonexistent artist should return 404."""
        resp = await client.post(
            "/api/artists/unsubscribe-by-name", json={"artist_name": "Nonexistent Artist"}
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_unsubscribe_already_unsubscribed(self, client: AsyncClient, db_session):
        """Unsubscribing an already-unsubscribed artist should be idempotent."""
        artist = await _create_artist(db_session, "Radiohead", subscribed=False)

        resp = await client.post(
            "/api/artists/unsubscribe-by-name", json={"artist_name": "Radiohead"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["subscribed"] is False
        assert data["subscription_source"] is None


# ---------------------------------------------------------------------------
# Helpers for auto-follow tests
# ---------------------------------------------------------------------------


async def _seed_setting(db: AsyncSession, key: str, value: str) -> None:
    """Insert or update a setting in the test DB."""
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = Setting(key=key, value=value, category="general")
        db.add(setting)
    else:
        setting.value = value
    await db.commit()


def _create_music_library(tmp: Path, artists: dict[str, int]) -> Path:
    """Create a fake music library tree.

    For each artist name -> album_count, create subdirectories
    with a dummy .flac file inside.
    """
    lib = tmp / "library"
    lib.mkdir(parents=True)
    for artist_name, album_count in artists.items():
        artist_dir = lib / artist_name
        artist_dir.mkdir()
        for i in range(album_count):
            album_dir = artist_dir / f"Album {i + 1}"
            album_dir.mkdir()
            (album_dir / "track.flac").touch()
    return lib


# ---------------------------------------------------------------------------
# POST /api/artists/auto-follow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_follow_subscribes_artists_above_threshold(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Artists with album count >= threshold get subscribed."""
    lib = _create_music_library(tmp_path, {
        "Radiohead": 5,
        "Boards of Canada": 2,
        "Aphex Twin": 1,
    })
    await _seed_setting(db_session, "music_library_directory", str(lib))
    await _seed_setting(db_session, "library_albums_subscribe_threshold", "2")

    response = await client.post("/api/artists/auto-follow")
    assert response.status_code == 200
    data = response.json()

    assert data["artists_scanned"] == 3
    assert data["artists_subscribed"] == 2  # Radiohead (5) + BoC (2), Aphex (1) below
    assert len(data["details"]) == 3

    # Verify DB state
    result = await db_session.execute(select(Artist).order_by(Artist.name))
    artists = result.scalars().all()
    assert len(artists) == 2  # Only 2 were created (above threshold)

    radiohead = next(a for a in artists if a.name == "Radiohead")
    assert radiohead.subscribed is True
    assert radiohead.subscription_source == "auto_library_size"
    assert radiohead.albums_in_library == 5

    boc = next(a for a in artists if a.name == "Boards of Canada")
    assert boc.subscribed is True
    assert boc.subscription_source == "auto_library_size"
    assert boc.albums_in_library == 2

    # Artists in details should include the below-threshold one
    names_in_details = {d["name"] for d in data["details"]}
    assert names_in_details == {"Radiohead", "Boards of Canada", "Aphex Twin"}


@pytest.mark.asyncio
async def test_auto_follow_no_artists_meet_threshold(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """No subscriptions when all artists are below threshold."""
    lib = _create_music_library(tmp_path, {
        "One Album Wonder": 1,
        "Singles Only": 1,
    })
    await _seed_setting(db_session, "music_library_directory", str(lib))
    await _seed_setting(db_session, "library_albums_subscribe_threshold", "2")

    response = await client.post("/api/artists/auto-follow")
    assert response.status_code == 200
    data = response.json()

    assert data["artists_scanned"] == 2
    assert data["artists_subscribed"] == 0
    assert len(data["details"]) == 2

    # No Artist records created
    result = await db_session.execute(select(func.count()).select_from(Artist))
    assert result.scalar() == 0


@pytest.mark.asyncio
async def test_auto_follow_creates_new_records_for_library_only_artists(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Artists only in the library (not yet in DB) are created and subscribed."""
    lib = _create_music_library(tmp_path, {
        "New Discovery": 3,
    })
    await _seed_setting(db_session, "music_library_directory", str(lib))
    await _seed_setting(db_session, "library_albums_subscribe_threshold", "2")

    response = await client.post("/api/artists/auto-follow")
    assert response.status_code == 200
    data = response.json()

    assert data["artists_scanned"] == 1
    assert data["artists_subscribed"] == 1

    result = await db_session.execute(
        select(Artist).where(func.lower(Artist.name) == "new discovery")
    )
    artist = result.scalar_one_or_none()
    assert artist is not None
    assert artist.subscribed is True
    assert artist.subscription_source == "auto_library_size"
    assert artist.albums_in_library == 3


# ---------------------------------------------------------------------------
# POST /api/artists — Manual artist creation
# ---------------------------------------------------------------------------

class TestCreateArtist:
    async def test_create_artist_success(self, client: AsyncClient, db_session):
        """POST /api/artists should create a new artist with 201."""
        resp = await client.post("/api/artists", json={
            "name": "Radiohead",
            "artist_mbid": "a74b1b7f-71a5-4011-9441-d0b5e4122711",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Radiohead"
        assert data["artist_mbid"] == "a74b1b7f-71a5-4011-9441-d0b5e4122711"
        assert data["subscribed"] is False
        assert data["subscription_source"] is None

        # Verify in DB
        result = await db_session.execute(
            select(Artist).where(func.lower(Artist.name) == "radiohead")
        )
        artist = result.scalar_one_or_none()
        assert artist is not None
        assert str(artist.id) == data["id"]

    async def test_create_artist_without_mbid(self, client: AsyncClient, db_session):
        """POST /api/artists should work without an MBID."""
        resp = await client.post("/api/artists", json={"name": "Unknown Artist"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Unknown Artist"
        assert data["artist_mbid"] is None

    async def test_create_artist_duplicate_409(self, client: AsyncClient):
        """POST /api/artists should return 409 for duplicate name (case-insensitive)."""
        resp1 = await client.post("/api/artists", json={"name": "Radiohead"})
        assert resp1.status_code == 201

        resp2 = await client.post("/api/artists", json={"name": "RADIOHEAD"})
        assert resp2.status_code == 409
        assert "already exists" in resp2.json()["detail"].lower()

    async def test_create_artist_empty_name_422(self, client: AsyncClient):
        """POST /api/artists should return 422 for empty name."""
        resp = await client.post("/api/artists", json={"name": ""})
        assert resp.status_code == 422

    async def test_create_artist_missing_name_422(self, client: AsyncClient):
        """POST /api/artists should return 422 when name is missing."""
        resp = await client.post("/api/artists", json={})
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_auto_follow_updates_existing_artist(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Existing Artist records are updated (not duplicated) on auto-follow."""
    lib = _create_music_library(tmp_path, {
        "Radiohead": 7,
    })
    await _seed_setting(db_session, "music_library_directory", str(lib))
    await _seed_setting(db_session, "library_albums_subscribe_threshold", "2")

    # Pre-create an artist that is NOT subscribed
    artist = Artist(
        name="Radiohead",
        subscribed=False,
        subscription_source=None,
        albums_in_library=0,
    )
    db_session.add(artist)
    await db_session.commit()

    response = await client.post("/api/artists/auto-follow")
    assert response.status_code == 200
    data = response.json()

    assert data["artists_subscribed"] == 1

    # The existing record should be updated, no duplicate
    result = await db_session.execute(
        select(Artist).where(func.lower(Artist.name) == "radiohead")
    )
    artists = result.scalars().all()
    assert len(artists) == 1
    updated = artists[0]
    assert updated.subscribed is True
    assert updated.subscription_source == "auto_library_size"
    assert updated.albums_in_library == 7


@pytest.mark.asyncio
async def test_auto_follow_missing_library_directory(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Returns empty result when library directory does not exist."""
    await _seed_setting(db_session, "music_library_directory", "/nonexistent/path")
    await _seed_setting(db_session, "library_albums_subscribe_threshold", "2")

    response = await client.post("/api/artists/auto-follow")
    assert response.status_code == 200
    data = response.json()

    assert data["artists_scanned"] == 0
    assert data["artists_subscribed"] == 0
    assert "message" in data


@pytest.mark.asyncio
async def test_auto_follow_ignores_empty_artist_dirs(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    """Artist directories with no albums (or no music files) are skipped."""
    lib = tmp_path / "library"
    lib.mkdir()
    empty_artist = lib / "Empty Artist"
    empty_artist.mkdir()  # No album subdirs

    real_artist = lib / "Real Artist"
    real_artist.mkdir()
    album = real_artist / "Album 1"
    album.mkdir()
    (album / "track.flac").touch()

    await _seed_setting(db_session, "music_library_directory", str(lib))
    await _seed_setting(db_session, "library_albums_subscribe_threshold", "1")

    response = await client.post("/api/artists/auto-follow")
    assert response.status_code == 200
    data = response.json()

    assert data["artists_scanned"] == 1  # Only "Real Artist"
    assert data["artists_subscribed"] == 1
    names = {d["name"] for d in data["details"]}
    assert "Empty Artist" not in names
    assert "Real Artist" in names
