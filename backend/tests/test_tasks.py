"""Tests for the task monitoring router."""

from __future__ import annotations

import uuid as uuid_mod
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task_run import TaskRun


# ---------------------------------------------------------------------------
# GET /api/tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tasks_returns_known_tasks(client: AsyncClient) -> None:
    """GET /api/tasks should return all 4 known tasks with status info."""
    response = await client.get("/api/tasks")
    assert response.status_code == 200
    data = response.json()

    assert "tasks" in data
    assert "recent_history" in data

    task_names = [t["task_name"] for t in data["tasks"]]
    assert "lastfm_sync" in task_names
    assert "mb_enrichment" in task_names
    assert "artwork_cache" in task_names
    assert "download_dispatcher" in task_names

    # No runs yet — all should have null status
    for task in data["tasks"]:
        assert task["last_run_status"] is None
        assert task["last_run_at"] is None
        assert task["last_result_summary"] is None
        # next_scheduled_at should still be set (based on now + interval)
        assert task["next_scheduled_at"] is not None

    assert data["recent_history"] == []


@pytest.mark.asyncio
async def test_list_tasks_includes_recent_history(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /api/tasks should include recent TaskRun history."""
    from datetime import datetime, timezone

    run = TaskRun(
        task_name="lastfm_sync",
        status="completed",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        result_summary="Synced 50 tracks",
    )
    db_session.add(run)
    await db_session.commit()

    response = await client.get("/api/tasks")
    assert response.status_code == 200
    data = response.json()

    # The task that has a run should show last_run_status
    lastfm_task = next(t for t in data["tasks"] if t["task_name"] == "lastfm_sync")
    assert lastfm_task["last_run_status"] == "completed"
    assert lastfm_task["last_result_summary"] == "Synced 50 tracks"

    # Recent history should include our run
    assert len(data["recent_history"]) == 1
    assert data["recent_history"][0]["task_name"] == "lastfm_sync"
    assert data["recent_history"][0]["status"] == "completed"


# ---------------------------------------------------------------------------
# POST /api/tasks/{task_name}/trigger
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_unknown_task_returns_400(client: AsyncClient) -> None:
    """POST /api/tasks/nonexistent/trigger should return 400."""
    response = await client.post("/api/tasks/nonexistent/trigger")
    assert response.status_code == 400
    data = response.json()
    assert "Unknown task" in data["detail"]


@pytest.mark.asyncio
async def test_trigger_task_no_scheduler_returns_503(client: AsyncClient) -> None:
    """POST /api/tasks/lastfm_sync/trigger without scheduler should return 503."""
    # Tests run without lifespan, so app.state.scheduler is not set
    response = await client.post("/api/tasks/lastfm_sync/trigger")
    assert response.status_code == 503
    data = response.json()
    assert "Scheduler is not running" in data["detail"]


@pytest.mark.asyncio
async def test_trigger_task_creates_run_and_updates(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/tasks/lastfm_sync/trigger with mock scheduler creates TaskRun."""
    from app.main import app

    # Create a mock job whose func is an async no-op
    mock_job = MagicMock()
    mock_job.func = AsyncMock()  # awaitable no-op

    mock_scheduler = MagicMock()
    mock_scheduler.get_job.return_value = mock_job

    # Set the mock scheduler on app state
    app.state.scheduler = mock_scheduler

    try:
        response = await client.post("/api/tasks/lastfm_sync/trigger")
        assert response.status_code == 200
        data = response.json()
        assert data["triggered"] is True
        assert data["task_name"] == "lastfm_sync"
        assert data["task_run_id"] is not None
        assert "completed successfully" in data["message"]

        # Verify TaskRun was created and marked complete
        run_id = uuid_mod.UUID(data["task_run_id"])
        run = await db_session.get(TaskRun, run_id)
        assert run is not None
        assert run.task_name == "lastfm_sync"
        assert run.status == "completed"
        assert run.completed_at is not None
        assert run.error_message is None
    finally:
        # Clean up — remove mock scheduler
        delattr(app.state, "scheduler")


@pytest.mark.asyncio
async def test_trigger_task_records_failure(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST trigger with a failing job should record failure status."""
    from app.main import app

    # Create a mock job that raises
    mock_job = MagicMock()
    async def _failing_func() -> None:
        raise RuntimeError("Simulated job failure")
    mock_job.func = _failing_func

    mock_scheduler = MagicMock()
    mock_scheduler.get_job.return_value = mock_job

    app.state.scheduler = mock_scheduler

    try:
        response = await client.post("/api/tasks/lastfm_sync/trigger")
        assert response.status_code == 200
        data = response.json()
        assert data["triggered"] is True
        assert "failed" in data["message"]
        assert "Simulated job failure" in data["message"]

        # Verify TaskRun was created and marked failed
        run_id = uuid_mod.UUID(data["task_run_id"])
        run = await db_session.get(TaskRun, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.error_message is not None
        assert "Simulated job failure" in run.error_message
    finally:
        delattr(app.state, "scheduler")
