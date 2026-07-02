"""Notifications router — Discord webhook test endpoint and status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.setting import Setting
from app.services.notifications import NotificationService

router = APIRouter()


@router.post("/notifications/test")
async def test_notification(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a test notification via Discord webhook.

    Reads the discord_webhook_url from the settings table.
    Returns success/failure with a descriptive message.
    """
    # Read webhook URL from settings
    result = await db.execute(
        select(Setting).where(Setting.key == "discord_webhook_url")
    )
    setting = result.scalar_one_or_none()
    webhook_url = setting.value if setting and setting.value else None

    if not webhook_url:
        return {
            "success": False,
            "message": "No Discord webhook URL configured. Set 'discord_webhook_url' in settings.",
        }

    notifier = NotificationService(webhook_url=webhook_url)

    try:
        ok = await notifier.send_discord(
            message="🧪 **Musically test notification** — If you see this, notifications are working! 🎵",
            embed={
                "title": "Musically Notification Test",
                "description": "Your Discord webhook is configured correctly.",
                "color": 0x003C33,  # Musically green
                "fields": [
                    {"name": "Status", "value": "✅ Connected", "inline": True},
                    {"name": "Service", "value": "Musically Backend", "inline": True},
                ],
            },
        )
        await notifier.close()

        if ok:
            return {"success": True, "message": "Test notification sent successfully!"}
        else:
            return {
                "success": False,
                "message": "Failed to send notification. Check the webhook URL and Discord channel permissions.",
            }
    except Exception as exc:
        await notifier.close()
        return {
            "success": False,
            "message": f"Error sending test notification: {exc}",
        }

