import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrackPlayResponse(BaseModel):
    """Schema for track play API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    track_name: str
    artist_name: str
    album_name: str
    album_mbid: str | None
    artist_mbid: str | None
    played_at: datetime
    created_at: datetime
