"""LastFM router — test connection endpoint."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.setting import Setting

router = APIRouter()

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"


@router.post("/lastfm/test")
async def test_lastfm_connection(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test LastFM API credentials by fetching recent tracks.

    Reads LastFM API key and username from the settings table.
    Calls user.getRecentTracks with limit=1 to verify credentials.
    Returns success/failure with detailed step-by-step status.
    """
    # Read credentials from settings
    key_result = await db.execute(
        select(Setting).where(Setting.key == "lastfm_api_key")
    )
    key_setting = key_result.scalar_one_or_none()
    api_key = key_setting.value if key_setting and key_setting.value else ""

    user_result = await db.execute(
        select(Setting).where(Setting.key == "lastfm_username")
    )
    user_setting = user_result.scalar_one_or_none()
    username = user_setting.value if user_setting and user_setting.value else ""

    if not api_key:
        return {
            "success": False,
            "step": "credentials",
            "message": "LastFM API key is not configured.",
            "steps": [{"step": "credentials", "status": "fail", "detail": "Missing API key"}],
        }

    if not username:
        return {
            "success": False,
            "step": "credentials",
            "message": "LastFM username is not configured.",
            "steps": [{"step": "credentials", "status": "fail", "detail": "Missing username"}],
        }

    steps: list[dict] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                LASTFM_API_URL,
                params={
                    "method": "user.getRecentTracks",
                    "user": username,
                    "api_key": api_key,
                    "format": "json",
                    "limit": 1,
                },
            )

            if resp.status_code != 200:
                steps.append({
                    "step": "api_call",
                    "status": "fail",
                    "detail": f"HTTP {resp.status_code}",
                })
                return {
                    "success": False,
                    "step": "api_call",
                    "message": f"LastFM API returned HTTP {resp.status_code}",
                    "steps": steps,
                }

            data = resp.json()

            # Check for LastFM error
            if data.get("error"):
                error_msg = data.get("message", "Unknown error")
                steps.append({
                    "step": "api_call",
                    "status": "fail",
                    "detail": f"LastFM error: {error_msg}",
                })
                return {
                    "success": False,
                    "step": "api_call",
                    "message": f"LastFM error: {error_msg}",
                    "steps": steps,
                }

            recent = data.get("recenttracks", {})
            tracks = recent.get("track", [])
            total = recent.get("@attr", {}).get("total", "0")
            user_display = recent.get("@attr", {}).get("user", username)

            steps.append({
                "step": "api_call",
                "status": "ok",
                "detail": f"User: {user_display}, total scrobbles: {total}",
            })

            if tracks:
                first = tracks[0] if isinstance(tracks, list) else tracks
                track_name = first.get("name", "unknown")
                artist_name = first.get("artist", {}).get("#text", "unknown")
                now_playing = first.get("@attr", {}).get("nowplaying", "false") == "true"
                detail = f"{'Now playing' if now_playing else 'Last played'}: {artist_name} — {track_name}"
                steps.append({
                    "step": "recent_track",
                    "status": "ok",
                    "detail": detail,
                })

            return {
                "success": True,
                "step": "done",
                "message": "LastFM connection verified!",
                "username": user_display,
                "total_scrobbles": total,
                "steps": steps,
            }

        except httpx.HTTPError as e:
            steps.append({"step": "api_call", "status": "fail", "detail": str(e)})
            return {
                "success": False,
                "step": "api_call",
                "message": f"Could not reach LastFM: {e}",
                "steps": steps,
            }
