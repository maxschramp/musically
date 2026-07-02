"""Spotify API service — OAuth PKCE, playlist sync, and track fetching.

Uses httpx.AsyncClient for all HTTP calls. Tokens are stored encrypted in
the Settings table and managed via the db session passed to methods that
require authentication.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.playlist import Playlist, PlaylistType
from app.models.playlist_track import PlaylistTrack
from app.models.setting import Setting

logger = logging.getLogger(__name__)

SPOTIFY_ACCOUNTS_URL = "https://accounts.spotify.com"
SPOTIFY_API_URL = "https://api.spotify.com/v1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_fernet() -> Fernet:
    """Derive a Fernet key from the application SECRET_KEY."""
    settings = get_settings()
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _encrypt_token(plain: str) -> str:
    """Encrypt a token value for storage in the Settings table."""
    if not plain:
        return ""
    return _get_fernet().encrypt(plain.encode()).decode()


def _decrypt_token(encrypted: str) -> str:
    """Decrypt a token value retrieved from the Settings table."""
    if not encrypted:
        return ""
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except Exception:
        logger.warning("Failed to decrypt token; returning empty string.")
        return ""


async def _get_setting(db: AsyncSession, key: str, default: str = "") -> str:
    """Read a setting value from the DB."""
    stmt = select(Setting.value).where(Setting.key == key)
    result = await db.execute(stmt)
    value = result.scalar()
    return value if value is not None else default


async def _set_setting(
    db: AsyncSession, key: str, value: str, category: str = "api_keys"
) -> None:
    """Upsert a setting value in the DB."""
    stmt = select(Setting).where(Setting.key == key)
    result = await db.execute(stmt)
    setting = result.scalar()
    if setting:
        setting.value = value
    else:
        db.add(Setting(key=key, value=value, description="", category=category))
    await db.flush()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SpotifyTrack:
    """Normalised representation of a Spotify playlist track."""

    track_name: str
    artist_name: str
    album_name: str
    spotify_uri: str


@dataclass
class SpotifySyncResult:
    """Summary of a playlist sync operation."""

    playlists_synced: int = 0
    tracks_added: int = 0
    seasonal: int = 0
    discover: int = 0
    other: int = 0


# ---------------------------------------------------------------------------
# SpotifyService
# ---------------------------------------------------------------------------


class SpotifyService:
    """Async Spotify API client using httpx.

    Handles PKCE OAuth, token refresh, playlist enumeration, and track
    fetching.  Token values are persisted (encrypted) in the Settings table
    via the db session passed to auth-aware methods.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = "",
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None
        self._client: httpx.AsyncClient | None = None
        # Client credentials token (for search — no user auth)
        self._cc_token: str | None = None
        self._cc_expiry: datetime | None = None

    # ------------------------------------------------------------------
    # HttpClient management
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Return (and cache) an httpx AsyncClient."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _api_headers(self) -> dict[str, str]:
        """Return Authorization header with current access token."""
        if not self._access_token:
            raise ValueError("No access token available. Authenticate first.")
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # PKCE helpers (static — no API calls)
    # ------------------------------------------------------------------

    @staticmethod
    def generate_pkce() -> tuple[str, str]:
        """Generate a PKCE code verifier and challenge (S256).

        Returns:
            (code_verifier, code_challenge)
        """
        verifier = secrets.token_urlsafe(64)[:128]
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return verifier, challenge

    @staticmethod
    def get_auth_url(
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        state: str,
    ) -> str:
        """Build the Spotify authorization URL for PKCE flow.

        Scopes requested: playlist-read-private, playlist-read-collaborative.
        """
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
            "state": state,
            "scope": "playlist-read-private playlist-read-collaborative",
        }
        return f"{SPOTIFY_ACCOUNTS_URL}/authorize?{urllib.parse.urlencode(params)}"

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def exchange_code(self, code: str, code_verifier: str) -> dict:
        """Exchange an authorization code for access + refresh tokens.

        Returns the JSON response from Spotify's /api/token endpoint.
        """
        client = await self._get_client()
        resp = await client.post(
            f"{SPOTIFY_ACCOUNTS_URL}/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            error_detail = ""
            try:
                error_detail = resp.json().get("error_description", resp.text[:300])
            except Exception:
                error_detail = resp.text[:300]
            raise ValueError(
                f"Token exchange failed (HTTP {resp.status_code}): {error_detail}"
            )

        data = resp.json()
        self._access_token = data.get("access_token", "")
        expires_in = data.get("expires_in", 3600)
        self._token_expiry = datetime.fromtimestamp(
            datetime.now(tz=timezone.utc).timestamp() + expires_in,
            tz=timezone.utc,
        )
        return data

    async def refresh_access_token(self, refresh_token: str) -> dict:
        """Refresh an expired access token using the refresh token.

        Returns the JSON response from Spotify's /api/token endpoint.
        """
        client = await self._get_client()
        resp = await client.post(
            f"{SPOTIFY_ACCOUNTS_URL}/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            error_detail = ""
            try:
                error_detail = resp.json().get("error_description", resp.text[:300])
            except Exception:
                error_detail = resp.text[:300]
            raise ValueError(
                f"Token refresh failed (HTTP {resp.status_code}): {error_detail}"
            )

        data = resp.json()
        self._access_token = data.get("access_token", "")
        expires_in = data.get("expires_in", 3600)
        self._token_expiry = datetime.fromtimestamp(
            datetime.now(tz=timezone.utc).timestamp() + expires_in,
            tz=timezone.utc,
        )

        # Some refresh responses include a new refresh_token; use it if provided.
        new_refresh = data.get("refresh_token", "")
        if new_refresh:
            data["_new_refresh_token"] = new_refresh

        return data

    async def _ensure_token(self, db: AsyncSession) -> None:
        """Ensure a valid access token is available, refreshing if needed.

        Loads the encrypted refresh token from the Settings table.  If the
        current access token is missing or expired, refreshes and persists
        the new values.
        """
        # Already have a valid token?
        now_ts = datetime.now(tz=timezone.utc).timestamp()
        if (
            self._access_token
            and self._token_expiry
            and now_ts < (self._token_expiry.timestamp() - 60)
        ):
            return

        # Load encrypted refresh token from DB
        encrypted_refresh = await _get_setting(db, "spotify_refresh_token", "")
        refresh_token = _decrypt_token(encrypted_refresh)
        if not refresh_token:
            # Try loading existing access token (may still be valid)
            encrypted_access = await _get_setting(
                db, "spotify_access_token_encrypted", ""
            )
            if encrypted_access:
                self._access_token = _decrypt_token(encrypted_access)
                expiry_str = await _get_setting(db, "spotify_token_expiry", "")
                if expiry_str:
                    try:
                        self._token_expiry = datetime.fromisoformat(expiry_str)
                    except ValueError:
                        self._token_expiry = None
                if (
                    self._access_token
                    and self._token_expiry
                    and now_ts < (self._token_expiry.timestamp() - 60)
                ):
                    return
            raise ValueError(
                "No refresh token available. User must authenticate via OAuth."
            )

        # Refresh the token
        logger.info("Refreshing Spotify access token...")
        data = await self.refresh_access_token(refresh_token)

        # Persist updated tokens
        await _set_setting(
            db,
            "spotify_access_token_encrypted",
            _encrypt_token(data.get("access_token", "")),
        )
        new_refresh = data.get("_new_refresh_token") or refresh_token
        await _set_setting(
            db,
            "spotify_refresh_token",
            _encrypt_token(new_refresh),
        )
        expiry_iso = (
            self._token_expiry.isoformat()
            if self._token_expiry
            else datetime.fromtimestamp(
                now_ts + 3600, tz=timezone.utc
            ).isoformat()
        )
        await _set_setting(db, "spotify_token_expiry", expiry_iso)

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    async def _get_rate_limit_delay(self, db: AsyncSession) -> float:
        """Return the minimum delay (seconds) between API calls."""
        rpm_str = await _get_setting(db, "spotify_rate_limit_rpm", "150")
        try:
            rpm = float(rpm_str)
        except ValueError:
            rpm = 150.0
        if rpm <= 0:
            return 0.0
        return 60.0 / rpm

    async def get_user_playlists(self, db: AsyncSession) -> list[dict]:
        """GET /me/playlists — fetch all user playlists with pagination.

        Requires user authentication (PKCE OAuth).
        """
        await self._ensure_token(db)
        client = await self._get_client()
        headers = await self._api_headers()
        delay = await self._get_rate_limit_delay(db)

        playlists: list[dict] = []
        url: str | None = f"{SPOTIFY_API_URL}/me/playlists?limit=50"

        while url:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                logger.warning(
                    "Spotify rate limited; waiting %d seconds.", retry_after
                )
                await asyncio.sleep(retry_after)
                continue
            if resp.status_code != 200:
                logger.error(
                    "Failed to fetch playlists: HTTP %d — %s",
                    resp.status_code,
                    resp.text[:300],
                )
                break

            data = resp.json()
            playlists.extend(data.get("items", []))
            url = data.get("next")

            if url and delay > 0:
                await asyncio.sleep(delay)

        return playlists

    async def get_playlist_tracks(
        self, db: AsyncSession, playlist_id: str
    ) -> list[SpotifyTrack]:
        """GET /playlists/{id}/tracks — fetch all tracks with pagination.

        Returns a list of normalised SpotifyTrack objects.
        """
        await self._ensure_token(db)
        client = await self._get_client()
        headers = await self._api_headers()
        delay = await self._get_rate_limit_delay(db)

        tracks: list[SpotifyTrack] = []
        url: str | None = (
            f"{SPOTIFY_API_URL}/playlists/{playlist_id}/tracks"
            "?limit=100&fields=next,items(track(uri,name,album(name),artists(name)))"
        )

        while url:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                logger.warning(
                    "Spotify rate limited; waiting %d seconds.", retry_after
                )
                await asyncio.sleep(retry_after)
                continue
            if resp.status_code != 200:
                logger.error(
                    "Failed to fetch tracks for playlist %s: HTTP %d — %s",
                    playlist_id,
                    resp.status_code,
                    resp.text[:300],
                )
                break

            data = resp.json()
            for item in data.get("items", []):
                track = item.get("track")
                if not track or not track.get("uri"):
                    continue  # skip null tracks (e.g. unavailable in region)

                artists = track.get("artists", [])
                artist_name = artists[0]["name"] if artists else "Unknown Artist"
                album = track.get("album") or {}
                album_name = album.get("name", "")

                tracks.append(
                    SpotifyTrack(
                        track_name=track.get("name", "Unknown Track"),
                        artist_name=artist_name,
                        album_name=album_name,
                        spotify_uri=track["uri"],
                    )
                )

            url = data.get("next")
            if url and delay > 0:
                await asyncio.sleep(delay)

        return tracks

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    async def sync_playlists(self, db: AsyncSession) -> SpotifySyncResult:
        """Full playlist sync: fetch, classify, upsert playlists and tracks.

        Classification rules:
        - Name matches ``spotify_seasonal_playlist_pattern`` regex → SEASONAL
        - Name is in ``spotify_discover_playlist_names`` JSON list → DISCOVER
        - Everything else → OTHER

        This method is idempotent — re-running clears old tracks for each
        playlist and re-fetches.
        """
        result = SpotifySyncResult()

        # 1. Read classification settings
        seasonal_pattern = await _get_setting(
            db, "spotify_seasonal_playlist_pattern", "Winter|Summer|Fall"
        )
        discover_names_raw = await _get_setting(
            db,
            "spotify_discover_playlist_names",
            '["Release Radar", "Pitchfork Selects"]',
        )
        try:
            discover_names: list[str] = json.loads(discover_names_raw)
        except (json.JSONDecodeError, TypeError):
            discover_names = ["Release Radar", "Pitchfork Selects"]

        # Compile the seasonal regex once (case-insensitive)
        try:
            seasonal_re = re.compile(seasonal_pattern, re.IGNORECASE)
        except re.error:
            logger.warning(
                "Invalid seasonal pattern '%s'; using default.", seasonal_pattern
            )
            seasonal_re = re.compile(r"Winter|Summer|Fall", re.IGNORECASE)

        # 2. Fetch all user playlists
        try:
            playlists = await self.get_user_playlists(db)
        except Exception:
            logger.exception("Failed to fetch Spotify playlists.")
            return result

        result.playlists_synced = len(playlists)

        # 3. Process each playlist
        for sp_playlist in playlists:
            spotify_id = sp_playlist.get("id", "")
            name = sp_playlist.get("name", "")
            if not spotify_id:
                continue

            # Classify
            ptype = PlaylistType.OTHER
            if seasonal_re.search(name):
                ptype = PlaylistType.SEASONAL
            elif name in discover_names:
                ptype = PlaylistType.DISCOVER

            # Count
            if ptype == PlaylistType.SEASONAL:
                result.seasonal += 1
            elif ptype == PlaylistType.DISCOVER:
                result.discover += 1
            else:
                result.other += 1

            # Upsert playlist row
            stmt = select(Playlist).where(Playlist.spotify_id == spotify_id)
            rows = await db.execute(stmt)
            existing = rows.scalar()
            if existing:
                existing.name = name
                existing.playlist_type = ptype
                existing.last_synced_at = datetime.now(tz=timezone.utc)
                playlist_obj = existing
            else:
                playlist_obj = Playlist(
                    spotify_id=spotify_id,
                    name=name,
                    playlist_type=ptype,
                    is_active=True,
                    last_synced_at=datetime.now(tz=timezone.utc),
                )
                db.add(playlist_obj)

            await db.flush()  # ensure playlist_obj.id is populated

            # Fetch tracks
            try:
                tracks = await self.get_playlist_tracks(db, spotify_id)
            except Exception:
                logger.exception(
                    "Failed to fetch tracks for playlist '%s'.", name
                )
                continue

            # Clear old tracks and insert new ones
            await db.execute(
                delete(PlaylistTrack).where(
                    PlaylistTrack.playlist_id == playlist_obj.id
                )
            )

            # Deduplicate by spotify_uri within this playlist
            seen_uris: set[str] = set()
            for track in tracks:
                if not track.spotify_uri or track.spotify_uri in seen_uris:
                    continue
                seen_uris.add(track.spotify_uri)
                db.add(
                    PlaylistTrack(
                        playlist_id=playlist_obj.id,
                        track_name=track.track_name,
                        artist_name=track.artist_name,
                        album_name=track.album_name,
                        spotify_uri=track.spotify_uri,
                    )
                )
                result.tracks_added += 1

        await db.commit()
        logger.info(
            "Spotify sync complete: %d playlists, %d tracks, "
            "seasonal=%d discover=%d other=%d",
            result.playlists_synced,
            result.tracks_added,
            result.seasonal,
            result.discover,
            result.other,
        )
        return result

    # ------------------------------------------------------------------
    # Client credentials (no user auth — for search)
    # ------------------------------------------------------------------

    async def _ensure_client_credentials_token(self) -> None:
        """Obtain an access token via the client-credentials OAuth flow.

        Does not require user authentication — suitable for public endpoints
        such as search.  The token is cached until it expires.
        """
        now_ts = datetime.now(tz=timezone.utc).timestamp()
        if (
            self._cc_token
            and self._cc_expiry
            and now_ts < (self._cc_expiry.timestamp() - 60)
        ):
            return

        if not self.client_id or not self.client_secret:
            raise ValueError(
                "Spotify client_id and client_secret must be configured for search."
            )

        client = await self._get_client()
        auth_str = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        resp = await client.post(
            f"{SPOTIFY_ACCOUNTS_URL}/api/token",
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {auth_str}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if resp.status_code != 200:
            error_detail = ""
            try:
                error_detail = resp.json().get("error_description", resp.text[:300])
            except Exception:
                error_detail = resp.text[:300]
            raise ValueError(
                f"Spotify client credentials failed (HTTP {resp.status_code}): {error_detail}"
            )

        data = resp.json()
        self._cc_token = data.get("access_token", "")
        expires_in = data.get("expires_in", 3600)
        self._cc_expiry = datetime.fromtimestamp(
            now_ts + expires_in, tz=timezone.utc
        )

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    async def search(self, query: str, search_type: str = "album") -> list[dict]:
        """Search Spotify for albums, artists, or both via client credentials.

        Args:
            query: Search query string.
            search_type: ``"album"``, ``"artist"``, or ``"album,artist"``.

        Returns:
            List of normalised dicts with keys: spotify_id, title/name,
            artist_name (album only), year, type.
        """
        await self._ensure_client_credentials_token()
        client = await self._get_client()

        resp = await client.get(
            f"{SPOTIFY_API_URL}/search",
            params={"q": query, "type": search_type, "limit": 10},
            headers={"Authorization": f"Bearer {self._cc_token}"},
        )
        if resp.status_code != 200:
            logger.error(
                "Spotify search failed (HTTP %d): %s",
                resp.status_code,
                resp.text[:300],
            )
            return []

        data = resp.json()
        results: list[dict] = []

        albums_data = (data.get("albums") or {}).get("items", [])
        for item in albums_data:
            artists = item.get("artists", [])
            artist_name = artists[0]["name"] if artists else ""
            release_date = item.get("release_date", "")
            year: int | None = None
            if release_date and len(release_date) >= 4:
                try:
                    year = int(release_date[:4])
                except (ValueError, TypeError):
                    pass
            results.append({
                "spotify_id": item.get("id", ""),
                "title": item.get("name", ""),
                "artist_name": artist_name,
                "year": year,
                "type": "album",
            })

        artists_data = (data.get("artists") or {}).get("items", [])
        for item in artists_data:
            results.append({
                "spotify_id": item.get("id", ""),
                "name": item.get("name", ""),
                "type": "artist",
            })

        return results
