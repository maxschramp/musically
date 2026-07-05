"""Logs router — real-time log viewing endpoints.

GET  /api/logs         — tail N lines from service log files.
GET  /api/logs/stream  — SSE stream that polls log files for new lines.
"""

import asyncio
import os
import time
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

LOG_FILES: dict[str, str] = {
    "api": "/var/log/supervisor/api.log",
    "nginx": "/var/log/supervisor/nginx.log",
    "postgres": "/var/log/supervisor/postgres.log",
    "redis": "/var/log/supervisor/redis.log",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_last_lines(path: str, n: int) -> list[str]:
    """Read the last *n* lines from *path* efficiently (reverse-chunk read).

    Returns an empty list when the file does not exist or is not readable.
    """
    if n <= 0:
        return []

    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            if file_size == 0:
                return []

            # Read backwards in 8 KiB chunks
            chunk_size = 8192
            lines: list[bytes] = []
            pos = file_size

            while pos > 0 and len(lines) <= n:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)

                # Split on newlines; the first element may be a partial line
                # that belongs to the previous chunk
                if pos == 0:
                    # At the start of file — every split is a full line
                    lines = chunk.split(b"\n") + lines
                else:
                    parts = chunk.split(b"\n")
                    if lines:
                        # Prepend the last partial chunk to the first buffered line
                        parts[-1] = parts[-1] + lines[0]
                        lines = parts + lines[1:]
                    else:
                        lines = parts

            # Decode, strip CR from CRLF line endings, and trim trailing empty line
            decoded = [ln.decode("utf-8", errors="replace").rstrip("\r") for ln in lines]
            # Remove trailing empty string if file ends with newline
            if decoded and decoded[-1] == "":
                decoded.pop()
            return decoded[-n:]
    except (FileNotFoundError, PermissionError, OSError):
        return []


def _merge_all_logs(n: int) -> list[str]:
    """Read all known log files, merge by timestamp prefix, return last *n*."""
    all_lines: list[tuple[str, str]] = []  # (line, source_tag)
    for svc, path in LOG_FILES.items():
        for line in _read_last_lines(path, n):
            all_lines.append((line, svc))
    # Sort by the ISO-8601 timestamp prefix when present, else keep original order.
    # Lines without a recognisable timestamp sort after timestamped lines.
    def _sort_key(item: tuple[str, str]) -> str:
        line = item[0]
        # Typical log line: "2026-07-04 12:34:56 [...]"
        if len(line) >= 19 and line[4] == "-" and line[7] == "-" and line[10] == " ":
            return line[:19]
        return "z"  # push non-timestamped lines to end

    all_lines.sort(key=_sort_key)
    return [f"[{svc}] {ln}" for ln, svc in all_lines[-n:]]


# ---------------------------------------------------------------------------
# GET /api/logs
# ---------------------------------------------------------------------------


@router.get("/logs")
async def get_logs(
    service: str = Query("all", description="Service name or 'all'"),
    lines: int = Query(200, ge=1, le=2000, description="Number of lines to return"),
) -> dict[str, Any]:
    """Return the last *lines* lines from the requested service log(s)."""
    if service == "all":
        log_lines = await asyncio.to_thread(_merge_all_logs, lines)
    elif service in LOG_FILES:
        log_lines = await asyncio.to_thread(_read_last_lines, LOG_FILES[service], lines)
    else:
        log_lines = []

    return {
        "service": service,
        "lines": log_lines,
        "total_lines": len(log_lines),
    }


# ---------------------------------------------------------------------------
# GET /api/logs/stream  (Server-Sent Events)
# ---------------------------------------------------------------------------


@router.get("/logs/stream")
async def stream_logs(
    request: Request,
    service: str = Query("all", description="Service name or 'all'"),
) -> StreamingResponse:
    """SSE endpoint that tails log files, pushing new lines every 2 seconds."""

    async def generator() -> AsyncGenerator[str, None]:
        # Determine which files to watch
        paths: dict[str, str] = {}
        if service == "all":
            paths = dict(LOG_FILES)
        elif service in LOG_FILES:
            paths = {service: LOG_FILES[service]}
        else:
            # Unknown service — yield an error event and stop
            yield "event: error\ndata: Unknown service\n\n"
            return

        # Per-file state: (current_size, last_mtime)
        state: dict[str, tuple[int, float]] = {}

        def _init_state() -> None:
            for svc, path in paths.items():
                try:
                    st = os.stat(path)
                    state[svc] = (st.st_size, st.st_mtime)
                except FileNotFoundError:
                    state[svc] = (0, 0.0)

        _init_state()

        while True:
            # Check for client disconnect
            if await request.is_disconnected():
                break

            new_lines: list[str] = []

            for svc, path in paths.items():
                try:
                    st = os.stat(path)
                except FileNotFoundError:
                    state[svc] = (0, 0.0)
                    continue

                cur_size, cur_mtime = st.st_size, st.st_mtime
                prev_size, prev_mtime = state.get(svc, (0, 0.0))

                # Detect rotation: file truncated or replaced
                if cur_size < prev_size or cur_mtime > prev_mtime + 10:
                    # File was rotated/truncated — reset and read from start
                    prev_size = 0

                if cur_size > prev_size:
                    try:
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(prev_size)
                            chunk = f.read(cur_size - prev_size)
                            chunk_lines = chunk.split("\n")
                            # Drop trailing empty from final newline
                            if chunk_lines and chunk_lines[-1] == "":
                                chunk_lines.pop()
                            for ln in chunk_lines:
                                if service == "all":
                                    new_lines.append(f"[{svc}] {ln}")
                                else:
                                    new_lines.append(ln)
                    except (FileNotFoundError, PermissionError, OSError):
                        pass

                state[svc] = (cur_size, cur_mtime)

            for ln in new_lines:
                yield f"data: {ln}\n\n"

            # Flush periodic keep-alive even when no new lines
            if not new_lines:
                yield ": keepalive\n\n"

            await asyncio.sleep(2)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
