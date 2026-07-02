"""Schemas for sync-related API responses."""

import json
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class SyncResultResponse(BaseModel):
    """Response schema for a sync trigger result."""

    sync_id: uuid.UUID
    started_at: datetime
    completed_at: datetime
    status: str
    tracks_fetched: int
    tracks_new: int
    albums_updated: int
    artists_updated: int
    albums_queued_auto: int = 0
    albums_queued_manual: int = 0
    artists_subscribed: int = 0
    rules_fired: list[str] | None = None
    error_message: str | None


class SyncHistoryResponse(BaseModel):
    """Response schema for a sync history entry."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    started_at: datetime
    completed_at: datetime | None
    status: str
    tracks_fetched: int
    tracks_new: int
    albums_updated: int
    artists_updated: int
    albums_queued_auto: int = 0
    albums_queued_manual: int = 0
    artists_subscribed: int = 0
    rules_fired: list[str] | None = None
    error_message: str | None
    created_at: datetime

    @field_validator("rules_fired", mode="before")
    @classmethod
    def parse_rules_fired(cls, v: object) -> list[str] | None:
        """Convert a JSON string from the DB into a list, or pass through."""
        if v is None:
            return None
        if isinstance(v, list):
            return v  # already a list (e.g. from SyncResultResponse serialization)
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return None
