"""Tests for the FLAC metadata tagger service.

Tests tag_album with real FLAC files from the download staging area
and verifies that beets can subsequently identify them.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from mutagen.flac import FLAC

from app.services.tagger import TaggerService

# Path to real (untagged) downloaded FLAC files for integration testing.
# These are Qobuz downloads with NO metadata.
REAL_DOWNLOADS_DIR = (
    Path(__file__).resolve().parents[2]
    / "data" / "downloads" / "06cd5a7c-c7f2-44fa-bf26-c205010b1170"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flac_tags(flac_path: Path) -> dict[str, str]:
    """Read back Vorbis comment tags from a FLAC file."""
    audio = FLAC(str(flac_path))
    tags: dict[str, str] = {}
    if audio.tags:
        for k, v in audio.tags.items():
            tags[k.upper()] = str(v[0]) if isinstance(v, list) else str(v)
    return tags


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestTaggerService:
    """Unit tests for TaggerService."""

    @pytest.fixture
    def tagger(self) -> TaggerService:
        return TaggerService()

    # -- parse_track_number --------------------------------------------------

    @pytest.mark.parametrize(
        "filename, expected",
        [
            ("01 - Song.flac", 1),
            ("12 - A Track.flac", 12),
            ("001 - Intro.flac", 1),
            ("no_number.flac", None),
            ("song.flac", None),
            ("", None),
        ],
    )
    def test_parse_track_number(self, filename: str, expected: int | None) -> None:
        assert TaggerService._parse_track_number(filename) == expected

    # -- tag_album with empty / nonexistent dirs -----------------------------

    @pytest.mark.asyncio
    async def test_tag_album_nonexistent_dir(self, tagger: TaggerService) -> None:
        count = await tagger.tag_album(
            "/nonexistent/path",
            artist="Test",
            album="Test",
            tracks=[],
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_tag_album_empty_dir(self, tagger: TaggerService) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            count = await tagger.tag_album(
                tmp,
                artist="Test",
                album="Test",
                tracks=[],
            )
            assert count == 0

    # -- tag_album with copied FLAC files ------------------------------------

    @pytest.mark.asyncio
    async def test_tag_album_basic_tagging(self, tagger: TaggerService) -> None:
        """Tag a single FLAC file with metadata and verify the tags."""
        src_dir = REAL_DOWNLOADS_DIR
        if not src_dir.is_dir():
            pytest.skip(f"Real downloads dir not found: {src_dir}")

        # Find the first FLAC and copy it to a temp dir
        flac_files = sorted(p for p in src_dir.iterdir() if p.suffix.lower() == ".flac")
        if not flac_files:
            pytest.skip("No FLAC files in real downloads dir")

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            # Copy just one file to keep the test fast
            shutil.copy(str(flac_files[0]), str(dest / flac_files[0].name))

            tracks = [
                {"track_number": 1, "title": "Test Song", "isrc": "US-ABC-12-34567"},
            ]
            count = await tagger.tag_album(
                album_dir=dest,
                artist="Test Artist",
                album="Test Album",
                tracks=tracks,
                release_date="2024-01-15",
                label="Test Label",
                genre="Rock",
            )
            assert count == 1

            # Read back and verify
            tagged_path = dest / flac_files[0].name
            tags = _flac_tags(tagged_path)
            assert tags.get("ARTIST") == "Test Artist"
            assert tags.get("ALBUM") == "Test Album"
            assert tags.get("TITLE") == "Test Song"
            assert tags.get("TRACKNUMBER") == "1"
            assert tags.get("TRACKTOTAL") == "1"
            assert tags.get("ISRC") == "US-ABC-12-34567"
            assert tags.get("DATE") == "2024-01-15"
            assert tags.get("LABEL") == "Test Label"
            assert tags.get("GENRE") == "Rock"
            assert tags.get("ALBUMARTIST") == "Test Artist"

    @pytest.mark.asyncio
    async def test_tag_album_multi_track(self, tagger: TaggerService) -> None:
        """Tag multiple FLAC files and verify each gets correct track info."""
        src_dir = REAL_DOWNLOADS_DIR
        if not src_dir.is_dir():
            pytest.skip(f"Real downloads dir not found: {src_dir}")

        flac_files = sorted(p for p in src_dir.iterdir() if p.suffix.lower() == ".flac")
        if len(flac_files) < 3:
            pytest.skip("Need at least 3 FLAC files for multi-track test")

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            # Copy first 3 files
            for f in flac_files[:3]:
                shutil.copy(str(f), str(dest / f.name))

            tracks = [
                {"track_number": 1, "title": "Alpha", "isrc": "ISRC-001"},
                {"track_number": 2, "title": "Beta", "isrc": "ISRC-002"},
                {"track_number": 3, "title": "Gamma", "isrc": None},
            ]
            count = await tagger.tag_album(
                album_dir=dest,
                artist="Multi Artist",
                album="Multi Album",
                tracks=tracks,
            )
            assert count == 3

            # Check each file
            for f in sorted(dest.iterdir()):
                if f.suffix.lower() != ".flac":
                    continue
                track_num = TaggerService._parse_track_number(f.name)
                tags = _flac_tags(f)
                assert tags.get("ARTIST") == "Multi Artist"
                assert tags.get("ALBUM") == "Multi Album"
                assert tags.get("TRACKTOTAL") == "3"
                assert tags.get("TRACKNUMBER") == str(track_num)
                # Title should match the track map
                if track_num == 1:
                    assert tags.get("TITLE") == "Alpha"
                    assert tags.get("ISRC") == "ISRC-001"
                elif track_num == 2:
                    assert tags.get("TITLE") == "Beta"
                    assert tags.get("ISRC") == "ISRC-002"
                elif track_num == 3:
                    assert tags.get("TITLE") == "Gamma"
                    assert "ISRC" not in tags  # None → not written

    @pytest.mark.asyncio
    async def test_tag_album_cover_embedding(self, tagger: TaggerService) -> None:
        """Verify cover art is embedded when cover_data bytes are provided."""
        src_dir = REAL_DOWNLOADS_DIR
        if not src_dir.is_dir():
            pytest.skip(f"Real downloads dir not found: {src_dir}")

        flac_files = sorted(p for p in src_dir.iterdir() if p.suffix.lower() == ".flac")
        if not flac_files:
            pytest.skip("No FLAC files in real downloads dir")

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            shutil.copy(str(flac_files[0]), str(dest / flac_files[0].name))

            # Create a tiny valid JPEG (1x1 pixel)
            fake_jpeg = (
                b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01"
                b"\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07"
                b"\x07\x07\x09\x09\x08\x0a\x0c\x14\x0d\x0c\x0b\x0b\x0c\x19"
                b"\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c\x20\x24"
                b"\x2e\x27\x20\x22\x2c\x23\x1c\x1c\x28\x37\x29\x2c\x30\x31"
                b"\x34\x34\x34\x1f\x27\x39\x3d\x38\x32\x3c\x2e\x33\x34\x32"
                b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff"
                b"\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07"
                b"\x08\x09\x0a\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03"
                b"\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01\x7d\x01\x02\x03"
                b"\x00\x04\x11\x05\x12\x21\x31\x41\x06\x13\x51\x61\x07\x22"
                b"\x71\x14\x32\x81\x91\xa1\x08\x23\x42\xb1\xc1\x15\x52\xd1"
                b"\xf0\x24\x33\x62\x72\x82\x09\x0a\x16\x17\x18\x19\x1a\x25"
                b"\x26\x27\x28\x29\x2a\x34\x35\x36\x37\x38\x39\x3a\x43\x44"
                b"\x45\x46\x47\x48\x49\x4a\x53\x54\x55\x56\x57\x58\x59\x5a"
                b"\x63\x64\x65\x66\x67\x68\x69\x6a\x73\x74\x75\x76\x77\x78"
                b"\x79\x7a\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95"
                b"\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa"
                b"\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6"
                b"\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1"
                b"\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5"
                b"\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x0c\x03\x01\x00\x02\x11"
                b"\x03\x11\x00\x3f\x00\xf2\xfa\x28\xa2\x80\x3f\xff\xd9"
            )

            count = await tagger.tag_album(
                album_dir=dest,
                artist="Cover Artist",
                album="Cover Album",
                tracks=[{"track_number": 1, "title": "Covered"}],
                cover_data=fake_jpeg,
            )
            assert count == 1

            # Verify the picture block was embedded
            audio = FLAC(str(dest / flac_files[0].name))
            assert len(audio.pictures) == 1
            assert audio.pictures[0].type == 3  # Cover (front)
            assert audio.pictures[0].mime == "image/jpeg"

    @pytest.mark.asyncio
    async def test_tag_album_graceful_error_handling(self, tagger: TaggerService) -> None:
        """Tagging should continue even if some files fail.

        We test this by mixing a valid FLAC with a non-FLAC binary file
        that has a .flac extension — the tagger should skip the bad one.
        """
        src_dir = REAL_DOWNLOADS_DIR
        if not src_dir.is_dir():
            pytest.skip(f"Real downloads dir not found: {src_dir}")

        flac_files = sorted(p for p in src_dir.iterdir() if p.suffix.lower() == ".flac")
        if not flac_files:
            pytest.skip("No FLAC files in real downloads dir")

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            # Copy a real FLAC
            shutil.copy(str(flac_files[0]), str(dest / flac_files[0].name))
            # Create a fake "FLAC" file that isn't actually FLAC
            (dest / "99 - Bogus.flac").write_bytes(b"not a real flac file at all")

            count = await tagger.tag_album(
                album_dir=dest,
                artist="Error Artist",
                album="Error Album",
                tracks=[
                    {"track_number": 1, "title": "Valid"},
                    {"track_number": 99, "title": "Bogus"},
                ],
            )
            # The valid file should still be tagged; bogus skipped
            assert count >= 1

            # The valid file should have tags
            tags = _flac_tags(dest / flac_files[0].name)
            assert tags.get("ARTIST") == "Error Artist"


# ---------------------------------------------------------------------------
# Integration test — beets import after tagging
# ---------------------------------------------------------------------------


class TestTaggerBeetsIntegration:
    """Verify that beets can identify FLAC files after tagging."""

    @pytest.mark.asyncio
    async def test_beets_import_after_tagging(self) -> None:
        """Tag real untagged FLACs, then run beets import and verify success."""
        import asyncio

        src_dir = REAL_DOWNLOADS_DIR
        if not src_dir.is_dir():
            pytest.skip(f"Real downloads dir not found: {src_dir}")

        flac_files = sorted(p for p in src_dir.iterdir() if p.suffix.lower() == ".flac")
        if not flac_files:
            pytest.skip("No FLAC files in real downloads dir")

        # Use a temp directory to avoid modifying the real downloads
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            for f in flac_files:
                shutil.copy(str(f), str(dest / f.name))

            tagger = TaggerService()
            tracks = [
                {"track_number": i + 1, "title": f.stem.split(" - ", 1)[-1]}
                for i, f in enumerate(sorted(dest.iterdir()))
                if f.suffix.lower() == ".flac"
            ]

            count = await tagger.tag_album(
                album_dir=dest,
                artist="Bola",
                album="Fyuti",
                tracks=tracks,
                release_date="2001",
                genre="Electronic",
            )
            assert count == len(flac_files)

            # Now run beets import on the tagged files
            # Use a separate temp dir as the beets "library"
            with tempfile.TemporaryDirectory() as lib_tmp:
                # Create a minimal beets config for this test
                config_content = f"""\
directory: {lib_tmp}
library: {lib_tmp}/beets.db
import:
    copy: yes
    move: no
    write: yes
    quiet: yes
    timid: yes
    resume: ask
    incremental: no
    quiet_fallback: skip
    default_action: apply
clutter:
    - Thumbs.db
    - .DS_Store
    - '*.m3u'
    - '*.jpg'
    - '*.png'
    - '*.cue'
    - '*.log'
"""

                config_path = Path(lib_tmp) / "config.yaml"
                config_path.write_text(config_content)

                cmd = [
                    "beet", "import",
                    "-q",           # quiet (no interactive prompts)
                    "-l", str(config_path),
                    "-c",           # copy mode
                    str(dest),
                ]

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_bytes, stderr_bytes = await process.communicate()
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")

                # beets should NOT be "Skipping" the files — it should match
                assert "Skipping" not in stdout, (
                    f"beets is still skipping files after tagging:\n{stdout}"
                )
                assert "imported" in stdout.lower() or process.returncode == 0, (
                    f"beets import did not succeed:\n"
                    f"stdout: {stdout}\nstderr: {stderr}"
                )
