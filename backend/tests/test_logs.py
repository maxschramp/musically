"""Tests for the logs router endpoints."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient


LOG_CONTENT = """2026-07-04 12:00:00 [INFO] app.main: Server started
2026-07-04 12:00:01 [INFO] app.main: Database connected
2026-07-04 12:00:02 [WARNING] app.services.lastfm: Rate limit approaching
2026-07-04 12:00:03 [ERROR] app.services.qobuz: Download failed for album 123
2026-07-04 12:00:04 [INFO] app.workers.download: Retrying in 60s
"""


@pytest.fixture
def log_dir(monkeypatch: pytest.MonkeyPatch) -> str:
    """Create a temporary log directory and monkey-patch LOG_FILES."""
    tmp = tempfile.mkdtemp(prefix="musically_test_logs_")
    monkeypatch.setattr(
        "app.routers.logs.LOG_FILES",
        {
            "api": os.path.join(tmp, "api.log"),
            "nginx": os.path.join(tmp, "nginx.log"),
            "postgres": os.path.join(tmp, "postgres.log"),
            "redis": os.path.join(tmp, "redis.log"),
        },
    )
    return tmp


def _write_log(path: str, content: str) -> None:
    Path(path).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# GET /api/logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_logs_all_empty(client: AsyncClient, log_dir: str) -> None:
    """When no log files exist, return empty list for service=all."""
    response = await client.get("/api/logs", params={"service": "all", "lines": 10})
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "all"
    assert data["lines"] == []
    assert data["total_lines"] == 0


@pytest.mark.asyncio
async def test_get_logs_specific_service(client: AsyncClient, log_dir: str) -> None:
    """Read last N lines from a specific service log."""
    _write_log(os.path.join(log_dir, "api.log"), LOG_CONTENT)

    response = await client.get("/api/logs", params={"service": "api", "lines": 3})
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "api"
    assert len(data["lines"]) == 3
    assert data["total_lines"] == 3
    # Last 3 of 5 lines: "Rate limit", "Download failed", "Retrying"
    assert "Download failed" in data["lines"][-2]
    assert "Retrying" in data["lines"][-1]


@pytest.mark.asyncio
async def test_get_logs_unknown_service(client: AsyncClient, log_dir: str) -> None:
    """Requesting an unknown service returns empty."""
    response = await client.get("/api/logs", params={"service": "unknown", "lines": 5})
    assert response.status_code == 200
    data = response.json()
    assert data["lines"] == []
    assert data["total_lines"] == 0


@pytest.mark.asyncio
async def test_get_logs_respects_lines_param(client: AsyncClient, log_dir: str) -> None:
    """The lines param caps the number of returned lines."""
    _write_log(os.path.join(log_dir, "api.log"), LOG_CONTENT)

    response = await client.get("/api/logs", params={"service": "api", "lines": 2})
    data = response.json()
    assert len(data["lines"]) == 2


@pytest.mark.asyncio
async def test_get_logs_all_merges(client: AsyncClient, log_dir: str) -> None:
    """service=all merges lines from every available log."""
    _write_log(os.path.join(log_dir, "api.log"), "2026-07-04 12:00:00 api-line\n")
    _write_log(os.path.join(log_dir, "nginx.log"), "2026-07-04 12:00:01 nginx-line\n")
    _write_log(os.path.join(log_dir, "postgres.log"), "2026-07-04 12:00:02 pg-line\n")

    response = await client.get("/api/logs", params={"service": "all", "lines": 10})
    data = response.json()
    assert data["service"] == "all"
    # All three lines should appear, tagged with [service]
    assert any("[api]" in ln for ln in data["lines"])
    assert any("[nginx]" in ln for ln in data["lines"])
    assert any("[postgres]" in ln for ln in data["lines"])


@pytest.mark.asyncio
async def test_get_logs_lines_max_enforced(client: AsyncClient, log_dir: str) -> None:
    """The lines param must be between 1 and 2000 (FastAPI Query validation)."""
    response = await client.get("/api/logs", params={"service": "api", "lines": 0})
    assert response.status_code == 422  # validation error

    response = await client.get("/api/logs", params={"service": "api", "lines": 2001})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/logs/stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_logs_unknown_service(client: AsyncClient, log_dir: str) -> None:
    """Streaming an unknown service emits an error SSE event and stops."""
    async with client.stream("GET", "/api/logs/stream", params={"service": "unknown"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"

        body = b""
        async for chunk in resp.aiter_bytes():
            body += chunk
            if b"error" in body:
                break
        assert b"Unknown service" in body


# NOTE: Full SSE streaming integration tests (infinite keepalive loop) are
# not practical with ASGITransport because response.aclose() hangs when the
# server-side generator never exits. The endpoint is tested indirectly via
# the unknown-service error path (above) which exits cleanly, and via the
# GET /api/logs endpoint which exercises the same _read_last_lines helper.
# The SSE stream is validated manually or via a real HTTP client (curl).


@pytest.mark.asyncio
async def test_read_last_lines_empty_file(client: AsyncClient, log_dir: str) -> None:
    """_read_last_lines returns empty list for an empty or missing file."""
    from app.routers.logs import _read_last_lines

    # Non-existent file
    result = _read_last_lines(os.path.join(log_dir, "nonexistent.log"), 10)
    assert result == []

    # Empty file
    empty_path = os.path.join(log_dir, "empty.log")
    _write_log(empty_path, "")
    result = _read_last_lines(empty_path, 10)
    assert result == []


@pytest.mark.asyncio
async def test_read_last_lines_handles_large_n(client: AsyncClient, log_dir: str) -> None:
    """_read_last_lines clamps to available lines when n exceeds file length."""
    from app.routers.logs import _read_last_lines

    path = os.path.join(log_dir, "short.log")
    _write_log(path, "line1\nline2\n")
    result = _read_last_lines(path, 100)
    assert result == ["line1", "line2"]
