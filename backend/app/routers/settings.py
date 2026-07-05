"""Settings router – fully implemented CRUD with seeding."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DEFAULT_SETTINGS, SETTING_CATEGORIES, SETTING_DESCRIPTIONS
from app.database import get_db
from app.models.setting import Setting
from app.schemas.settings import SettingResponse, SettingsBulkUpdate

router = APIRouter()

# Settings whose values should never be returned via the API
SENSITIVE_SETTING_KEYS: set[str] = {
    "spotify_client_secret",
    "spotify_access_token_encrypted",
    "spotify_refresh_token",
    "spotify_token_expiry",
    "qobuz_password_encrypted",
    "discord_webhook_url",
    "lastfm_api_secret",
}

MASKED_VALUE = "••••••••"


def _setting_to_response(setting: Setting) -> SettingResponse:
    value = setting.value
    if setting.key in SENSITIVE_SETTING_KEYS and value:
        value = MASKED_VALUE
    return SettingResponse(
        key=setting.key,
        value=value,
        description=setting.description,
        category=setting.category,
    )


async def _seed_defaults(db: AsyncSession) -> None:
    """Ensure all default settings exist in the DB (upsert on first access)."""
    # Fetch all existing setting keys
    result = await db.execute(select(Setting.key))
    existing_keys: set[str] = {row[0] for row in result}

    added = 0
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing_keys:
            category = SETTING_CATEGORIES.get(key, "general")
            description = SETTING_DESCRIPTIONS.get(key, "")
            db.add(Setting(key=key, value=value, description=description, category=category))
            added += 1

    if added:
        await db.commit()


@router.get("/settings", response_model=dict[str, list[SettingResponse]])
async def get_settings(
    category: str | None = Query(None, description="Filter by category"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[SettingResponse]]:
    """Return all settings grouped by category. Seeds defaults if empty."""
    await _seed_defaults(db)

    stmt = select(Setting).order_by(Setting.key)
    if category:
        stmt = stmt.where(Setting.category == category)

    result = await db.execute(stmt)
    all_settings = result.scalars().all()

    grouped: dict[str, list[SettingResponse]] = {}
    for setting in all_settings:
        cat = setting.category
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(_setting_to_response(setting))

    return grouped


@router.put("/settings", response_model=dict[str, list[SettingResponse]])
async def update_settings(
    payload: SettingsBulkUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[SettingResponse]]:
    """Bulk update settings by key-value pairs. Only known keys are updated."""
    await _seed_defaults(db)

    # Fetch existing settings that need updating
    stmt = select(Setting).where(Setting.key.in_(payload.settings.keys()))
    result = await db.execute(stmt)
    existing: dict[str, Setting] = {s.key: s for s in result.scalars().all()}

    for key, new_value in payload.settings.items():
        if key in existing:
            existing[key].value = new_value
        else:
            # Create new setting if key not present (with unknown category -> general)
            category = SETTING_CATEGORIES.get(key, "general")
            description = SETTING_DESCRIPTIONS.get(key, "")
            db.add(Setting(key=key, value=new_value, description=description, category=category))

    await db.commit()

    # Return the full updated set
    stmt = select(Setting).order_by(Setting.key)
    result = await db.execute(stmt)
    all_settings = result.scalars().all()

    grouped: dict[str, list[SettingResponse]] = {}
    for setting in all_settings:
        cat = setting.category
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(_setting_to_response(setting))

    return grouped
