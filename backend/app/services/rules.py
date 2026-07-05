"""Rule engine — evaluates R1-R7 rules after aggregation and creates queue actions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.album import Album, AlbumStatus, QueueType
from app.models.artist import Artist
from app.models.playlist import Playlist, PlaylistType
from app.models.playlist_track import PlaylistTrack
from app.models.setting import Setting
from app.models.track_play import TrackPlay

logger = logging.getLogger(__name__)

# Statuses that mean an album is already in the pipeline — skip creating/queueing.
_PIPELINE_STATUSES = frozenset({
    AlbumStatus.QUEUED,
    AlbumStatus.DOWNLOADING,
    AlbumStatus.DOWNLOADED,
    AlbumStatus.REJECTED,
})


@dataclass
class RuleResult:
    """Result of rule evaluation.

    Attributes:
        albums_queued_auto: Number of albums queued via R1/R2 (auto).
        albums_queued_manual: Number of albums queued via R6 (manual).
        artists_subscribed: Number of artists newly subscribed via R3/R4.
        rules_fired: List of rule names that fired at least once (e.g. "R1", "R2").
        errors: Non-fatal errors encountered during evaluation.
    """

    albums_queued_auto: int = 0
    albums_queued_manual: int = 0
    artists_subscribed: int = 0
    rules_fired: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class RuleEngine:
    """Evaluates all enabled rules and creates queue actions.

    The rule engine runs AFTER aggregation.  It reads TrackPlay data that has
    already been inserted by the aggregator and decides what to do next.

    Usage::

        engine = RuleEngine(db)
        result = await engine.evaluate()
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_setting_int(self, key: str, default: int) -> int:
        """Read a setting value from the DB as int, falling back to *default*."""
        stmt = select(Setting.value).where(Setting.key == key)
        result = await self.db.execute(stmt)
        value = result.scalar()
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            logger.warning("Setting %s=%r is not a valid int; using default %d.", key, value, default)
            return default

    async def _album_in_pipeline(self, artist_name: str, album_title: str) -> Album | None:
        """Return an Album if one already exists (case-insensitive) and is
        currently in the pipeline (queued / downloading / downloaded)."""
        stmt = select(Album).where(
            func.lower(Album.artist_name) == artist_name.lower(),
            func.lower(Album.title) == album_title.lower(),
            Album.status.in_(_PIPELINE_STATUSES),
        )
        result = await self.db.execute(stmt)
        return result.scalar()

    async def _get_or_create_album(
        self,
        artist_name: str,
        album_title: str,
        queue_type: QueueType,
        reason: str,
        play_count: int = 0,
    ) -> Album | None:
        """Return an existing album (any status) or create a new one queued.

        If an album with status in *queued / downloading / downloaded / rejected*
        already exists, returns None (skip — already handled).
        """
        # Flush any pending inserts from prior iterations so the SELECT
        # below sees all rows — avoids UniqueViolationError caused by
        # PostgreSQL collation mismatches on func.lower().
        await self.db.flush()

        # Check if album already exists (case-insensitive).
        stmt = select(Album).where(
            func.lower(Album.artist_name) == artist_name.lower(),
            func.lower(Album.title) == album_title.lower(),
        )
        row = await self.db.execute(stmt)
        album = row.scalar()

        if album is not None:
            logger.debug(
                "_get_or_create_album: FOUND existing '%s - %s' (status=%s)",
                artist_name, album_title, album.status.value if album.status else "?",
            )
            # Already in the pipeline — skip
            if album.status in _PIPELINE_STATUSES:
                logger.debug(
                    "_get_or_create_album: SKIP '%s - %s' (already in pipeline: %s)",
                    artist_name, album_title, album.status.value,
                )
                return None
            # Exists but not in pipeline (e.g. stalled) — re-queue it
            logger.info(
                "_get_or_create_album: RE-QUEUE '%s - %s' (was %s)",
                artist_name, album_title, album.status.value,
            )
            album.status = AlbumStatus.QUEUED
            album.queue_type = queue_type
            album.reason = reason
            album.play_count = max(album.play_count or 0, play_count)
            self.db.add(album)
            await self.db.flush()
            return album

        logger.debug(
            "_get_or_create_album: NOT FOUND '%s - %s', will create",
            artist_name, album_title,
        )
        # Create a brand-new Album row
        logger.info(
            "_get_or_create_album: CREATE '%s - %s'",
            artist_name, album_title,
        )
        album = Album(
            title=album_title,
            artist_name=artist_name,
            status=AlbumStatus.QUEUED,
            queue_type=queue_type,
            reason=reason,
            play_count=play_count,
        )
        self.db.add(album)
        await self.db.flush()
        return album

    # ------------------------------------------------------------------
    # R1: Play count ≥ threshold on same album → QUEUE (auto)
    # ------------------------------------------------------------------

    async def _evaluate_r1(self, threshold: int, result: RuleResult) -> None:
        """R1: Group TrackPlay records by (artist, album), count plays,
        and queue albums that meet the threshold."""
        # Subquery: count plays per (artist, album) from track_plays,
        # excluding rows with empty album_name.
        subq = (
            select(
                TrackPlay.artist_name,
                TrackPlay.album_name,
                func.count(TrackPlay.id).label("play_count"),
            )
            .where(TrackPlay.album_name != "")
            .group_by(
                func.lower(TrackPlay.artist_name),
                func.lower(TrackPlay.album_name),
            )
            .having(func.count(TrackPlay.id) >= threshold)
            .subquery()
        )

        stmt = select(
            subq.c.artist_name,
            subq.c.album_name,
            subq.c.play_count,
        ).order_by(subq.c.play_count.desc())

        rows = await self.db.execute(stmt)
        candidates = rows.all()

        rule_fired = False
        for artist_name, album_name, play_count in candidates:
            if not album_name or not artist_name:
                continue

            # Use a savepoint so a duplicate on THIS album doesn't
            # roll back previously-queued albums in the same rule.
            try:
                async with self.db.begin_nested():
                    album = await self._get_or_create_album(
                        artist_name=artist_name,
                        album_title=album_name,
                        queue_type=QueueType.MANUAL,
                        reason=f"{play_count} plays",
                        play_count=play_count,
                    )
            except IntegrityError:
                logger.warning(
                    "R1: Skipping duplicate '%s - %s'",
                    artist_name, album_name,
                )
                continue

            if album is not None:
                result.albums_queued_auto += 1
                rule_fired = True
                logger.info(
                    "R1: Queued '%s - %s' (%d plays)",
                    artist_name, album_name, play_count,
                )

        if rule_fired:
            result.rules_fired.append("R1")

    # ------------------------------------------------------------------
    # R2: Song on seasonal playlist → QUEUE (auto)
    # ------------------------------------------------------------------

    async def _evaluate_r2(self, result: RuleResult) -> None:
        """R2: For each active seasonal playlist, queue every unique album
        found in its tracks that isn't already in the pipeline."""
        # Fetch active seasonal playlists
        stmt = select(Playlist).where(
            Playlist.playlist_type == PlaylistType.SEASONAL,
            Playlist.is_active == True,  # noqa: E712
        )
        rows = await self.db.execute(stmt)
        playlists = rows.scalars().all()

        rule_fired = False
        for playlist in playlists:
            # Fetch playlist tracks
            track_stmt = select(PlaylistTrack).where(
                PlaylistTrack.playlist_id == playlist.id,
            )
            track_rows = await self.db.execute(track_stmt)
            tracks = track_rows.scalars().all()

            for track in tracks:
                if not track.album_name or not track.artist_name:
                    continue

                try:
                    async with self.db.begin_nested():
                        album = await self._get_or_create_album(
                            artist_name=track.artist_name,
                            album_title=track.album_name,
                            queue_type=QueueType.MANUAL,
                            reason=f"In {playlist.name}",
                        )
                except IntegrityError:
                    logger.warning(
                        "R2: Skipping duplicate '%s - %s'",
                        track.artist_name, track.album_name,
                    )
                    continue

                if album is not None:
                    result.albums_queued_auto += 1
                    rule_fired = True
                    logger.info(
                        "R2: Queued '%s - %s' (seasonal playlist '%s')",
                        track.artist_name, track.album_name, playlist.name,
                    )

        if rule_fired:
            result.rules_fired.append("R2")

    # ------------------------------------------------------------------
    # R3: Artist play count ≥ threshold → SUBSCRIBE
    # ------------------------------------------------------------------

    async def _evaluate_r3(self, threshold: int, result: RuleResult) -> None:
        """R3: Subscribe artists whose total_play_count meets the threshold."""
        stmt = select(Artist).where(
            Artist.total_play_count >= threshold,
            Artist.subscribed == False,  # noqa: E712
        )
        rows = await self.db.execute(stmt)
        artists = rows.scalars().all()

        for artist in artists:
            artist.subscribed = True
            artist.subscription_source = "auto_play_count"
            self.db.add(artist)
            result.artists_subscribed += 1
            logger.info(
                "R3: Subscribed '%s' (%d plays)",
                artist.name, artist.total_play_count,
            )

        if artists:
            result.rules_fired.append("R3")

    # ------------------------------------------------------------------
    # R4: Already own ≥ N albums by artist → SUBSCRIBE
    # ------------------------------------------------------------------

    async def _evaluate_r4(self, threshold: int, result: RuleResult) -> None:
        """R4: Subscribe artists whose albums_in_library meets the threshold."""
        stmt = select(Artist).where(
            Artist.albums_in_library >= threshold,
            Artist.subscribed == False,  # noqa: E712
        )
        rows = await self.db.execute(stmt)
        artists = rows.scalars().all()

        for artist in artists:
            artist.subscribed = True
            artist.subscription_source = "auto_library_size"
            self.db.add(artist)
            result.artists_subscribed += 1
            logger.info(
                "R4: Subscribed '%s' (%d albums in library)",
                artist.name, artist.albums_in_library,
            )

        if artists:
            result.rules_fired.append("R4")

    # ------------------------------------------------------------------
    # R5: Subscribed artist has new release → QUEUE (auto)  [STUB]
    # ------------------------------------------------------------------

    async def _evaluate_r5(self, result: RuleResult) -> None:
        """R5: Check MusicBrainz for new releases by subscribed artists.

        STUB — not yet implemented.
        """
        logger.info("R5: MusicBrainz new release check not yet implemented.")
        result.errors.append("R5: MusicBrainz new release check not yet implemented.")

    # ------------------------------------------------------------------
    # R6: Song from discover playlists → QUEUE (manual)
    # ------------------------------------------------------------------

    async def _evaluate_r6(self, result: RuleResult) -> None:
        """R6: Queue albums from discover playlists with >N tracks for manual review.

        Aggregates track counts across all active DISCOVER playlists and only
        queues albums that have more than ``swipe_min_track_count`` tracks
        (default 4). Singles and short EPs are skipped to keep the swipe queue
        focused on full-length releases.
        """
        min_tracks = await self._get_setting_int("swipe_min_track_count", 4)

        stmt = select(Playlist).where(
            Playlist.playlist_type == PlaylistType.DISCOVER,
            Playlist.is_active == True,  # noqa: E712
        )
        rows = await self.db.execute(stmt)
        playlists = rows.scalars().all()

        playlist_ids = [p.id for p in playlists]
        if not playlist_ids:
            return

        # Count tracks per (artist, album) across all discover playlists
        track_count_stmt = (
            select(
                PlaylistTrack.artist_name,
                PlaylistTrack.album_name,
                func.count(PlaylistTrack.id).label("track_count"),
            )
            .where(
                PlaylistTrack.playlist_id.in_(playlist_ids),
                PlaylistTrack.album_name != "",
                PlaylistTrack.artist_name != "",
            )
            .group_by(
                func.lower(PlaylistTrack.artist_name),
                func.lower(PlaylistTrack.album_name),
            )
            .having(func.count(PlaylistTrack.id) > min_tracks)
        )
        track_rows = await self.db.execute(track_count_stmt)
        candidates = track_rows.all()

        rule_fired = False
        for artist_name, album_name, track_count in candidates:
            try:
                async with self.db.begin_nested():
                    album = await self._get_or_create_album(
                        artist_name=artist_name,
                        album_title=album_name,
                        queue_type=QueueType.MANUAL,
                        reason=f"Discover: {track_count} tracks",
                    )
            except IntegrityError:
                await self.db.rollback()
                logger.warning(
                    "R6: Skipping duplicate '%s - %s'",
                    artist_name,
                    album_name,
                )
                continue

            if album is not None:
                result.albums_queued_manual += 1
                rule_fired = True
                logger.info(
                    "R6: Queued '%s - %s' (%d tracks from discover playlists)",
                    artist_name,
                    album_name,
                    track_count,
                )

        if rule_fired:
            result.rules_fired.append("R6")

        logger.info(
            "R6: processed %d playlists, found %d albums with >%d tracks, queued %d",
            len(playlists),
            len(candidates),
            min_tracks,
            result.albums_queued_manual,
        )

        # --- Retroactive cleanup: remove queued albums that no longer meet the threshold ---
        # Find all manual-queued albums and check if they still have enough tracks.
        # Only cleans up queue_type=MANUAL albums (from R6), not auto or watch_folder.
        # Limit to 500 per run to keep performance predictable.
        cleanup_where = (
            Album.status == AlbumStatus.QUEUED,
            Album.queue_type == QueueType.MANUAL,
        )
        total_queued = (
            await self.db.execute(select(func.count(Album.id)).where(*cleanup_where))
        ).scalar()
        logger.debug(
            "R6 cleanup: checking %d queued albums (limit 500), threshold=%d",
            total_queued,
            min_tracks,
        )

        cleanup_stmt = (
            select(Album)
            .where(*cleanup_where)
            .limit(500)
        )
        cleanup_rows = await self.db.execute(cleanup_stmt)
        queued_albums = cleanup_rows.scalars().all()

        removed = 0
        for album in queued_albums:
            # Count how many playlist tracks exist for this album
            count_stmt = select(func.count(PlaylistTrack.id)).where(
                func.lower(PlaylistTrack.artist_name) == func.lower(album.artist_name),
                func.lower(PlaylistTrack.album_name) == func.lower(album.title),
            )
            count_result = await self.db.execute(count_stmt)
            track_count = count_result.scalar() or 0

            if track_count < min_tracks:
                await self.db.delete(album)
                removed += 1
                logger.info(
                    "R6 cleanup: removed '%s - %s' (only %d tracks, threshold=%d)",
                    album.artist_name,
                    album.title,
                    track_count,
                    min_tracks,
                )

        if removed:
            await self.db.flush()
            logger.info("R6 cleanup: removed %d albums below track threshold", removed)

    # ------------------------------------------------------------------
    # R7: File appears in watch folder → QUEUE (tag+move)  [STUB]
    # ------------------------------------------------------------------

    async def _evaluate_r7(self, result: RuleResult) -> None:
        """R7: Watch folder monitoring for new files.

        STUB — not yet implemented (requires filesystem watchdog).
        """
        logger.info("R7: Watch folder monitoring not yet implemented.")
        result.errors.append("R7: Watch folder monitoring not yet implemented.")

    # ------------------------------------------------------------------
    # Main evaluate loop
    # ------------------------------------------------------------------

    async def evaluate(self) -> RuleResult:
        """Evaluate all enabled rules and return actions taken.

        Rules are evaluated in order (R1 → R7).  Each rule is independent;
        a failure in one rule does not prevent others from running.
        Each rule commits its own changes immediately after success so that
        a later rule's failure cannot roll back prior rules' work.
        """
        result = RuleResult()

        # Read thresholds from DB settings
        r1_threshold = await self._get_setting_int("album_play_threshold", 5)
        r3_threshold = await self._get_setting_int("artist_subscribe_play_threshold", 20)
        r4_threshold = await self._get_setting_int("library_albums_subscribe_threshold", 3)

        # --- R1: play count → auto queue ---
        try:
            await self._evaluate_r1(r1_threshold, result)
            await self.db.commit()
            logger.info("R1 committed: %d albums queued", result.albums_queued_auto)
        except Exception:
            await self.db.rollback()
            logger.exception("R1 evaluation failed.")
            result.errors.append("R1: evaluation error — see logs.")

        # --- R2: seasonal playlist → auto queue ---
        try:
            await self._evaluate_r2(result)
            await self.db.commit()
            logger.info("R2 committed: %d albums queued", result.albums_queued_auto)
        except Exception:
            await self.db.rollback()
            logger.exception("R2 evaluation failed.")
            result.errors.append("R2: evaluation error — see logs.")

        # --- R3: artist play count → subscribe ---
        try:
            await self._evaluate_r3(r3_threshold, result)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            logger.exception("R3 evaluation failed.")
            result.errors.append("R3: evaluation error — see logs.")

        # --- R4: library size → subscribe ---
        try:
            await self._evaluate_r4(r4_threshold, result)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            logger.exception("R4 evaluation failed.")
            result.errors.append("R4: evaluation error — see logs.")

        # --- R5: new releases (stub) ---
        try:
            await self._evaluate_r5(result)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            logger.exception("R5 evaluation failed.")

        # --- R6: discover playlists ---
        try:
            await self._evaluate_r6(result)
            await self.db.commit()
            logger.info("R6 committed: %d albums queued", result.albums_queued_manual)
        except Exception:
            await self.db.rollback()
            logger.exception("R6 evaluation failed.")

        # --- R7: watch folder (stub) ---
        try:
            await self._evaluate_r7(result)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            logger.exception("R7 evaluation failed.")

        logger.info(
            "Rule engine complete: auto_queued=%d manual_queued=%d subscribed=%d "
            "rules=%s errors=%d",
            result.albums_queued_auto,
            result.albums_queued_manual,
            result.artists_subscribed,
            result.rules_fired,
            len(result.errors),
        )

        return result
