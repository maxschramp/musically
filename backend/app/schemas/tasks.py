"""Schemas for the Task Monitoring system."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class TaskRunResponse(BaseModel):
    """Response for a single TaskRun record."""
    id: str
    task_name: str
    status: str = 'never_run'
    started_at: datetime
    completed_at: datetime | None
    error_message: str | None
    result_summary: str | None

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_uuid_to_str(cls, v: object) -> str:
        """Convert UUID objects to strings for JSON serialization."""
        if isinstance(v, UUID):
            return str(v)
        return str(v) if not isinstance(v, str) else v


class TaskInfo(BaseModel):
    """Summary info for a known task."""
    task_name: str
    status: str = 'never_run'
    last_run_at: datetime | None
    next_scheduled_at: datetime | None
    last_result: str | None


class TaskListResponse(BaseModel):
    """Response for GET /api/tasks."""
    tasks: list[TaskInfo]
    recent_history: list[TaskRunResponse]


class TaskTriggerResponse(BaseModel):
    """Response for POST /api/tasks/{task_name}/trigger."""
    task_name: str
    triggered: bool
    message: str
    task_run_id: str | None
