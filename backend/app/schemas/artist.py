import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ArtistCreate(BaseModel):
    """Schema for manually creating an artist."""
    name: str = Field(..., min_length=1, description="Artist name")
    artist_mbid: str | None = None


class ArtistResponse(BaseModel):
    """Schema for artist API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    artist_mbid: str | None
    subscribed: bool
    subscription_source: str | None
    albums_in_library: int
    total_play_count: int
    last_mb_check: datetime | None
    created_at: datetime


class ArtistLookupRequest(BaseModel):
    """Schema for artist lookup/subscribe-by-name request body."""
    artist_name: str = Field(..., min_length=1, description="Artist name (case-insensitive lookup)")
