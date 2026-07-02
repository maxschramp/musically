import uuid
from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str]
    artist_mbid: Mapped[str | None]
    subscribed: Mapped[bool] = mapped_column(default=False)
    subscription_source: Mapped[str | None]  # "auto_play_count" | "auto_library_size" | "manual"
    albums_in_library: Mapped[int] = mapped_column(default=0)
    total_play_count: Mapped[int] = mapped_column(default=0)
    last_mb_check: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=func.now())
