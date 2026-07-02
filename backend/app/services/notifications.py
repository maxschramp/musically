"""Notification service — Discord webhook integration for Musically events."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# Musically brand deep green
MUSICALLY_GREEN = 0x003C33
# Status colors
COLOR_SUCCESS = 0x00C853
COLOR_WARNING = 0xFFD600
COLOR_ERROR = 0xFF1744
COLOR_INFO = 0x2979FF


class NotificationService:
    """Service for sending rich Discord webhook notifications.

    If no webhook_url is provided, all send methods are no-ops and return False.
    """

    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url = webhook_url
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def send_discord(self, message: str, embed: dict | None = None) -> bool:
        """Send a Discord webhook message. Returns True on success, False if no URL or on failure."""
        if not self.webhook_url:
            logger.debug("No Discord webhook URL configured; skipping notification.")
            return False

        payload: dict = {"content": message}
        if embed:
            payload["embeds"] = [embed]

        try:
            client = await self._get_client()
            resp = await client.post(self.webhook_url, json=payload)
            if resp.status_code in (200, 204):
                logger.info("Discord notification sent: %s", message[:100])
                return True
            else:
                logger.warning(
                    "Discord webhook returned %d: %s",
                    resp.status_code,
                    resp.text[:300],
                )
                return False
        except httpx.HTTPError as e:
            logger.error("Discord webhook HTTP error: %s", e)
            return False
        except Exception:
            logger.exception("Unexpected error sending Discord notification")
            return False

    # ------------------------------------------------------------------
    # Specific notification types
    # ------------------------------------------------------------------

    async def notify_download(self, album_title: str, artist_name: str, reason: str = "") -> bool:
        """Send a rich notification when an album has been downloaded.

        Args:
            album_title: The album title.
            artist_name: The artist name.
            reason: Why this album was queued (e.g. "5+ plays", "new release").
        """
        embed = {
            "title": f"{artist_name} — {album_title}",
            "description": f"Downloaded from Qobuz{f' • {reason}' if reason else ''}",
            "color": MUSICALLY_GREEN,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Musically"},
        }
        return await self.send_discord("✅ **Musically** — Album downloaded!", embed)

    async def notify_stalled(
        self,
        album_title: str,
        artist_name: str,
        reason: str = "",
        retry_count: int = 0,
        next_retry_at: str | None = None,
    ) -> bool:
        """Send a notification when an album download has stalled.

        Args:
            album_title: The album title.
            artist_name: The artist name.
            reason: Why it stalled (e.g. "Not found on Qobuz").
            retry_count: Number of retries attempted.
            next_retry_at: ISO timestamp of the next retry.
        """
        fields = [
            {"name": "Reason", "value": reason or "Unknown", "inline": True},
            {"name": "Retries", "value": str(retry_count), "inline": True},
        ]
        if next_retry_at:
            fields.append({"name": "Next Retry", "value": next_retry_at, "inline": False})

        embed = {
            "title": f"{artist_name} — {album_title}",
            "description": "Album download stalled and will be retried.",
            "color": COLOR_WARNING,
            "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Musically"},
        }
        return await self.send_discord("⚠️ **Musically** — Album stalled", embed)

    async def notify_error(self, message: str, details: str = "") -> bool:
        """Send an error notification."""
        embed = {
            "title": "Error",
            "description": details or message,
            "color": COLOR_ERROR,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Musically"},
        }
        return await self.send_discord(f"❌ **Musically** — {message}", embed)

    async def notify_queued_manual(
        self, album_title: str, artist_name: str, reason: str = ""
    ) -> bool:
        """Send a notification when an album is manually queued and needs approval."""
        embed = {
            "title": f"{artist_name} — {album_title}",
            "description": f"Album queued for manual approval{f' • {reason}' if reason else ''}",
            "color": COLOR_INFO,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Musically — awaiting approval"},
        }
        return await self.send_discord(
            "📥 **Musically** — Album queued for review", embed
        )

    async def notify_watch_folder(
        self, album_title: str, artist_name: str, source_path: str = ""
    ) -> bool:
        """Send a notification when a new file is detected in the watch folder."""
        embed = {
            "title": f"{artist_name} — {album_title}",
            "description": f"New files detected in watch folder{f': {source_path}' if source_path else ''}",
            "color": COLOR_INFO,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Musically — watch folder"},
        }
        return await self.send_discord(
            "👀 **Musically** — New files in watch folder", embed
        )

