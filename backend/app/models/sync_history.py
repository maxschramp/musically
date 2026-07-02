"""SyncHistory model — records each sync run for observability."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SyncHistory(Base):
    __tablename__ = "sync_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    started_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(20), default="completed")
    # "completed" | "failed" | "skipped"
    tracks_fetched: Mapped[int] = mapped_column(default=0)
    tracks_new: Mapped[int] = mapped_column(default=0)
    albums_updated: Mapped[int] = mapped_column(default=0)
    artists_updated: Mapped[int] = mapped_column(default=0)

    # Rule engine metrics
    albums_queued_auto: Mapped[int] = mapped_column(default=0)
    albums_queued_manual: Mapped[int] = mapped_column(default=0)
    artists_subscribed: Mapped[int] = mapped_column(default=0)
    rules_fired: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_message: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=func.now())
