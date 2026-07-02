import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PlaylistType(str, enum.Enum):
    SEASONAL = "seasonal"
    DISCOVER = "discover"
    OTHER = "other"


class Playlist(Base):
    __tablename__ = "playlists"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    spotify_id: Mapped[str]
    name: Mapped[str]
    playlist_type: Mapped[PlaylistType] = mapped_column(Enum(PlaylistType, name="playlist_type", create_type=False), default=PlaylistType.OTHER)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_synced_at: Mapped[datetime | None]

    tracks: Mapped[list["PlaylistTrack"]] = relationship(back_populates="playlist", cascade="all, delete-orphan")
