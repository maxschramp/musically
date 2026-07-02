from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class StatsResponse(BaseModel):
    """Application-wide statistics."""
    total_albums: int = 0
    total_tracks: int = 0
    total_artists: int = 0
    queued_count: int = 0
    downloading_count: int = 0
    downloaded_count: int = 0
    stalled_count: int = 0
    rejected_count: int = 0
    subscribed_artists: int = 0
    watch_folder_pending: int = 0
