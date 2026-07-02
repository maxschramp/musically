"""Tests for the notification service and notification router."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting
from app.services.notifications import NotificationService


# ---------------------------------------------------------------------------
# NotificationService unit tests
# ---------------------------------------------------------------------------

@pytest.fixture
def notifier() -> NotificationService:
    return NotificationService(webhook_url="https://discord.com/api/webhooks/test/123")


@pytest.fixture
def notifier_no_url() -> NotificationService:
    return NotificationService(webhook_url=None)


@pytest.mark.asyncio
async def test_send_discord_success(notifier: NotificationService) -> None:
    """Should return True on successful Discord send."""
    with patch.object(notifier, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post.return_value = httpx.Response(204)
        mock_get_client.return_value = mock_client

        result = await notifier.send_discord("Test message")
        assert result is True


@pytest.mark.asyncio
async def test_send_discord_no_url(notifier_no_url: NotificationService) -> None:
    """Should return False when no webhook URL is configured."""
    result = await notifier_no_url.send_discord("Test")
    assert result is False


@pytest.mark.asyncio
async def test_send_discord_http_error(notifier: NotificationService) -> None:
    """Should return False on HTTP error."""
    with patch.object(notifier, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post.return_value = httpx.Response(403, json={"error": "Forbidden"})
        mock_get_client.return_value = mock_client

        result = await notifier.send_discord("Test")
        assert result is False


@pytest.mark.asyncio
async def test_send_discord_network_error(notifier: NotificationService) -> None:
    """Should return False on network error."""
    with patch.object(notifier, "_get_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_get_client.return_value = mock_client

        result = await notifier.send_discord("Test")
        assert result is False


@pytest.mark.asyncio
async def test_notify_download_embed_structure(notifier: NotificationService) -> None:
    """Should include the correct embed structure for download notifications."""
    with patch.object(notifier, "send_discord", return_value=True) as mock_send:
        result = await notifier.notify_download("Album", "Artist", "5+ plays")
        assert result is True
        call_args = mock_send.call_args
        # First positional arg is the message
        assert "downloaded" in call_args[0][0].lower()
        # Second positional arg is the embed
        embed = call_args[0][1]
        assert embed["title"] == "Artist — Album"
        assert "5+ plays" in embed["description"]
        assert embed["color"] == 0x003C33


@pytest.mark.asyncio
async def test_notify_stalled(notifier: NotificationService) -> None:
    """Should include retry info in stalled notifications."""
    with patch.object(notifier, "send_discord", return_value=True) as mock_send:
        result = await notifier.notify_stalled(
            "Album", "Artist", "Not found", retry_count=3, next_retry_at="2025-01-01T00:00:00Z"
        )
        assert result is True
        embed = mock_send.call_args[0][1]
        fields = embed.get("fields", [])
        field_names = [f["name"] for f in fields]
        assert "Reason" in field_names
        assert "Retries" in field_names


@pytest.mark.asyncio
async def test_notify_queued_manual(notifier: NotificationService) -> None:
    """Manual queue notification should include reason."""
    with patch.object(notifier, "send_discord", return_value=True) as mock_send:
        result = await notifier.notify_queued_manual("Album", "Artist", "discover playlist")
        assert result is True
        embed = mock_send.call_args[0][1]
        assert "discover playlist" in embed["description"]


@pytest.mark.asyncio
async def test_notify_watch_folder(notifier: NotificationService) -> None:
    """Watch folder notification should include source path."""
    with patch.object(notifier, "send_discord", return_value=True) as mock_send:
        result = await notifier.notify_watch_folder("Album", "Artist", "/watch/new_album")
        assert result is True
        embed = mock_send.call_args[0][1]
        assert "/watch/new_album" in embed["description"]


@pytest.mark.asyncio
async def test_notify_error(notifier: NotificationService) -> None:
    """Error notification should work."""
    with patch.object(notifier, "send_discord", return_value=True) as mock_send:
        result = await notifier.notify_error("Something broke", "Details here")
        assert result is True
        assert "Something broke" in mock_send.call_args[0][0]


@pytest.mark.asyncio
async def test_close_cleans_up(notifier: NotificationService) -> None:
    """close() should close the HTTP client."""
    # Access internal client to verify it gets cleaned up
    client = await notifier._get_client()
    assert client is not None
    await notifier.close()
    assert notifier._client is None


# ---------------------------------------------------------------------------
# Notification Router tests
# ---------------------------------------------------------------------------

async def _seed_webhook_url(db: AsyncSession, url: str) -> None:
    from sqlalchemy import select
    result = await db.execute(
        select(Setting).where(Setting.key == "discord_webhook_url")
    )
    s = result.scalar_one_or_none()
    if s:
        s.value = url
    else:
        db.add(Setting(key="discord_webhook_url", value=url, category="notifications"))
    await db.commit()


@pytest.mark.asyncio
async def test_notification_test_no_webhook_url(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/notifications/test should return failure when no URL is configured."""
    # Ensure no webhook URL in settings
    await _seed_webhook_url(db_session, "")

    response = await client.post("/api/notifications/test")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "No Discord webhook URL" in data["message"]


@pytest.mark.asyncio
async def test_notification_test_with_webhook_url(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST /api/notifications/test should attempt to send when URL is configured."""
    await _seed_webhook_url(db_session, "https://discord.com/api/webhooks/test/123")

    with patch.object(NotificationService, "send_discord", return_value=True):
        response = await client.post("/api/notifications/test")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "successfully" in data["message"].lower()


@pytest.mark.asyncio
async def test_notification_test_send_fails(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Should report failure if Discord send fails."""
    await _seed_webhook_url(db_session, "https://discord.com/api/webhooks/test/123")

    with patch.object(NotificationService, "send_discord", return_value=False):
        response = await client.post("/api/notifications/test")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
