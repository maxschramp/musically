"""Spotify router — test connection, OAuth PKCE flow, and playlist sync."""

from __future__ import annotations

import base64
import secrets
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.setting import Setting
from app.services.spotify import (
    SpotifyService,
    SpotifySyncResult,
    _decrypt_token,
    _encrypt_token,
    _get_setting,
    _set_setting,
)

router = APIRouter()

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_URL = "https://api.spotify.com/v1"


# ---------------------------------------------------------------------------
# GET /spotify/status — Connection health check
# ---------------------------------------------------------------------------
@router.get("/spotify/status")
async def spotify_status(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return Spotify connection state: configured, authorized, last sync.

    Does NOT make any external API calls — reads from the local DB only.
    Use POST /spotify/test to verify live credentials.
    """
    from sqlalchemy import func
    from app.models.playlist import Playlist

    # Read all relevant settings
    keys = [
        "spotify_client_id", "spotify_client_secret",
        "spotify_refresh_token", "spotify_access_token_encrypted",
        "spotify_token_expiry", "spotify_enabled",
    ]
    stmt = select(Setting).where(Setting.key.in_(keys))
    rows = await db.execute(stmt)
    settings_map: dict[str, str] = {s.key: s.value for s in rows.scalars().all()}

    has_credentials = bool(
        settings_map.get("spotify_client_id", "")
        and settings_map.get("spotify_client_secret", "")
    )
    enabled = settings_map.get("spotify_enabled", "true").lower() == "true"

    has_refresh = bool(settings_map.get("spotify_refresh_token", ""))
    has_access = bool(settings_map.get("spotify_access_token_encrypted", ""))

    token_expiry: str | None = None
    token_expired: bool = False
    expiry_str = settings_map.get("spotify_token_expiry", "")
    if expiry_str:
        token_expiry = expiry_str
        try:
            exp = datetime.fromisoformat(expiry_str)
            token_expired = datetime.now(timezone.utc) > exp
        except (ValueError, TypeError):
            pass

    # Last sync time = most recent playlist last_synced_at
    last_synced_stmt = select(func.max(Playlist.last_synced_at))
    last_synced_result = await db.execute(last_synced_stmt)
    last_synced = last_synced_result.scalar()

    # Playlist counts
    total_stmt = select(func.count(Playlist.id))
    total_count = (await db.execute(total_stmt)).scalar() or 0

    active_stmt = select(func.count(Playlist.id)).where(Playlist.is_active == True)
    active_count = (await db.execute(active_stmt)).scalar() or 0

    return {
        "configured": has_credentials,
        "enabled": enabled,
        "authorized": has_refresh and has_access,
        "token_expired": token_expired,
        "token_expiry": token_expiry if token_expiry else None,
        "last_synced_at": last_synced.isoformat() if last_synced else None,
        "total_playlists": total_count,
        "active_playlists": active_count,
    }


@router.post("/spotify/test")
async def test_spotify_connection(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test Spotify API credentials by obtaining a client-credentials token.

    Reads Spotify client_id and client_secret from the settings table.
    Uses the Client Credentials flow (no user OAuth needed for basic test).
    Returns success/failure with detailed step-by-step status.
    """
    # Read credentials from settings
    client_id_result = await db.execute(
        select(Setting).where(Setting.key == "spotify_client_id")
    )
    client_id_setting = client_id_result.scalar_one_or_none()
    client_id = client_id_setting.value if client_id_setting and client_id_setting.value else ""

    secret_result = await db.execute(
        select(Setting).where(Setting.key == "spotify_client_secret")
    )
    secret_setting = secret_result.scalar_one_or_none()
    client_secret = secret_setting.value if secret_setting and secret_setting.value else ""

    if not client_id or not client_secret:
        return {
            "success": False,
            "step": "credentials",
            "message": "Spotify Client ID and Client Secret are not configured.",
            "steps": [{"step": "credentials", "status": "fail", "detail": "Missing credentials"}],
        }

    steps: list[dict] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Step 1: Get access token via Client Credentials flow
        auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        try:
            token_resp = await client.post(
                SPOTIFY_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            if token_resp.status_code != 200:
                error_detail = ""
                try:
                    error_detail = token_resp.json().get("error_description", "")
                except Exception:
                    pass
                steps.append({
                    "step": "auth",
                    "status": "fail",
                    "detail": f"HTTP {token_resp.status_code}: {error_detail or token_resp.text[:200]}",
                })
                return {
                    "success": False,
                    "step": "auth",
                    "message": f"Spotify authentication failed: {error_detail or 'Invalid credentials'}",
                    "steps": steps,
                }

            token_data = token_resp.json()
            access_token = token_data.get("access_token", "")
            steps.append({
                "step": "auth",
                "status": "ok",
                "detail": "Client credentials token obtained",
            })

        except httpx.HTTPError as e:
            steps.append({"step": "auth", "status": "fail", "detail": str(e)})
            return {
                "success": False,
                "step": "auth",
                "message": f"Could not reach Spotify: {e}",
                "steps": steps,
            }

        # Step 2: Test API access with a simple search
        try:
            search_resp = await client.get(
                f"{SPOTIFY_API_URL}/search",
                params={"q": "Radiohead", "type": "artist", "limit": 1},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if search_resp.status_code == 200:
                data = search_resp.json()
                artists = data.get("artists", {}).get("items", [])
                if artists:
                    artist_name = artists[0].get("name", "unknown")
                    steps.append({
                        "step": "search",
                        "status": "ok",
                        "detail": f"Found artist: {artist_name}",
                    })
                else:
                    steps.append({"step": "search", "status": "warn", "detail": "No results"})
            else:
                steps.append({
                    "step": "search",
                    "status": "warn",
                    "detail": f"HTTP {search_resp.status_code} (search may require user auth)",
                })
        except Exception as e:
            steps.append({"step": "search", "status": "warn", "detail": str(e)})

        return {
            "success": True,
            "step": "done",
            "message": "Spotify connection verified! Client credentials flow successful.",
            "token_type": token_data.get("token_type", ""),
            "steps": steps,
        }


# ---------------------------------------------------------------------------
# OAuth PKCE endpoints
# ---------------------------------------------------------------------------


@router.get("/spotify/auth/login")
async def spotify_login(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Generate PKCE challenge and return the Spotify authorization URL.

    The user should be redirected to the returned ``auth_url``.  After
    authorizing, Spotify redirects back to ``/api/spotify/auth/callback``.

    The redirect URI is auto-detected from the incoming request's Host header
    when the configured value is still a localhost default.  This avoids the
    common "redirect_uri: Not matching configuration" error on LAN setups.
    """
    # Read client_id from settings
    client_id = await _get_setting(db, "spotify_client_id", "")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="Spotify Client ID is not configured. Set it in Settings first.",
        )

    # Build redirect_uri — auto-detect from request if still on localhost default
    redirect_uri = await _get_setting(
        db,
        "spotify_redirect_uri",
        "http://localhost:8000/api/spotify/auth/callback",
    )

    # If the configured redirect_uri still points to localhost, derive the
    # correct one from the incoming request.  For non-localhost addresses
    # we default to https:// since Spotify requires it.
    if "localhost" in redirect_uri or "127.0.0.1" in redirect_uri:
        scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme or "http")
        host = request.headers.get("X-Forwarded-Host", None)
        if not host:
            host = request.headers.get("Host", "localhost:8000")

        # Spotify requires HTTPS for non-localhost redirect URIs.
        # If the request came via HTTP but we're on a LAN server, force HTTPS
        # and use the HTTPS port (8443 by default) instead of the HTTP port.
        is_localhost = "localhost" in host or "127.0.0.1" in host
        if scheme == "http" and not is_localhost:
            scheme = "https"
            # Swap HTTP port for HTTPS port if using default mappings
            if ":808" in host or host.endswith(":80"):
                host = host.replace(":808", ":8443").replace(":80", ":443")

        redirect_uri = f"{scheme}://{host}/api/spotify/auth/callback"

    # Spotify requires HTTPS for all non-localhost redirect URIs.
    # If the resolved URI is still HTTP on a LAN/server address, reject early.
    if redirect_uri.startswith("http://") and "localhost" not in redirect_uri and "127.0.0.1" not in redirect_uri:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Spotify requires HTTPS for redirect URIs on non-localhost addresses. "
                f"The resolved redirect URI is: {redirect_uri}. "
                f"To fix this, either: (1) access Musically via HTTPS (https://YOUR_IP:8443) "
                f"and try again, or (2) manually set spotify_redirect_uri in Settings to an "
                f"https:// URL that points to this server."
            ),
        )

    # Store the resolved redirect_uri so the callback can use the same one
    await _set_setting(db, "spotify_pkce_redirect_uri", redirect_uri, "api_keys")

    # Generate PKCE
    code_verifier, code_challenge = SpotifyService.generate_pkce()
    state = secrets.token_urlsafe(32)

    # Store PKCE verifier and state temporarily (for callback verification)
    await _set_setting(db, "spotify_pkce_verifier", code_verifier, "api_keys")
    await _set_setting(db, "spotify_pkce_state", state, "api_keys")
    await db.commit()

    # Build authorization URL
    auth_url = SpotifyService.get_auth_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        state=state,
    )

    return {"auth_url": auth_url}


@router.get("/spotify/auth/callback")
async def spotify_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Handle the OAuth callback from Spotify.

    Verifies the state parameter, exchanges the authorization code for
    tokens, and stores them (encrypted) in the Settings table.
    """
    # 1. Verify state
    stored_state = await _get_setting(db, "spotify_pkce_state", "")
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="State mismatch. Possible CSRF attack.")

    # 2. Read stored PKCE verifier
    code_verifier = await _get_setting(db, "spotify_pkce_verifier", "")
    if not code_verifier:
        raise HTTPException(status_code=400, detail="PKCE verifier not found. Restart the auth flow.")

    # 3. Read client_id and client_secret
    client_id = await _get_setting(db, "spotify_client_id", "")
    client_secret = await _get_setting(db, "spotify_client_secret", "")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="Spotify Client ID/Secret not configured.",
        )

    redirect_uri = await _get_setting(
        db,
        "spotify_redirect_uri",
        "http://localhost:8000/api/spotify/auth/callback",
    )

    # 4. Exchange code for tokens
    spotify = SpotifyService(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    try:
        token_data = await spotify.exchange_code(code, code_verifier)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        await spotify.close()

    # 5. Store tokens (encrypted) in settings
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)
    expiry = datetime.fromtimestamp(
        datetime.now(tz=timezone.utc).timestamp() + expires_in,
        tz=timezone.utc,
    )

    await _set_setting(
        db, "spotify_access_token_encrypted", _encrypt_token(access_token)
    )
    await _set_setting(
        db, "spotify_refresh_token", _encrypt_token(refresh_token)
    )
    await _set_setting(db, "spotify_token_expiry", expiry.isoformat())

    # Clear temporary PKCE values
    await _set_setting(db, "spotify_pkce_verifier", "")
    await _set_setting(db, "spotify_pkce_state", "")

    await db.commit()

    return {
        "connected": True,
        "message": "Spotify connected successfully! You can now sync playlists.",
    }


@router.get("/spotify/auth/status")
async def spotify_status(db: AsyncSession = Depends(get_db)) -> dict:
    """Return whether the user is connected to Spotify via OAuth."""
    encrypted_refresh = await _get_setting(db, "spotify_refresh_token", "")
    refresh_token = _decrypt_token(encrypted_refresh)
    return {"connected": bool(refresh_token)}


@router.post("/spotify/sync")
async def trigger_spotify_sync(db: AsyncSession = Depends(get_db)) -> dict:
    """Manually trigger a Spotify playlist sync.

    Fetches all user playlists, classifies them (seasonal / discover / other),
    and stores their tracks in the database.
    """
    client_id = await _get_setting(db, "spotify_client_id", "")
    client_secret = await _get_setting(db, "spotify_client_secret", "")

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="Spotify Client ID and Client Secret are not configured.",
        )

    # Check if user has connected via OAuth
    encrypted_refresh = await _get_setting(db, "spotify_refresh_token", "")
    refresh_token = _decrypt_token(encrypted_refresh)
    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail="Spotify not connected. Please authenticate via /api/spotify/auth/login first.",
        )

    redirect_uri = await _get_setting(
        db,
        "spotify_redirect_uri",
        "http://localhost:8000/api/spotify/auth/callback",
    )

    spotify = SpotifyService(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    try:
        # Pre-load access token from DB so _ensure_token can attempt refresh
        encrypted_access = await _get_setting(
            db, "spotify_access_token_encrypted", ""
        )
        if encrypted_access:
            spotify._access_token = _decrypt_token(encrypted_access)
        expiry_str = await _get_setting(db, "spotify_token_expiry", "")
        if expiry_str:
            try:
                spotify._token_expiry = datetime.fromisoformat(expiry_str)
            except ValueError:
                pass

        result: SpotifySyncResult = await spotify.sync_playlists(db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        await spotify.close()

    return {
        "success": True,
        "playlists_synced": result.playlists_synced,
        "tracks_added": result.tracks_added,
        "seasonal": result.seasonal,
        "discover": result.discover,
        "other": result.other,
    }


# ---------------------------------------------------------------------------
# POST /spotify/auth/disconnect — Clear OAuth tokens
# ---------------------------------------------------------------------------
@router.post("/spotify/auth/disconnect")
async def spotify_disconnect(db: AsyncSession = Depends(get_db)) -> dict:
    """Clear all stored Spotify OAuth tokens.

    Does NOT revoke tokens at Spotify (the user should do that at
    https://www.spotify.com/account/apps/ if desired).  This simply
    removes the encrypted tokens from the local database so Musically
    stops accessing the user's Spotify account.
    """
    token_keys = [
        "spotify_access_token_encrypted",
        "spotify_refresh_token",
        "spotify_token_expiry",
        "spotify_pkce_verifier",
        "spotify_pkce_state",
        "spotify_pkce_redirect_uri",
    ]

    for key in token_keys:
        stmt = select(Setting).where(Setting.key == key)
        result = await db.execute(stmt)
        setting = result.scalar()
        if setting:
            setting.value = ""

    await db.commit()
    return {"success": True, "message": "Spotify tokens cleared."}
