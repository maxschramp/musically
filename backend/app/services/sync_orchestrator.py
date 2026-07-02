"""Sync orchestrator — ties together LastFM polling, aggregation, and sync history."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.setting import Setting
from app.models.sync_history import SyncHistory
from app.models.track_play import TrackPlay
from app.services.aggregator import aggregate_plays, AggregationResult
from app.services.lastfm import LastFMService
from app.services.rules import RuleEngine, RuleResult

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a full sync cycle."""

    sync_id: uuid.UUID
    started_at: datetime
    completed_at: datetime
    status: str  # "completed" | "failed" | "skipped"
    tracks_fetched: int
    tracks_new: int
    albums_updated: int
    artists_updated: int
    albums_queued_auto: int = 0
    albums_queued_manual: int = 0
    artists_subscribed: int = 0
    rules_fired: list[str] | None = None
    error_message: str | None = None


class SyncOrchestrator:
    """Orchestrates the full sync pipeline: check config → fetch → aggregate → record."""

    def __init__(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self.db_session_factory = db_session_factory
        self.settings = settings

    async def _get_setting(self, db: AsyncSession, key: str, default: str = "") -> str:
        """Read a setting value from the DB, falling back to the provided default."""
        stmt = select(Setting.value).where(Setting.key == key)
        result = await db.execute(stmt)
        value = result.scalar()
        return value if value is not None else default

    async def run_sync(self) -> SyncResult:
        """Execute a full sync cycle.

        1. Check if LastFM is enabled and API key is set.
        2. Determine the time range (backfill vs. normal).
        3. Create LastFMService and call aggregate_plays().
        4. Record SyncHistory entry.
        5. Return SyncResult.
        """
        sync_id = uuid.uuid4()
        started_at = datetime.now(tz=timezone.utc)

        async with self.db_session_factory() as db:
            try:
                # 1. Check if LastFM is enabled
                lastfm_enabled = await self._get_setting(db, "lastfm_enabled", "true")
                if lastfm_enabled.lower() != "true":
                    logger.info("LastFM sync skipped: lastfm_enabled is not 'true'.")
                    error_message = "lastfm_enabled is false"
                    completed_at = datetime.now(tz=timezone.utc)
                    sync_history = SyncHistory(
                        id=sync_id,
                        started_at=started_at,
                        completed_at=completed_at,
                        status="skipped",
                        tracks_fetched=0,
                        tracks_new=0,
                        albums_updated=0,
                        artists_updated=0,
                        error_message=error_message,
                    )
                    db.add(sync_history)
                    await db.commit()
                    return SyncResult(
                        sync_id=sync_id,
                        started_at=started_at,
                        completed_at=completed_at,
                        status="skipped",
                        tracks_fetched=0,
                        tracks_new=0,
                        albums_updated=0,
                        artists_updated=0,
                        error_message=error_message,
                    )

                # 2. Get API key from DB (fall back to env var)
                api_key = await self._get_setting(db, "lastfm_api_key", "")
                if not api_key:
                    api_key = self.settings.LASTFM_API_KEY or ""

                if not api_key:
                    logger.info("LastFM sync skipped: no API key configured.")
                    error_message = "No LastFM API key configured"
                    completed_at = datetime.now(tz=timezone.utc)
                    sync_history = SyncHistory(
                        id=sync_id,
                        started_at=started_at,
                        completed_at=completed_at,
                        status="skipped",
                        tracks_fetched=0,
                        tracks_new=0,
                        albums_updated=0,
                        artists_updated=0,
                        error_message=error_message,
                    )
                    db.add(sync_history)
                    await db.commit()
                    return SyncResult(
                        sync_id=sync_id,
                        started_at=started_at,
                        completed_at=completed_at,
                        status="skipped",
                        tracks_fetched=0,
                        tracks_new=0,
                        albums_updated=0,
                        artists_updated=0,
                        error_message=error_message,
                    )

                # 3. Get LastFM username
                username = await self._get_setting(db, "lastfm_username", "")
                if not username:
                    logger.info("LastFM sync skipped: no username configured.")
                    error_message = "No LastFM username configured"
                    completed_at = datetime.now(tz=timezone.utc)
                    sync_history = SyncHistory(
                        id=sync_id,
                        started_at=started_at,
                        completed_at=completed_at,
                        status="skipped",
                        tracks_fetched=0,
                        tracks_new=0,
                        albums_updated=0,
                        artists_updated=0,
                        error_message=error_message,
                    )
                    db.add(sync_history)
                    await db.commit()
                    return SyncResult(
                        sync_id=sync_id,
                        started_at=started_at,
                        completed_at=completed_at,
                        status="skipped",
                        tracks_fetched=0,
                        tracks_new=0,
                        albums_updated=0,
                        artists_updated=0,
                        error_message=error_message,
                    )

                # 4. Determine time range (backfill vs. normal)
                now_ts = int(datetime.now(tz=timezone.utc).timestamp())
                from_ts: int | None = None

                # Check if any TrackPlay records exist
                stmt = select(func.max(TrackPlay.played_at))
                result = await db.execute(stmt)
                last_played = result.scalar()

                if last_played is None:
                    # Backfill mode: no existing records
                    backfill_days_str = await self._get_setting(db, "backfill_days", "30")
                    try:
                        backfill_days = int(backfill_days_str)
                    except ValueError:
                        backfill_days = 30
                    from_ts = now_ts - (backfill_days * 24 * 3600)
                    logger.info("Backfill mode: fetching since %d days ago (ts=%d)", backfill_days, from_ts)
                else:
                    # Normal mode: resume from last play
                    from_ts = int(last_played.timestamp())
                    logger.info("Normal mode: fetching since last play at ts=%d", from_ts)

                # 5. Get rate limit
                rate_limit_str = await self._get_setting(db, "lastfm_rate_limit_rps", "4.5")
                try:
                    rate_limit_rps = float(rate_limit_str)
                except ValueError:
                    rate_limit_rps = 4.5

                # 6. Create LastFM service and run aggregation
                lastfm = LastFMService(
                    api_key=api_key,
                    user=username,
                    rate_limit_rps=rate_limit_rps,
                )

                try:
                    agg_result = await aggregate_plays(
                        db=db,
                        lastfm=lastfm,
                        from_ts=from_ts,
                        to_ts=now_ts,
                    )
                finally:
                    await lastfm.close()

                # 7. Run rule engine
                rule_engine = RuleEngine(db)
                try:
                    rule_result = await rule_engine.evaluate()
                except Exception:
                    logger.exception("Rule engine evaluation failed; continuing with empty result.")
                    rule_result = RuleResult()

                logger.info(
                    "Rule engine: auto_queued=%d manual_queued=%d subscribed=%d rules=%s",
                    rule_result.albums_queued_auto,
                    rule_result.albums_queued_manual,
                    rule_result.artists_subscribed,
                    rule_result.rules_fired,
                )

                # 8. Spotify playlist sync (if enabled)
                spotify_enabled = await self._get_setting(db, "spotify_enabled", "true")
                if spotify_enabled.lower() == "true":
                    try:
                        spotify_client_id = await self._get_setting(db, "spotify_client_id", "")
                        spotify_client_secret = await self._get_setting(db, "spotify_client_secret", "")
                        if spotify_client_id and spotify_client_secret:
                            # Only sync if user has connected (refresh token exists)
                            from app.services.spotify import (
                                SpotifyService,
                                _decrypt_token,
                            )
                            encrypted_refresh = await self._get_setting(
                                db, "spotify_refresh_token", ""
                            )
                            if _decrypt_token(encrypted_refresh):
                                spotify_redirect = await self._get_setting(
                                    db,
                                    "spotify_redirect_uri",
                                    "http://localhost:8000/api/spotify/auth/callback",
                                )
                                spotify = SpotifyService(
                                    client_id=spotify_client_id,
                                    client_secret=spotify_client_secret,
                                    redirect_uri=spotify_redirect,
                                )
                                # Pre-load access token
                                encrypted_access = await self._get_setting(
                                    db, "spotify_access_token_encrypted", ""
                                )
                                if encrypted_access:
                                    spotify._access_token = _decrypt_token(encrypted_access)
                                expiry_str = await self._get_setting(
                                    db, "spotify_token_expiry", ""
                                )
                                if expiry_str:
                                    from datetime import datetime as dt
                                    try:
                                        spotify._token_expiry = dt.fromisoformat(expiry_str)
                                    except ValueError:
                                        pass

                                try:
                                    sync_result = await spotify.sync_playlists(db)
                                    logger.info("Spotify sync: %s", sync_result)
                                finally:
                                    await spotify.close()
                    except Exception:
                        logger.exception("Spotify playlist sync failed")

                # 9. Record sync history
                completed_at = datetime.now(tz=timezone.utc)
                sync_history = SyncHistory(
                    id=sync_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    status="completed",
                    tracks_fetched=agg_result.tracks_fetched,
                    tracks_new=agg_result.tracks_new,
                    albums_updated=agg_result.albums_updated,
                    artists_updated=agg_result.artists_updated,
                    albums_queued_auto=rule_result.albums_queued_auto,
                    albums_queued_manual=rule_result.albums_queued_manual,
                    artists_subscribed=rule_result.artists_subscribed,
                    rules_fired=(
                        json.dumps(rule_result.rules_fired)
                        if rule_result.rules_fired
                        else None
                    ),
                    error_message=None,
                )
                db.add(sync_history)
                await db.commit()

                logger.info("Sync completed: %s", agg_result)
                return SyncResult(
                    sync_id=sync_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    status="completed",
                    tracks_fetched=agg_result.tracks_fetched,
                    tracks_new=agg_result.tracks_new,
                    albums_updated=agg_result.albums_updated,
                    artists_updated=agg_result.artists_updated,
                    albums_queued_auto=rule_result.albums_queued_auto,
                    albums_queued_manual=rule_result.albums_queued_manual,
                    artists_subscribed=rule_result.artists_subscribed,
                    rules_fired=rule_result.rules_fired if rule_result.rules_fired else None,
                    error_message=None,
                )

            except Exception as exc:
                logger.exception("Sync failed with error: %s", exc)
                completed_at = datetime.now(tz=timezone.utc)
                error_message = str(exc)
                try:
                    sync_history = SyncHistory(
                        id=sync_id,
                        started_at=started_at,
                        completed_at=completed_at,
                        status="failed",
                        tracks_fetched=0,
                        tracks_new=0,
                        albums_updated=0,
                        artists_updated=0,
                        error_message=error_message,
                    )
                    db.add(sync_history)
                    await db.commit()
                except Exception:
                    logger.exception("Failed to record SyncHistory for failed sync.")

                return SyncResult(
                    sync_id=sync_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    status="failed",
                    tracks_fetched=0,
                    tracks_new=0,
                    albums_updated=0,
                    artists_updated=0,
                    error_message=error_message,
                )
