"""Qobuz API client — async wrapper for searching and downloading from Qobuz.

Adapted from Reference Code/minimal-downloader.py.
Uses httpx.AsyncClient throughout. Credentials are scraped fresh each session
from open.qobuz.com (Qobuz rotates app_id/app_secret periodically).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.qobuz.com/api.json/0.2"
OPEN_QOBUZ_URL = "https://open.qobuz.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)

# Credential scraping regex patterns (must match the reference code patterns)
BUNDLE_SRC_RE = re.compile(
    r'<script[^>]+src="([^"]+(?:/js/main\.js|/resources/[^"]+/js/[^"]+\.js))"'
)
CREDS_RE = re.compile(
    r'app_id:"(?P<app_id>\d{9})",app_secret:"(?P<app_secret>[a-f0-9]{32})"'
)

# Format constants
FMT_MP3_320 = 5
FMT_FLAC_16 = 6
FMT_FLAC_24_96 = 7
FMT_FLAC_24_192 = 27
FMT_FALLBACK_MAP = {7: 6, 27: 6}  # fall back to 16-bit FLAC on 400


@dataclass
class QobuzAlbum:
    """Represents a Qobuz album search result."""
    qobuz_id: str
    title: str
    artist_name: str
    cover_url: str | None = None
    track_count: int = 0
    tracks: list[QobuzTrack] = field(default_factory=list)


@dataclass
class QobuzTrack:
    """Represents a single track within a Qobuz album."""
    track_id: int
    title: str
    track_number: int
    duration: int  # seconds
    isrc: str | None = None


class QobuzService:
    """Async Qobuz API client with credential scraping, auth, search, and download."""

    def __init__(
        self,
        email: str,
        password: str,
        rate_limit_rps: float = 2.0,
    ) -> None:
        if not email or not password:
            raise ValueError("Qobuz email and password are required")

        self.email = email
        self.password = password
        self.rate_limit_rps = rate_limit_rps
        self._min_interval: float = 1.0 / rate_limit_rps if rate_limit_rps > 0 else 0.0
        self._last_call: float = 0.0

        self.app_id: str | None = None
        self.app_secret: str | None = None
        self.user_auth_token: str | None = None

        self.client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(60.0, connect=15.0),
        )

    # ------------------------------------------------------------------
    # Rate limiting helper
    # ------------------------------------------------------------------
    async def _rate_limit(self) -> None:
        """Sleep if needed to respect the rate limit."""
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_call = time.monotonic()

    # ------------------------------------------------------------------
    # Credential scraping
    # ------------------------------------------------------------------
    async def _fetch_app_credentials(self) -> tuple[str, str]:
        """Scrape app_id and app_secret from the open.qobuz.com web player JS bundle.

        Qobuz rotates these periodically, so we scrape fresh each session.
        Returns (app_id, app_secret).
        """
        logger.info("Fetching Qobuz app credentials from %s ...", OPEN_QOBUZ_URL)

        # Step 1: Load the shell page to find the JS bundle URL
        shell_resp = await self.client.get(f"{OPEN_QOBUZ_URL}/track/1")
        shell_resp.raise_for_status()

        m = BUNDLE_SRC_RE.search(shell_resp.text)
        if not m:
            raise RuntimeError("Could not find JS bundle URL in open.qobuz.com shell")

        bundle_path = m.group(1)
        if bundle_path.startswith("/"):
            bundle_url = f"{OPEN_QOBUZ_URL}{bundle_path}"
        else:
            bundle_url = bundle_path

        # Step 2: Fetch the JS bundle to extract credentials
        bundle_resp = await self.client.get(bundle_url)
        bundle_resp.raise_for_status()

        creds = CREDS_RE.search(bundle_resp.text)
        if not creds:
            raise RuntimeError("app_id/app_secret pattern not found in JS bundle")

        app_id = creds.group("app_id")
        app_secret = creds.group("app_secret")
        logger.info("Got Qobuz credentials: app_id=%s", app_id)
        return app_id, app_secret

    async def _ensure_credentials(self) -> None:
        """Ensure we have valid app credentials, scraping if needed."""
        if self.app_id is None or self.app_secret is None:
            self.app_id, self.app_secret = await self._fetch_app_credentials()
            self.client.headers["X-App-Id"] = self.app_id

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    async def _login(self) -> str:
        """Authenticate with Qobuz and return the user_auth_token."""
        await self._ensure_credentials()

        resp = await self.client.post(
            f"{BASE_URL}/user/login",
            params={
                "email": self.email,
                "password": self.password,
                "app_id": self.app_id,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["user_auth_token"]
        logger.info("Qobuz login successful")
        return token

    async def _ensure_authenticated(self) -> None:
        """Ensure we have a valid auth token, logging in if needed."""
        if self.user_auth_token is None:
            self.user_auth_token = await self._login()
            self.client.headers["X-User-Auth-Token"] = self.user_auth_token

    # ------------------------------------------------------------------
    # Auth-aware request helper with token refresh on 401
    # ------------------------------------------------------------------
    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_data: dict | None = None,
        retry_auth: bool = True,
    ) -> httpx.Response:
        """Make an API request with automatic rate limiting and token refresh.

        If retry_auth is True and we get a 401, we re-login and retry once.
        """
        await self._ensure_authenticated()
        await self._rate_limit()

        resp = await self.client.request(method, url, params=params, json=json_data)

        if resp.status_code == 401 and retry_auth:
            logger.info("Qobuz returned 401, refreshing auth token...")
            self.user_auth_token = None  # force re-login
            await self._ensure_authenticated()
            await self._rate_limit()
            resp = await self.client.request(method, url, params=params, json=json_data)

        return resp

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    async def search_album(self, artist: str, album: str) -> QobuzAlbum | None:
        """Search Qobuz for an album by artist and album name.

        Returns the best-matching QobuzAlbum or None if not found.
        """
        query = f"{artist} {album}"
        resp = await self._request(
            "GET",
            f"{BASE_URL}/album/search",
            params={"query": query, "limit": 10},
        )
        resp.raise_for_status()

        data = resp.json()
        items = (data.get("albums") or {}).get("items", [])
        if not items:
            logger.info("No Qobuz results for query=%r", query)
            return None

        # Take the first result (best match)
        item = items[0]
        result = QobuzAlbum(
            qobuz_id=str(item["id"]),
            title=item.get("title", ""),
            artist_name=(item.get("artist") or {}).get("name", ""),
            cover_url=item.get("image", {}).get("large") or None,
            track_count=item.get("tracks_count", 0),
        )
        logger.info("Qobuz search found: %s - %s (id=%s)", result.artist_name, result.title, result.qobuz_id)
        return result

    async def search(self, query: str) -> list[dict]:
        """General album search on Qobuz by query string.

        Unlike :meth:`search_album`, this accepts a single free-text query
        and returns a list of normalised dicts (not a QobuzAlbum).

        Args:
            query: Free-text search query.

        Returns:
            List of dicts with keys: qobuz_id, title, artist_name, year, type.
        """
        resp = await self._request(
            "GET",
            f"{BASE_URL}/album/search",
            params={"query": query, "limit": 10},
        )
        resp.raise_for_status()

        data = resp.json()
        items = (data.get("albums") or {}).get("items", [])

        results: list[dict] = []
        for item in items:
            year: int | None = None
            date_str = item.get("release_date_original", "")
            if date_str and len(date_str) >= 4:
                try:
                    year = int(date_str[:4])
                except (ValueError, TypeError):
                    pass
            results.append({
                "qobuz_id": str(item["id"]),
                "title": item.get("title", ""),
                "artist_name": (item.get("artist") or {}).get("name", ""),
                "year": year,
                "type": "album",
            })

        logger.info("Qobuz general search for %r returned %d results", query, len(results))
        return results

    async def get_album_tracks(self, album_id: str) -> list[QobuzTrack]:
        """Fetch the full track listing for a Qobuz album."""
        resp = await self._request(
            "GET",
            f"{BASE_URL}/album/get",
            params={"album_id": album_id},
        )
        resp.raise_for_status()

        data = resp.json()
        tracks_data = data.get("tracks", {}).get("items", [])

        tracks: list[QobuzTrack] = []
        for t in tracks_data:
            tracks.append(QobuzTrack(
                track_id=t["id"],
                title=t.get("title", ""),
                track_number=t.get("track_number", 0),
                duration=t.get("duration", 0),
                isrc=t.get("isrc"),
            ))

        return tracks

    async def search_album_with_tracks(self, artist: str, album: str) -> QobuzAlbum | None:
        """Search for an album and populate its track listing in one call."""
        result = await self.search_album(artist, album)
        if result is None:
            return None
        result.tracks = await self.get_album_tracks(result.qobuz_id)
        return result

    # ------------------------------------------------------------------
    # Signed stream URL (MD5 signature as in reference code)
    # ------------------------------------------------------------------
    async def _get_stream_url(self, track_id: int, fmt: int) -> str:
        """Get a signed, time-limited stream URL for a track.

        Uses MD5 signature: md5("trackgetFileUrlformat_id{fmt}intentstreamtrack_id{id}{ts}{app_secret}")
        """
        await self._ensure_credentials()
        assert self.app_secret is not None

        ts = str(int(time.time()))
        raw = f"trackgetFileUrlformat_id{fmt}intentstreamtrack_id{track_id}{ts}{self.app_secret}"
        sig = hashlib.md5(raw.encode()).hexdigest()

        resp = await self._request(
            "GET",
            f"{BASE_URL}/track/getFileUrl",
            params={
                "request_ts": ts,
                "request_sig": sig,
                "track_id": track_id,
                "format_id": fmt,
                "intent": "stream",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        url = data.get("url")
        if not url:
            raise RuntimeError(f"No stream URL returned (response={data!r})")
        return url

    # ------------------------------------------------------------------
    # Download track to file
    # ------------------------------------------------------------------
    async def download_track(
        self,
        track_id: int,
        dest_path: str | Path,
        fmt: int = FMT_FLAC_24_192,
    ) -> bool:
        """Download a single track to the given file path.

        Tries the requested format first; falls back to 16-bit FLAC on 400 error.
        Returns True on success.
        """
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            url = await self._get_stream_url(track_id, fmt)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 400 and fmt in FMT_FALLBACK_MAP:
                fallback_fmt = FMT_FALLBACK_MAP[fmt]
                logger.info(
                    "format_id=%d unavailable for track_id=%d, falling back to %d",
                    fmt, track_id, fallback_fmt,
                )
                url = await self._get_stream_url(track_id, fallback_fmt)
            else:
                raise

        # Stream the file to disk
        await self._rate_limit()
        async with self.client.stream("GET", url) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                async for chunk in r.aiter_bytes(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

        logger.info("Downloaded track_id=%d to %s", track_id, dest_path)
        return True

    # ------------------------------------------------------------------
    # Download full album
    # ------------------------------------------------------------------
    async def download_album(
        self,
        qobuz_album_id: str,
        dest_dir: str | Path,
        fmt: int = FMT_FLAC_24_192,
    ) -> bool:
        """Download all tracks of a Qobuz album to dest_dir.

        Files are named: {tracknum:02d} - {title}.flac
        Returns True if all tracks downloaded successfully.
        """
        dest_dir = Path(dest_dir)
        tracks = await self.get_album_tracks(qobuz_album_id)

        if not tracks:
            logger.warning("No tracks found for Qobuz album %s", qobuz_album_id)
            return False

        for track in tracks:
            safe_title = re.sub(r'[\\/:*?"<>|]', "_", track.title).strip()
            filename = f"{track.track_number:02d} - {safe_title}.flac"
            dest_path = dest_dir / filename

            try:
                await self.download_track(track.track_id, dest_path, fmt)
            except Exception:
                logger.exception(
                    "Failed to download track %d (%s) from album %s",
                    track.track_id, track.title, qobuz_album_id,
                )
                return False

        logger.info("Downloaded %d tracks for album %s", len(tracks), qobuz_album_id)
        return True

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()

