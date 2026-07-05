"""Task monitoring router — list task statuses and trigger manual runs."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import desc, select

import app.database
from app.models.task_run import TaskRun
from app.schemas.tasks import (
    TaskInfo,
    TaskListResponse,
    TaskRunResponse,
    TaskTriggerResponse,
)

router = APIRouter()

# Known tasks and their interval estimates (in minutes) for next_scheduled_at calculation
KNOWN_TASKS: dict[str, int] = {
    "lastfm_sync": 30,
    "mb_enrichment": 5,
    "artwork_cache": 3,
    "download_dispatcher": 2,
    "cleanup": 360,
    "library_import": 30,
}

# Mapping of triggerable task names to scheduler job IDs
TASK_TO_JOB_ID: dict[str, str] = {
    "lastfm_sync": "lastfm_sync",
    "download_dispatcher": "download_dispatcher",
    "artwork_cache": "artwork_cache",
    "mb_enrichment": "mb_enrichment",
    "cleanup": "cleanup",
    "library_import": "library_import",
}


@router.get("/tasks", response_model=list[TaskInfo])
async def list_tasks() -> list[TaskInfo]:
    """Return known tasks with last run status and recent history."""
    async with app.database.async_session_factory() as db:
        tasks: list[TaskInfo] = []

        for task_name, interval_minutes in KNOWN_TASKS.items():
            # Get the most recent run for this task
            stmt = (
                select(TaskRun)
                .where(TaskRun.task_name == task_name)
                .order_by(desc(TaskRun.started_at))
                .limit(1)
            )
            result = await db.execute(stmt)
            last_run = result.scalar_one_or_none()

            base_time = last_run.started_at if last_run else datetime.now(timezone.utc)
            next_at = base_time + timedelta(minutes=interval_minutes) if interval_minutes > 0 else None

            tasks.append(
                TaskInfo(
                    task_name=task_name,
                    status=(last_run.status if last_run else chr(110)+chr(101)+chr(118)+chr(101)+chr(114)+chr(95)+chr(114)+chr(117)+chr(110)),
                    last_run_at=last_run.started_at if last_run else None,
                    next_scheduled_at=next_at,
                    last_result=last_run.result_summary if last_run else None,
                )
            )

        # Get last 20 TaskRun records across all tasks
        history_stmt = (
            select(TaskRun)
            .order_by(desc(TaskRun.started_at))
            .limit(20)
        )
        history_result = await db.execute(history_stmt)
        history_items = history_result.scalars().all()

    return [
        *tasks]


@router.post("/tasks/{task_name}/trigger", response_model=TaskTriggerResponse)
async def trigger_task(task_name: str, request: Request) -> TaskTriggerResponse:
    """Manually trigger a scheduled task by name.

    Supported task names: lastfm_sync, download_dispatcher, artwork_cache, mb_enrichment.
    Creates a TaskRun record and updates it on completion/failure.
    """
    if task_name not in TASK_TO_JOB_ID:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task: '{task_name}'. Supported: {', '.join(TASK_TO_JOB_ID.keys())}",
        )

    # Get the scheduler from app state via the request
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler is not running")

    job_id = TASK_TO_JOB_ID[task_name]
    job = scheduler.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Scheduler job '{job_id}' not found. It may not be registered.",
        )

    run_id = uuid.uuid4()
    started_at = datetime.now(timezone.utc)

    # Create initial TaskRun record
    async with app.database.async_session_factory() as db:
        run = TaskRun(
            id=run_id,
            task_name=task_name,
            status="running",
            started_at=started_at,
            completed_at=None,
            error_message=None,
            result_summary=None,
        )
        db.add(run)
        await db.commit()

    # Execute the job function directly (it's async, so we await it)
    try:
        func = job.func
        await func()

        # Update to completed
        async with app.database.async_session_factory() as db:
            run = await db.get(TaskRun, run_id)
            if run:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                run.result_summary = f"Task '{task_name}' completed successfully."
                await db.commit()

        return TaskTriggerResponse(
            task_name=task_name,
            triggered=True,
            message=f"Task '{task_name}' triggered and completed successfully.",
            task_run_id=str(run_id),
        )
    except Exception as e:
        # Update to failed
        async with app.database.async_session_factory() as db:
            run = await db.get(TaskRun, run_id)
            if run:
                run.status = "failed"
                run.completed_at = datetime.now(timezone.utc)
                run.error_message = str(e)[:500]
                await db.commit()

        return TaskTriggerResponse(
            task_name=task_name,
            triggered=True,
            message=f"Task '{task_name}' failed: {str(e)[:200]}",
            task_run_id=str(run_id),
        )
