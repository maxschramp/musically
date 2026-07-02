import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    playlist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("playlists.id"), nullable=False)
    track_name: Mapped[str]
    artist_name: Mapped[str]
    album_name: Mapped[str]
    spotify_uri: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    playlist: Mapped["Playlist"] = relationship(back_populates="tracks")
