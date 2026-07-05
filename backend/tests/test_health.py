"""Tests for the health check endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """GET /api/health should return 200 with status ok."""
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_get_version(client: AsyncClient) -> None:
    """GET /api/health/version should return 200 with version info."""
    response = await client.get("/api/health/version")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert "build_date" in data
    assert "build_ref" in data
    # Defaults when env vars are not set
    assert data["version"] == "0.0.0"
    assert data["build_date"] == "unknown"
    assert data["build_ref"] == "dev"


@pytest.mark.asyncio
async def test_stats(client: AsyncClient) -> None:
    """GET /api/stats should return 200 with placeholder stats."""
    response = await client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_albums"] == 0
    assert "queued_count" in data
