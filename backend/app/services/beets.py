"""Beets CLI service — async subprocess wrapper for tagging and importing music."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BeetsResult:
    """Result of a beets import operation."""
    success: bool
    matched_album: str | None = None  # "Artist - Album" as matched by beets
    files_imported: int = 0
    errors: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


class BeetsService:
    """Service for tagging and importing music via the beets CLI.

    Runs `beet import` as an async subprocess. Beets must be installed and
    available in PATH on the system (installed via apt in the Docker image).

    The beets config directory (containing config.yaml and library.db) is
    set via the ``BEETSDIR`` environment variable so subprocess calls pick
    up the correct configuration.
    """

    def __init__(self, config_path: str = "/config/beets/config.yaml") -> None:
        # config_path is the path to config.yaml; the directory containing
        # it is used as BEETSDIR so beets finds both config.yaml and library.db.
        import os
        from pathlib import Path

        self.config_path = config_path
        self.beets_dir = str(Path(config_path).parent)
        # Ensure BEETSDIR is set for subprocess calls
        os.environ.setdefault("BEETSDIR", self.beets_dir)

    async def import_album(
        self,
        source_dir: str,
        dest_base: str = "/music/library",
        move: bool = False,
    ) -> BeetsResult:
        """Import and tag an album using beets.

        Flags:
          -q   = quiet (no interactive prompts)
          -c   = copy (never move, safer for NAS)
          -C   = do not copy; move files (set move=True for this)

        The library database path is read from the beets config file
        (set via the BEETSDIR environment variable).

        Args:
            source_dir: Path to the directory containing FLAC files to import.
            dest_base: Base library directory (informational, not passed to beets).
            move: If True, use -C (move). Default is -c (copy, safer for NAS).

        Returns:
            BeetsResult with success status, matched album name, and any errors.
        """
        cmd = ["beet", "import", "-q"]

        if move:
            cmd.append("-C")  # move mode
        else:
            cmd.append("-c")  # copy mode (safer)

        cmd.append(source_dir)

        logger.info("Running beets import: %s", " ".join(cmd))

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await process.communicate()

            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

            logger.debug("beets stdout: %s", stdout[:500])
            if stderr:
                logger.debug("beets stderr: %s", stderr[:500])

            if process.returncode != 0:
                error_msg = stderr or stdout or f"beets exited with code {process.returncode}"
                logger.warning(
                    "beets import FAILED (rc=%d): %s",
                    process.returncode,
                    error_msg[:500],
                )
                return BeetsResult(
                    success=False,
                    files_imported=0,
                    errors=[error_msg],
                    stdout=stdout,
                    stderr=stderr,
                )

            # Parse output for "importing X tracks" or similar success indicator
            files_imported = self._parse_imported_count(stdout)
            matched_album = self._parse_matched_album(stdout)

            return BeetsResult(
                success=True,
                matched_album=matched_album,
                files_imported=files_imported,
                errors=[],
                stdout=stdout,
                stderr=stderr,
            )

        except FileNotFoundError:
            error_msg = "beets CLI not found in PATH. Is beets installed?"
            logger.error(error_msg)
            return BeetsResult(success=False, errors=[error_msg])
        except Exception:
            logger.exception("beets import failed with unexpected error")
            return BeetsResult(
                success=False,
                errors=["Unexpected error during beets import"],
            )

    @staticmethod
    def _parse_imported_count(stdout: str) -> int:
        """Parse the number of imported files from beets output.

        Looks for patterns like:
          - "importing 12 tracks"
          - "(12 items)" or similar
        """
        m = re.search(r"import(?:ed|ing)\s+(\d+)\s+(?:track|item|file)s?", stdout, re.IGNORECASE)
        if m:
            return int(m.group(1))

        # Fallback: count "Added" lines
        added_count = len(re.findall(r"^\s*Added", stdout, re.MULTILINE))
        if added_count > 0:
            return added_count

        return 0

    @staticmethod
    def _parse_matched_album(stdout: str) -> str | None:
        """Parse the matched album name from beets output.

        Looks for patterns like:
          - "Correcting tags from: Artist — Album"
          - "Tagging: Artist - Album"
          - "match: Artist - Album"
        """
        patterns = [
            r"(?:Correcting tags from|Tagging|match):\s*(.+)",
            r"Album:\s*(.+)",
        ]
        for pat in patterns:
            m = re.search(pat, stdout, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

