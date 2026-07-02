"""Play aggregation service: fetch LastFM data, deduplicate, and update counts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.album import Album
from app.models.artist import Artist
from app.models.track_play import TrackPlay
from app.services.lastfm import LastFMTrack, LastFMService

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


@dataclass
class AggregationResult:
    """Result of an aggregation run."""

    tracks_fetched: int
    tracks_new: int
    albums_updated: int
    artists_updated: int


async def aggregate_plays(
    db: AsyncSession,
    lastfm: LastFMService,
    from_ts: int | None = None,
    to_ts: int | None = None,
    max_pages: int = 10,
) -> AggregationResult:
    """Fetch tracks from LastFM, deduplicate, insert TrackPlay records,
    and update Album/Artist play counts.

    Does NOT auto-create albums or artists — that's the rule engine's job.

    Args:
        db: Async database session.
        lastfm: Configured LastFMService instance.
        from_ts: Unix timestamp to fetch from (None = no lower bound).
        to_ts: Unix timestamp to fetch to (None = now).
        max_pages: Maximum pages to fetch from LastFM.

    Returns:
        AggregationResult with counts of what was done.
    """
    # 1. Fetch from LastFM
    tracks: list[LastFMTrack] = await lastfm.fetch_all_recent(
        from_ts=from_ts,
        to_ts=to_ts,
        max_pages=max_pages,
    )
    tracks_fetched = len(tracks)

    if not tracks:
        logger.info("No tracks fetched from LastFM; nothing to aggregate.")
        return AggregationResult(
            tracks_fetched=0,
            tracks_new=0,
            albums_updated=0,
            artists_updated=0,
        )

    # 2. Deduplicate: check which track_name + artist_name + played_at combos already exist
    tracks_new = 0
    new_plays: list[TrackPlay] = []
    # Collect existing keys in batches to avoid huge IN queries
    seen: set[tuple[str, str, datetime]] = set()

    # Query existing records for all track/artist/played_at combos
    for i in range(0, len(tracks), BATCH_SIZE):
        batch = tracks[i : i + BATCH_SIZE]
        # Build conditions
        for track in batch:
            key = (track.track_name.lower(), track.artist_name.lower(), track.played_at)
            if key in seen:
                continue
            seen.add(key)

            # Check if this exact play already exists
            stmt = select(TrackPlay.id).where(
                func.lower(TrackPlay.track_name) == track.track_name.lower(),
                func.lower(TrackPlay.artist_name) == track.artist_name.lower(),
                TrackPlay.played_at == track.played_at,
            )
            result = await db.execute(stmt)
            existing = result.scalar()
            if existing is None:
                new_play = TrackPlay(
                    track_name=track.track_name,
                    artist_name=track.artist_name,
                    album_name=track.album_name or "",
                    album_mbid=None,
                    artist_mbid=track.artist_mbid,
                    played_at=track.played_at,
                )
                new_plays.append(new_play)
                tracks_new += 1

    # 3. Bulk insert new track plays in batches
    for i in range(0, len(new_plays), BATCH_SIZE):
        batch = new_plays[i : i + BATCH_SIZE]
        db.add_all(batch)
        await db.flush()
    if new_plays:
        await db.commit()
        logger.info("Inserted %d new TrackPlay records.", len(new_plays))

    # 4. Aggregate album play counts from all tracks (only update existing albums)
    albums_updated = 0
    album_counts: dict[tuple[str, str], int] = {}  # (artist_name, album_name) -> count
    for track in tracks:
        if track.album_name:
            key = (track.artist_name.lower(), track.album_name.lower())
            album_counts[key] = album_counts.get(key, 0) + 1

    for (artist_lower, album_lower), count in album_counts.items():
        stmt = select(Album).where(
            func.lower(Album.artist_name) == artist_lower,
            func.lower(Album.title) == album_lower,
        )
        result = await db.execute(stmt)
        album = result.scalar()
        if album is not None:
            album.play_count = (album.play_count or 0) + count
            albums_updated += 1

    if albums_updated:
        await db.commit()
        logger.info("Updated play_count for %d albums.", albums_updated)

    # 5. Aggregate artist play counts (only update existing artists)
    artists_updated = 0
    artist_counts: dict[str, int] = {}  # artist_name (lower) -> count
    for track in tracks:
        key = track.artist_name.lower()
        artist_counts[key] = artist_counts.get(key, 0) + 1

    for artist_lower, count in artist_counts.items():
        stmt = select(Artist).where(func.lower(Artist.name) == artist_lower)
        result = await db.execute(stmt)
        artist = result.scalar()
        if artist is not None:
            artist.total_play_count = (artist.total_play_count or 0) + count
            artists_updated += 1

    if artists_updated:
        await db.commit()
        logger.info("Updated total_play_count for %d artists.", artists_updated)

    logger.info(
        "Aggregation complete: fetched=%d new=%d albums_updated=%d artists_updated=%d",
        tracks_fetched,
        tracks_new,
        albums_updated,
        artists_updated,
    )

    return AggregationResult(
        tracks_fetched=tracks_fetched,
        tracks_new=tracks_new,
        albums_updated=albums_updated,
        artists_updated=artists_updated,
    )
