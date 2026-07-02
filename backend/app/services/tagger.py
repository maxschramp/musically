"""FLAC metadata tagger — writes Vorbis comments to downloaded FLAC files.

Uses the ``mutagen`` library (a transitive dependency of beets) to write
standard Vorbis comment tags (ARTIST, ALBUM, TITLE, TRACKNUMBER, etc.)
so that beets can identify and import the files.

Adapted from the reference browser extension's tagger.js logic.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.id3._util import error as ID3Error

logger = logging.getLogger(__name__)

# Map our logical tag names → Vorbis comment field names.
# All of these are standard and recognised by beets / MusicBrainz Picard.
TAG_MAP: dict[str, str] = {
    "artist": "ARTIST",
    "album": "ALBUM",
    "title": "TITLE",
    "tracknumber": "TRACKNUMBER",
    "tracktotal": "TRACKTOTAL",
    "date": "DATE",
    "isrc": "ISRC",
    "label": "LABEL",
    "genre": "GENRE",
    "albumartist": "ALBUMARTIST",
}


class TaggerService:
    """Writes FLAC metadata tags (Vorbis comments) to downloaded files.

    This is a critical step in the download pipeline — Qobuz delivers raw
    FLAC streams with **no** metadata, and beets requires at least ARTIST,
    ALBUM, and TITLE tags to match against MusicBrainz.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def tag_album(
        self,
        album_dir: str | Path,
        artist: str,
        album: str,
        tracks: list[dict],
        cover_data: bytes | None = None,
        release_date: str | None = None,
        label: str | None = None,
        genre: str | None = None,
    ) -> int:
        """Tag all FLAC files in *album_dir* with metadata.

        Files are matched to tracks by parsing the leading track number
        from the filename (e.g. ``"01 - Song.flac"`` → track 1).

        Parameters
        ----------
        album_dir:
            Directory containing the downloaded FLAC files.
        artist:
            Artist name for the ARTIST / ALBUMARTIST tags.
        album:
            Album title for the ALBUM tag.
        tracks:
            List of track dicts, each containing at least ``track_number``
            and ``title``.  Optional keys: ``isrc``.
        cover_data:
            Raw image bytes to embed as cover art (JPEG / PNG).  If
            ``None``, the method looks for ``cover.jpg`` or ``cover.png``
            in *album_dir*.
        release_date:
            Release date string (YYYY, YYYY-MM-DD, etc.) for the DATE tag.
        label:
            Record label string for the LABEL tag.
        genre:
            Genre string for the GENRE tag.

        Returns
        -------
        int
            Number of FLAC files successfully tagged.
        """
        album_dir = Path(album_dir)
        if not album_dir.is_dir():
            logger.warning("Tagger: album_dir does not exist: %s", album_dir)
            return 0

        # Build a lookup: track_number → track dict
        track_map: dict[int, dict] = {}
        for t in tracks:
            tn = t.get("track_number")
            if tn is not None:
                track_map[int(tn)] = t

        # Resolve cover art (cover_data takes priority)
        embedded_cover = cover_data
        if embedded_cover is None:
            embedded_cover = self._load_cover_from_dir(album_dir)

        # Find all FLAC files, sorted by name for predictable ordering
        flac_files = sorted(
            p for p in album_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".flac"
        )

        if not flac_files:
            logger.warning("Tagger: no .flac files found in %s", album_dir)
            return 0

        track_total = len(flac_files)
        tagged_count = 0

        for flac_path in flac_files:
            try:
                track_num = self._parse_track_number(flac_path.name)
                track_info = track_map.get(track_num) if track_num is not None else None

                # Build the tag dict
                tags: dict[str, str] = {}

                # Per-track tags
                if track_info:
                    title = track_info.get("title", "")
                    if title:
                        tags["title"] = title
                    isrc = track_info.get("isrc")
                    if isrc:
                        tags["isrc"] = isrc

                # Album-level tags
                if artist:
                    tags["artist"] = artist
                    tags["albumartist"] = artist
                if album:
                    tags["album"] = album
                if release_date:
                    tags["date"] = release_date
                if label:
                    tags["label"] = label
                if genre:
                    tags["genre"] = genre

                # Track ordering
                if track_num is not None:
                    tags["tracknumber"] = str(track_num)
                tags["tracktotal"] = str(track_total)

                # Write tags
                self._write_tags(flac_path, tags, embedded_cover)
                tagged_count += 1
                logger.debug("Tagged: %s", flac_path.name)

            except Exception:
                logger.exception("Failed to tag %s", flac_path)

        logger.info(
            "Tagged %d/%d FLAC files in %s",
            tagged_count, len(flac_files), album_dir,
        )
        return tagged_count

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_track_number(filename: str) -> int | None:
        """Extract the track number from a filename like ``"01 - Song.flac"``.

        Returns ``None`` if no leading number is found.
        """
        m = re.match(r"^(\d{1,4})\b", filename)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _load_cover_from_dir(album_dir: Path) -> bytes | None:
        """Look for cover.jpg or cover.png in *album_dir* and return its bytes."""
        for name in ("cover.jpg", "cover.png", "Cover.jpg", "Cover.png"):
            path = album_dir / name
            if path.is_file():
                try:
                    return path.read_bytes()
                except OSError:
                    logger.warning("Tagger: could not read cover file %s", path)
        return None

    def _write_tags(
        self,
        flac_path: Path,
        tags: dict[str, str],
        cover_data: bytes | None,
    ) -> None:
        """Open a FLAC file, write Vorbis comments, and save."""
        audio = FLAC(str(flac_path))

        # Clear any existing tags (should be none from Qobuz, but be safe)
        audio.delete()

        for key, value in tags.items():
            vorbis_key = TAG_MAP.get(key, key.upper())
            audio[vorbis_key] = value

        # Embed cover art
        if cover_data:
            try:
                picture = Picture()
                picture.type = 3  # Cover (front)
                picture.mime = self._guess_mime(cover_data)
                picture.desc = "cover"
                picture.data = cover_data
                audio.add_picture(picture)
            except (ID3Error, ValueError, OSError) as exc:
                logger.warning("Tagger: could not embed cover art in %s: %s", flac_path.name, exc)

        audio.save()

    @staticmethod
    def _guess_mime(data: bytes) -> str:
        """Guess MIME type from magic bytes (JPEG or PNG)."""
        if data[:4] == b"\xff\xd8\xff\xe0" or data[:4] == b"\xff\xd8\xff\xe1":
            return "image/jpeg"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        # Fall back to JPEG — most cover art is JPEG
        return "image/jpeg"
