"""MusicBrainz API service.

Uses the MusicBrainz REST API v2 (https://musicbrainz.org/ws/2/).
Rate-limited to 1 request per second as required by MusicBrainz.
"""

from __future__ import annotations

import asyncio
import time

import httpx

MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"
HEADERS = {"User-Agent": "Musically/0.1 (https://github.com/maxschramp/musically)"}
RATE_LIMIT_SECONDS = 1.1


class MusicBrainzService:
    """Async client for MusicBrainz API.

    Handles search, release lookups, and rate limiting.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._last_request: float = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=HEADERS,
                timeout=httpx.Timeout(30.0),
            )
        return self._client

    async def _rate_limit(self) -> None:
        """Ensure at least RATE_LIMIT_SECONDS between requests."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < RATE_LIMIT_SECONDS:
            await asyncio.sleep(RATE_LIMIT_SECONDS - elapsed)
        self._last_request = time.monotonic()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # check_new_releases — retained from stub for backward compat
    # ------------------------------------------------------------------
    async def check_new_releases(self, artist_mbid: str) -> list[dict]:
        """Check for new releases by an artist's MBID.

        Queries MusicBrainz for releases by the artist and returns
        those with a release date in the last 90 days.
        """
        client = await self._get_client()
        await self._rate_limit()

        url = f"{MUSICBRAINZ_API}/release/"
        params = {
            "artist": artist_mbid,
            "inc": "artists+labels",
            "fmt": "json",
            "limit": 25,
        }
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        # Filter to recent releases (last 90 days)
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=90)
        recent: list[dict] = []
        for release in data.get("releases", []):
            date_str = release.get("date", "")
            try:
                release_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                # Partial dates like "2026" or "2026-07" — treat as recent
                recent.append(release)
                continue
            if release_date >= cutoff:
                recent.append(release)

        return recent

    # ------------------------------------------------------------------
    # search_album
    # ------------------------------------------------------------------
    async def search_album(self, artist: str, album: str) -> dict | None:
        """Search MusicBrainz for an album by artist and title.

        Returns the first matching release dict, or None if not found.
        """
        client = await self._get_client()
        await self._rate_limit()

        query = f'artist:"{artist}" AND release:"{album}"'
        url = f"{MUSICBRAINZ_API}/release/"
        params = {"query": query, "fmt": "json", "limit": 1}

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        releases = data.get("releases", [])
        return releases[0] if releases else None

    # ------------------------------------------------------------------
    # get_release_tracks
    # ------------------------------------------------------------------
    async def get_release_tracks(self, mbid: str) -> list[dict]:
        """Get track listing for a release by MBID.

        Returns a list of dicts with keys: position, title, length, id.
        """
        client = await self._get_client()
        await self._rate_limit()

        url = f"{MUSICBRAINZ_API}/release/{mbid}"
        params = {"inc": "recordings", "fmt": "json"}

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        tracks: list[dict] = []
        for medium in data.get("media", []):
            for track in medium.get("tracks", []):
                recording = track.get("recording", {})
                tracks.append({
                    "position": int(track.get("position", 0)),
                    "title": track.get("title", recording.get("title", "")),
                    "length_ms": int(track.get("length", recording.get("length", 0)) or 0),
                    "id": recording.get("id", ""),
                })

        return tracks

    # ------------------------------------------------------------------
    # get_album_tracklist
    # ------------------------------------------------------------------
    async def get_album_tracklist(self, artist: str, album: str) -> dict | None:
        """Search for an album and return its track listing.

        Returns a dict with keys: mbid, title, artist, tracks, track_count,
        or None if the album could not be found.
        """
        release = await self.search_album(artist, album)
        if release is None:
            return None

        mbid = release.get("id", "")
        tracks = await self.get_release_tracks(mbid)

        return {
            "mbid": mbid,
            "title": release.get("title", album),
            "artist": release.get("artist-credit", [{}])[0].get("name", artist) if release.get("artist-credit") else artist,
            "tracks": tracks,
            "track_count": len(tracks),
        }

    # ------------------------------------------------------------------
    # search — general query search for albums or artists
    # ------------------------------------------------------------------
    async def search(self, query: str, search_type: str = "album") -> list[dict]:
        """Search MusicBrainz for releases or artists by a general query string.

        Args:
            query: Free-text search query.
            search_type: ``"album"`` (release search) or ``"artist"`` (artist search).

        Returns:
            List of normalised dicts with keys: mbid, title/name,
            artist_name (album only), year, type.
        """
        client = await self._get_client()
        await self._rate_limit()

        if search_type == "artist":
            url = f"{MUSICBRAINZ_API}/artist/"
            params = {"query": f'artist:"{query}"', "fmt": "json", "limit": 10}
        else:
            url = f"{MUSICBRAINZ_API}/release/"
            params = {"query": f'release:"{query}"', "fmt": "json", "limit": 10}

        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        results: list[dict] = []
        if search_type == "artist":
            for item in data.get("artists", []):
                results.append({
                    "mbid": item.get("id", ""),
                    "name": item.get("name", ""),
                    "type": "artist",
                })
        else:
            for item in data.get("releases", []):
                artist_name = ""
                if item.get("artist-credit"):
                    artist_name = item["artist-credit"][0].get("name", "")
                year_str = item.get("date", "")
                year: int | None = None
                if year_str and len(year_str) >= 4:
                    try:
                        year = int(year_str[:4])
                    except (ValueError, TypeError):
                        pass
                results.append({
                    "mbid": item.get("id", ""),
                    "title": item.get("title", ""),
                    "artist_name": artist_name,
                    "year": year,
                    "type": "album",
                })

        return results

