import uuid
from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TrackPlay(Base):
    __tablename__ = "track_plays"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    track_name: Mapped[str]
    artist_name: Mapped[str]
    album_name: Mapped[str]
    album_mbid: Mapped[str | None]
    artist_mbid: Mapped[str | None]
    played_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=func.now())
