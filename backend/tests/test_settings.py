"""Tests for the settings router — CRUD and seeding."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_settings_seeds_defaults(client: AsyncClient) -> None:
    """GET /api/settings should seed defaults and return grouped settings."""
    response = await client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()

    # Should return at least the known categories
    assert isinstance(data, dict)
    assert "thresholds" in data
    assert "scheduling" in data
    assert "sources" in data

    # Verify a known key is present
    thresholds = data["thresholds"]
    keys = [s["key"] for s in thresholds]
    assert "album_play_threshold" in keys


@pytest.mark.asyncio
async def test_get_settings_filter_by_category(client: AsyncClient) -> None:
    """GET /api/settings?category=thresholds should return only that category."""
    response = await client.get("/api/settings?category=thresholds")
    assert response.status_code == 200
    data = response.json()

    assert set(data.keys()) == {"thresholds"}


@pytest.mark.asyncio
async def test_update_settings(client: AsyncClient) -> None:
    """PUT /api/settings should update existing settings and return the updated state."""
    payload = {"settings": {"album_play_threshold": "10", "lastfm_enabled": "false"}}
    response = await client.put("/api/settings", json=payload)
    assert response.status_code == 200
    data = response.json()

    # Check that thresholds were updated
    thresholds = data.get("thresholds", [])
    album_entry = next((s for s in thresholds if s["key"] == "album_play_threshold"), None)
    assert album_entry is not None
    assert album_entry["value"] == "10"

    # Check sources updated
    sources = data.get("sources", [])
    lastfm_entry = next((s for s in sources if s["key"] == "lastfm_enabled"), None)
    assert lastfm_entry is not None
    assert lastfm_entry["value"] == "false"
