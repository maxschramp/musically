"""Qobuz router — test connection and download flow."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.setting import Setting
from app.services.qobuz import QobuzService
from app.services.spotify import _decrypt_token

router = APIRouter()


@router.post("/qobuz/test")
async def test_qobuz_connection(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Test the full Qobuz connection: scrape → login → search → download.

    Reads Qobuz email and password from the settings table.
    Downloads a single track to a temp directory to verify the download pipeline,
    then cleans up. Returns success/failure with detailed step-by-step status.
    """
    # Read credentials from settings
    email_result = await db.execute(
        select(Setting).where(Setting.key == "qobuz_email")
    )
    email_setting = email_result.scalar_one_or_none()
    email = email_setting.value if email_setting and email_setting.value else ""

    password_result = await db.execute(
        select(Setting).where(Setting.key == "qobuz_password_encrypted")
    )
    password_setting = password_result.scalar_one_or_none()
    raw_password = password_setting.value if password_setting and password_setting.value else ""
    # Decrypt if stored encrypted (Fernet tokens start with 'gAAAAAB')
    if raw_password.startswith("gAAAAAB"):
        password = _decrypt_token(raw_password) or raw_password
    else:
        password = raw_password

    if not email or not password:
        return {
            "success": False,
            "step": "credentials",
            "message": "Qobuz email and password are not configured.",
        }

    svc = QobuzService(email=email, password=password)
    steps: list[dict] = []

    try:
        # Step 1: Scrape credentials
        await svc._ensure_credentials()
        if not svc.app_id or not svc.app_secret:
            return {
                "success": False,
                "step": "scrape",
                "message": "Failed to scrape app credentials from open.qobuz.com.",
                "steps": steps,
            }
        steps.append({"step": "scrape", "status": "ok", "detail": f"app_id={svc.app_id}"})

        # Step 2: Login
        try:
            await svc._ensure_authenticated()
            steps.append({"step": "login", "status": "ok", "detail": "Authenticated"})
        except Exception as e:
            steps.append({"step": "login", "status": "fail", "detail": str(e)})
            return {
                "success": False,
                "step": "login",
                "message": f"Login failed: {e}",
                "app_id": svc.app_id,
                "steps": steps,
            }

        # Step 3: Search
        qobuz_album = None
        try:
            qobuz_album = await svc.search_album_with_tracks("Radiohead", "OK Computer")
            if qobuz_album and qobuz_album.qobuz_id:
                steps.append({
                    "step": "search",
                    "status": "ok",
                    "detail": f"Found: {qobuz_album.title} ({qobuz_album.track_count} tracks)",
                })
            else:
                steps.append({"step": "search", "status": "warn", "detail": "No results for test query"})
                return {
                    "success": True,
                    "step": "search",
                    "message": "Login verified. Search returned no results for test query (album may not be available in your region).",
                    "app_id": svc.app_id,
                    "steps": steps,
                }
        except Exception as e:
            steps.append({"step": "search", "status": "fail", "detail": str(e)})
            return {
                "success": True,
                "step": "login_only",
                "message": f"Login successful, but search failed: {e}",
                "app_id": svc.app_id,
                "steps": steps,
            }

        # Step 4: Download a single track to verify the full download pipeline
        if qobuz_album and qobuz_album.tracks:
            first_track = qobuz_album.tracks[0]
            with tempfile.TemporaryDirectory() as tmpdir:
                dest = Path(tmpdir) / "test.flac"
                try:
                    await svc.download_track(first_track.track_id, dest)
                    file_size = dest.stat().st_size if dest.exists() else 0
                    steps.append({
                        "step": "download",
                        "status": "ok",
                        "detail": f"Downloaded '{first_track.title}' ({file_size / 1_048_576:.1f} MiB)",
                    })
                except Exception as e:
                    steps.append({
                        "step": "download",
                        "status": "fail",
                        "detail": f"Track download failed: {e}",
                    })
                    return {
                        "success": False,
                        "step": "download",
                        "message": f"Search and login successful, but download failed: {e}",
                        "app_id": svc.app_id,
                        "steps": steps,
                    }

        return {
            "success": True,
            "step": "download",
            "message": "Full Qobuz connection verified: scrape → login → search → download!",
            "app_id": svc.app_id,
            "test_search": f"Found: {qobuz_album.title} by {qobuz_album.artist_name} ({qobuz_album.track_count} tracks)",
            "steps": steps,
        }

    except Exception as e:
        steps.append({"step": "error", "status": "fail", "detail": str(e)})
        return {
            "success": False,
            "step": "error",
            "message": f"Connection test failed: {e}",
            "steps": steps,
        }
    finally:
        await svc.close()
