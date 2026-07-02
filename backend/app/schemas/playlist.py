import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.playlist import PlaylistType
from app.schemas.track_play import TrackPlayResponse


class PlaylistTrackResponse(BaseModel):
    """Minimal track info inside a playlist."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    track_name: str
    artist_name: str
    album_name: str
    spotify_uri: str


class PlaylistResponse(BaseModel):
    """Schema for playlist API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    spotify_id: str
    name: str
    playlist_type: PlaylistType
    is_active: bool
    last_synced_at: datetime | None
    tracks: list[PlaylistTrackResponse] = []


class PlaylistUpdate(BaseModel):
    """Schema for updating a playlist."""
    playlist_type: PlaylistType | None = None
    is_active: bool | None = None
