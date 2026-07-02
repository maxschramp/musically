import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AlbumStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    STALLED = "stalled"
    REJECTED = "rejected"


class QueueType(str, enum.Enum):
    AUTO = "auto"
    MANUAL = "manual"
    WATCH_FOLDER = "watch_folder"


class Album(Base):
    __tablename__ = "albums"
    __table_args__ = (
        UniqueConstraint('artist_name', 'title', name='uq_album_artist_title'),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str]
    artist_name: Mapped[str]
    album_mbid: Mapped[str | None]
    qobuz_id: Mapped[str | None]
    status: Mapped[AlbumStatus] = mapped_column(Enum(AlbumStatus, name="album_status", create_type=False), default=AlbumStatus.QUEUED)
    queue_type: Mapped[QueueType] = mapped_column(Enum(QueueType, name="queue_type", create_type=False), default=QueueType.MANUAL)
    reason: Mapped[str] = mapped_column(default="")
    play_count: Mapped[int] = mapped_column(default=0)
    retry_count: Mapped[int] = mapped_column(default=0)
    next_retry_at: Mapped[datetime | None]
    downloaded_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=func.now())
