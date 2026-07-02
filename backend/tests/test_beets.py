"""Tests for the beets CLI service.

Mocks subprocess execution to avoid requiring actual beets installation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.beets import BeetsService, BeetsResult


@pytest.fixture
def beets_service() -> BeetsService:
    return BeetsService(config_path="/test/config.yaml")


# ---------------------------------------------------------------------------
# Successful import
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_album_success(beets_service: BeetsService) -> None:
    """Should return success when beets exits with code 0."""
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (
        b"importing 12 tracks\nAlbum: Test Artist - Test Album\n",
        b"",
    )
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await beets_service.import_album("/tmp/test_album")

        assert result.success is True
        assert result.files_imported == 12
        assert result.matched_album == "Test Artist - Test Album"
        assert result.errors == []

        # Verify correct command
        args = mock_exec.call_args[0]
        assert args[0] == "beet"
        assert "import" in args
        assert "-q" in args
        assert "-l" in args
        assert "/test/config.yaml" in args
        assert "-c" in args  # copy mode by default
        assert "/tmp/test_album" in args


@pytest.mark.asyncio
async def test_import_album_move_mode(beets_service: BeetsService) -> None:
    """Should pass -C (move) flag when move=True."""
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"imported 5 tracks\n", b"")
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        result = await beets_service.import_album("/tmp/test_album", move=True)

        assert result.success is True
        args = mock_exec.call_args[0]
        assert "-C" in args
        assert "-c" not in args


# ---------------------------------------------------------------------------
# Failed import
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_album_failure_nonzero_exit(beets_service: BeetsService) -> None:
    """Should return failure when beets exits with non-zero code."""
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (
        b"",
        b"Error: no music files found",
    )
    mock_process.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        result = await beets_service.import_album("/tmp/empty_dir")

        assert result.success is False
        assert "no music files found" in result.errors[0]
        assert result.files_imported == 0


@pytest.mark.asyncio
async def test_import_album_beets_not_installed(beets_service: BeetsService) -> None:
    """Should return failure when beets CLI is not found."""
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("beet not found")):
        result = await beets_service.import_album("/tmp/test_album")

        assert result.success is False
        assert any("not found in PATH" in e for e in result.errors)


@pytest.mark.asyncio
async def test_import_album_unexpected_error(beets_service: BeetsService) -> None:
    """Should handle unexpected exceptions gracefully."""
    with patch("asyncio.create_subprocess_exec", side_effect=OSError("disk full")):
        result = await beets_service.import_album("/tmp/test_album")

        assert result.success is False
        assert len(result.errors) > 0


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

def test_parse_imported_count_importing() -> None:
    assert BeetsService._parse_imported_count("importing 15 tracks") == 15


def test_parse_imported_count_imported() -> None:
    assert BeetsService._parse_imported_count("imported 3 items") == 3


def test_parse_imported_count_added_lines() -> None:
    stdout = "Added 1\nAdded 2\nAdded 3\nSome other text"
    assert BeetsService._parse_imported_count(stdout) == 3


def test_parse_imported_count_none() -> None:
    assert BeetsService._parse_imported_count("No matches found") == 0


def test_parse_matched_album_correcting() -> None:
    assert BeetsService._parse_matched_album("Correcting tags from: Artist - Album") == "Artist - Album"


def test_parse_matched_album_tagging() -> None:
    assert BeetsService._parse_matched_album("Tagging: Cool Band - Great Album") == "Cool Band - Great Album"


def test_parse_matched_album_none() -> None:
    assert BeetsService._parse_matched_album("some random output") is None


# ---------------------------------------------------------------------------
# BeetsResult dataclass
# ---------------------------------------------------------------------------

def test_beets_result_defaults() -> None:
    result = BeetsResult(success=True)
    assert result.matched_album is None
    assert result.files_imported == 0
    assert result.errors == []
    assert result.stdout == ""
    assert result.stderr == ""
