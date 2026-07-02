import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.album import AlbumStatus, QueueType


class AlbumCreate(BaseModel):
    """Schema for creating a new album queue entry."""
    title: str = Field(..., min_length=1)
    artist_name: str = Field(..., min_length=1)
    album_mbid: str | None = None
    qobuz_id: str | None = None
    queue_type: QueueType = QueueType.MANUAL
    reason: str = Field(default="Manual add", min_length=1)


class AlbumBulkItem(BaseModel):
    """A single album within a bulk creation request."""
    title: str = Field(..., min_length=1)
    artist_name: str = Field(..., min_length=1)
    album_mbid: str | None = None
    qobuz_id: str | None = None
    queue_type: QueueType = QueueType.MANUAL
    reason: str = Field(default="Manual add", min_length=1)


class AlbumBulkCreate(BaseModel):
    """Schema for creating multiple album queue entries at once."""
    albums: list[AlbumBulkItem] = Field(..., min_length=1)


class AlbumResponse(BaseModel):
    """Schema for album API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    artist_name: str
    album_mbid: str | None
    qobuz_id: str | None
    status: AlbumStatus
    queue_type: QueueType
    reason: str
    play_count: int
    retry_count: int
    next_retry_at: datetime | None
    downloaded_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Track listing (filesystem)
# ---------------------------------------------------------------------------

class AlbumTrackItem(BaseModel):
    """A single audio file found in an album folder."""
    filename: str
    size: int
    format: str
    path: str


class AlbumTracksResponse(BaseModel):
    """Response for GET /albums/{id}/tracks."""
    album_id: uuid.UUID
    artist: str
    title: str
    folder_path: str | None
    tracks: list[AlbumTrackItem]
    track_count: int


# ---------------------------------------------------------------------------
# MusicBrainz metadata
# ---------------------------------------------------------------------------

class MusicBrainzTrackItem(BaseModel):
    """A track from the MusicBrainz release listing."""
    position: int
    title: str
    length_ms: int
    mbid: str


class MusicBrainzAlbumResponse(BaseModel):
    """Response for GET /albums/{id}/musicbrainz."""
    found: bool
    mbid: str | None
    title: str | None
    artist: str | None
    tracks: list[MusicBrainzTrackItem]
    track_count: int
    source: str = "musicbrainz"  # "musicbrainz" or "spotify"
