"""Celery download task — wraps the DownloadPipeline for async execution.

Celery tasks are synchronous, so we use asyncio.run() to call the async
pipeline from within the task.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from functools import lru_cache

from app.celery_app import celery_app
from app.config import get_settings
from app.constants import DEFAULT_SETTINGS
from app.database import async_session_factory
from app.services.beets import BeetsService
from app.services.notifications import NotificationService
from app.services.pipeline import DownloadPipeline
from app.services.qobuz import QobuzService
from app.services.spotify import _decrypt_token

logger = logging.getLogger(__name__)


async def _read_db_settings() -> dict[str, str]:
    """Read settings from the database, returning a key→value dict."""
    from sqlalchemy import select
    from app.models.setting import Setting

    result: dict[str, str] = {}
    async with async_session_factory() as db:
        stmt = select(Setting)
        rows = await db.execute(stmt)
        for setting in rows.scalars().all():
            result[setting.key] = setting.value
    return result


async def _build_pipeline_async() -> DownloadPipeline:
    """Async version of _build_pipeline — use when already in an event loop."""
    settings = get_settings()
    db_settings = await _read_db_settings()
    merged = dict(DEFAULT_SETTINGS)
    merged.update(db_settings)

    qobuz_email = settings.QOBUZ_EMAIL or merged.get("qobuz_email", "")
    db_password = merged.get("qobuz_password_encrypted", "")
    if db_password:
        qobuz_password = _decrypt_token(db_password) or db_password
    else:
        qobuz_password = settings.QOBUZ_PASSWORD or ""
    qobuz_rate_limit = float(merged.get("qobuz_rate_limit_rps", "2.0"))

    beets_config = merged.get("beets_config_path", "/config/beets/config.yaml")
    discord_url = settings.DISCORD_WEBHOOK_URL or merged.get("discord_webhook_url", "")

    qobuz = QobuzService(
        email=qobuz_email,
        password=qobuz_password,
        rate_limit_rps=qobuz_rate_limit,
    )
    beets = BeetsService(config_path=beets_config)
    notifier = NotificationService(webhook_url=discord_url or None)

    return DownloadPipeline(
        db_session_factory=async_session_factory,
        qobuz=qobuz,
        beets=beets,
        notifier=notifier,
        settings=merged,
    )


def _build_pipeline() -> DownloadPipeline:
    """Build a DownloadPipeline from current configuration.

    Reads Qobuz credentials from DB settings first, then env vars as fallback.
    This is called inside the Celery task (worker process).
    """
    settings = get_settings()

    # Read DB settings (contains credentials saved via the UI)
    db_settings = asyncio.run(_read_db_settings())

    # Merge: DB settings take priority over DEFAULT_SETTINGS
    merged = dict(DEFAULT_SETTINGS)
    merged.update(db_settings)

    qobuz_email = settings.QOBUZ_EMAIL or merged.get("qobuz_email", "")
    db_password = merged.get("qobuz_password_encrypted", "")
    if db_password:
        qobuz_password = _decrypt_token(db_password) or db_password
    else:
        qobuz_password = settings.QOBUZ_PASSWORD or ""
    qobuz_rate_limit = float(merged.get("qobuz_rate_limit_rps", "2.0"))

    beets_config = merged.get("beets_config_path", "/config/beets/config.yaml")
    discord_url = settings.DISCORD_WEBHOOK_URL or merged.get("discord_webhook_url", "")

    qobuz = QobuzService(
        email=qobuz_email,
        password=qobuz_password,
        rate_limit_rps=qobuz_rate_limit,
    )
    beets = BeetsService(config_path=beets_config)
    notifier = NotificationService(webhook_url=discord_url or None)

    return DownloadPipeline(
        db_session_factory=async_session_factory,
        qobuz=qobuz,
        beets=beets,
        notifier=notifier,
        settings=merged,
    )


def _run_async(coro):
    """Run an async coroutine from a synchronous Celery task."""
    return asyncio.run(coro)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minutes between Celery-level retries
    name="musically.download_album",
)
def download_album_task(self, album_id: str) -> dict:
    """Celery task: download and import an album.

    Args:
        album_id: The UUID of the Album record to process, as a string.

    Returns:
        A dict with status, album_id, and message.

    The task has 3 retries at the Celery level (separate from the stalled
    retry mechanism in the pipeline). If the pipeline itself fails, the
    album will be marked as stalled and retried later by process_stalled_albums.
    """
    try:
        album_uuid = uuid.UUID(album_id)
    except ValueError:
        return {"status": "error", "album_id": album_id, "message": "Invalid UUID"}

    pipeline = _build_pipeline()

    try:
        result = _run_async(pipeline.process_album(album_uuid))

        # Close resources
        _run_async(pipeline.qobuz.close())
        _run_async(pipeline.notifier.close())

        if not result.success:
            logger.warning(
                "Download pipeline failed for album %s: %s",
                album_id, result.message,
            )
            # Let Celery retry for transient errors
            if result.status == "stalled":
                # Stalled is not a transient error — don't retry at Celery level
                return {
                    "status": "stalled",
                    "album_id": album_id,
                    "message": result.message,
                    "errors": result.errors,
                }
            # For other failures, retry
            raise self.retry(exc=Exception(result.message))

        return {
            "status": "downloaded",
            "album_id": album_id,
            "message": result.message,
            "files_downloaded": result.files_downloaded,
            "files_imported": result.files_imported,
        }

    except self.MaxRetriesExceededError:
        logger.error("Max Celery retries exceeded for album %s", album_id)
        return {
            "status": "error",
            "album_id": album_id,
            "message": "Max retries exceeded",
        }
    except Exception as exc:
        logger.exception("Celery task failed for album %s", album_id)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {
                "status": "error",
                "album_id": album_id,
                "message": str(exc),
            }
    finally:
        # Ensure cleanup even on retry
        try:
            _run_async(pipeline.qobuz.close())
            _run_async(pipeline.notifier.close())
        except Exception:
            pass


# Legacy alias for backward compatibility
download_album = download_album_task


# ---------------------------------------------------------------------------
# Watch folder pipeline builder (no Qobuz needed)
# ---------------------------------------------------------------------------


def _build_watch_folder_pipeline() -> DownloadPipeline:
    """Build a DownloadPipeline for watch folder processing (no Qobuz).

    Watch folder albums already have FLAC files — we only need beets
    for tagging / import and the notifier for Discord updates.
    """
    settings = get_settings()
    db_defaults = dict(DEFAULT_SETTINGS)

    beets_config = db_defaults.get(
        "beets_config_path", "/config/beets/config.yaml"
    )
    discord_url = settings.DISCORD_WEBHOOK_URL or db_defaults.get(
        "discord_webhook_url", ""
    )

    beets = BeetsService(config_path=beets_config)
    notifier = NotificationService(webhook_url=discord_url or None)

    return DownloadPipeline(
        db_session_factory=async_session_factory,
        qobuz=None,  # No Qobuz needed for watch folder
        beets=beets,
        notifier=notifier,
        settings=db_defaults,
    )


@celery_app.task(
    bind=True,
    max_retries=2,
    default_retry_delay=120,  # 2 minutes between Celery-level retries
    name="musically.process_watch_folder_album",
)
def process_watch_folder_album_task(
    self, album_id: str, source_path: str = ""
) -> dict:
    """Celery task: process a watch folder album (beets import only, no Qobuz).

    This is the simplified pipeline for albums that already have FLAC files.
    It runs beets import directly — no Qobuz search or download needed.

    Args:
        album_id: UUID of the Album record as a string.
        source_path: Absolute path to the source directory containing FLAC
            files.  Passed from the watch folder service.

    Returns:
        A dict with status, album_id, and message.
    """
    try:
        album_uuid = uuid.UUID(album_id)
    except ValueError:
        return {"status": "error", "album_id": album_id, "message": "Invalid UUID"}

    pipeline = _build_watch_folder_pipeline()

    try:
        result = _run_async(
            pipeline.process_watch_folder_album(album_uuid, source_path)
        )

        # Close resources
        _run_async(pipeline.notifier.close())

        if not result.success:
            logger.warning(
                "Watch folder pipeline failed for album %s: %s",
                album_id,
                result.message,
            )
            if result.status == "stalled":
                # Stalled is not a transient error — don't retry at Celery level
                return {
                    "status": "stalled",
                    "album_id": album_id,
                    "message": result.message,
                    "errors": result.errors,
                }
            # For other failures, retry
            raise self.retry(exc=Exception(result.message))

        return {
            "status": "downloaded",
            "album_id": album_id,
            "message": result.message,
            "files_imported": result.files_imported,
        }

    except self.MaxRetriesExceededError:
        logger.error(
            "Max Celery retries exceeded for watch folder album %s", album_id
        )
        return {
            "status": "error",
            "album_id": album_id,
            "message": "Max retries exceeded",
        }
    except Exception as exc:
        logger.exception(
            "Celery task failed for watch folder album %s", album_id
        )
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {
                "status": "error",
                "album_id": album_id,
                "message": str(exc),
            }
    finally:
        # Ensure cleanup even on retry
        try:
            _run_async(pipeline.notifier.close())
        except Exception:
            pass

