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
async def test_stats(client: AsyncClient) -> None:
    """GET /api/stats should return 200 with placeholder stats."""
    response = await client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_albums"] == 0
    assert "queued_count" in data
