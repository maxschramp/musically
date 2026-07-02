"""Schemas for the unified search endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class SearchResult(BaseModel):
    """A single search result from any source."""

    source: str  # "musicbrainz", "spotify", "qobuz"
    type: str  # "album" | "artist"

    # Album fields
    title: str | None = None
    artist_name: str | None = None

    # Artist fields
    name: str | None = None

    # Identifiers (source-specific)
    mbid: str | None = None
    spotify_id: str | None = None
    qobuz_id: str | None = None

    # Metadata
    year: int | None = None

    # Library / queue status
    in_library: bool = False
    in_queue: bool = False


class SearchResponse(BaseModel):
    """Response for GET /api/search."""

    query: str
    results: list[SearchResult]
    warnings: list[str] = []
