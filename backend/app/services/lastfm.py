"""LastFM API polling service."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://ws.audioscrobbler.com/2.0/"


@dataclass
class LastFMTrack:
    """A single track returned by the LastFM API."""

    track_name: str
    artist_name: str
    album_name: str | None
    track_mbid: str | None
    artist_mbid: str | None
    played_at: datetime


@dataclass
class LastFMPagination:
    """Pagination metadata from a LastFM response."""

    page: int
    total_pages: int
    per_page: int
    total: int


@dataclass
class LastFMResponse:
    """A single page of tracks from LastFM, with pagination info."""

    tracks: list[LastFMTrack]
    pagination: LastFMPagination


class LastFMService:
    """Async client for the LastFM API (user.getRecentTracks)."""

    def __init__(
        self,
        api_key: str,
        user: str,
        rate_limit_rps: float = 4.5,
    ) -> None:
        self.api_key = api_key
        self.user = user
        self.rate_limit_rps = rate_limit_rps
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    async def fetch_recent_tracks(
        self,
        from_ts: int | None = None,
        to_ts: int | None = None,
        limit: int = 200,
        page: int = 1,
    ) -> LastFMResponse:
        """Fetch a single page of recent tracks from LastFM.

        Args:
            from_ts: Unix timestamp to fetch tracks from (inclusive).
            to_ts: Unix timestamp to fetch tracks up to (inclusive).
            limit: Number of tracks per page (max 200).
            page: Page number (1-indexed).

        Returns:
            LastFMResponse with parsed tracks and pagination metadata.
        """
        params: dict[str, str | int] = {
            "method": "user.getRecentTracks",
            "user": self.user,
            "api_key": self.api_key,
            "format": "json",
            "limit": min(limit, 200),
            "page": page,
        }
        if from_ts is not None:
            params["from"] = from_ts
        if to_ts is not None:
            params["to"] = to_ts

        logger.info(
            "Fetching LastFM recent tracks for user=%s page=%s limit=%s",
            self.user,
            page,
            limit,
        )

        try:
            response = await self.client.get("", params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            logger.error("LastFM API request failed: %s", exc)
            raise
        except ValueError as exc:
            logger.error("LastFM API returned invalid JSON: %s", exc)
            raise

        if "recenttracks" not in data:
            logger.warning(
                "LastFM response missing 'recenttracks' key. Keys: %s",
                list(data.keys()) if data else "empty",
            )
            return LastFMResponse(
                tracks=[],
                pagination=LastFMPagination(page=page, total_pages=0, per_page=limit, total=0),
            )

        recent_tracks = data["recenttracks"]
        raw_tracks: list[dict] = recent_tracks.get("track", [])
        if not isinstance(raw_tracks, list):
            raw_tracks = [raw_tracks]

        # Parse pagination
        attr = recent_tracks.get("@attr", {})
        try:
            pagination = LastFMPagination(
                page=int(attr.get("page", page)),
                total_pages=int(attr.get("totalPages", 0)),
                per_page=int(attr.get("perPage", limit)),
                total=int(attr.get("total", 0)),
            )
        except (ValueError, TypeError):
            pagination = LastFMPagination(page=page, total_pages=0, per_page=limit, total=0)

        tracks: list[LastFMTrack] = []
        for raw in raw_tracks:
            # Skip "now playing" tracks (no played_at date)
            track_attr = raw.get("@attr", {})
            if isinstance(track_attr, dict) and track_attr.get("nowplaying") == "true":
                continue

            # Parse played_at from date.uts
            date_info = raw.get("date", {})
            uts = date_info.get("uts")
            if uts is not None:
                try:
                    played_at = datetime.utcfromtimestamp(int(uts))
                except (ValueError, OSError):
                    continue
            else:
                continue

            track_name = str(raw.get("name", ""))
            artist_info = raw.get("artist", {})
            artist_name = str(artist_info.get("#text", "")) if isinstance(artist_info, dict) else ""
            album_info = raw.get("album", {})
            album_name = str(album_info.get("#text", "")) if isinstance(album_info, dict) else ""
            if not album_name:
                album_name = None

            track_mbid = raw.get("mbid")
            if track_mbid == "":
                track_mbid = None
            artist_mbid_raw = artist_info.get("mbid", "") if isinstance(artist_info, dict) else ""
            artist_mbid = artist_mbid_raw if artist_mbid_raw else None

            if not track_name or not artist_name:
                continue

            tracks.append(
                LastFMTrack(
                    track_name=track_name,
                    artist_name=artist_name,
                    album_name=album_name,
                    track_mbid=track_mbid if track_mbid else None,
                    artist_mbid=artist_mbid,
                    played_at=played_at,
                )
            )

        logger.info("Fetched %d tracks (page %d/%d)", len(tracks), pagination.page, pagination.total_pages)
        return LastFMResponse(tracks=tracks, pagination=pagination)

    async def fetch_all_recent(
        self,
        from_ts: int | None = None,
        to_ts: int | None = None,
        max_pages: int = 10,
    ) -> list[LastFMTrack]:
        """Fetch all recent tracks, handling pagination internally.

        Args:
            from_ts: Unix timestamp to fetch from (inclusive).
            to_ts: Unix timestamp to fetch to (inclusive).
            max_pages: Maximum number of pages to fetch (safety limit).

        Returns:
            Combined list of all tracks across all pages.
        """
        all_tracks: list[LastFMTrack] = []

        # Fetch first page
        first_resp = await self.fetch_recent_tracks(from_ts=from_ts, to_ts=to_ts, page=1)
        all_tracks.extend(first_resp.tracks)

        total_pages = first_resp.pagination.total_pages
        pages_to_fetch = min(total_pages, max_pages)

        if pages_to_fetch <= 1:
            return all_tracks

        # Fetch remaining pages with rate limiting
        for page in range(2, pages_to_fetch + 1):
            await asyncio.sleep(1.0 / self.rate_limit_rps)
            try:
                resp = await self.fetch_recent_tracks(
                    from_ts=from_ts, to_ts=to_ts, page=page
                )
                all_tracks.extend(resp.tracks)
            except Exception:
                logger.exception("Failed to fetch page %d; returning %d tracks collected so far", page, len(all_tracks))
                break

        logger.info("Fetched %d total tracks across %d pages", len(all_tracks), pages_to_fetch)
        return all_tracks

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()
