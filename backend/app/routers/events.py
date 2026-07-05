"""SSE (Server-Sent Events) endpoint for real-time updates.

Provides ``GET /api/events`` which streams state-change events to the
frontend as a ``text/event-stream`` response.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from app.services.event_bus import event_bus

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Stream real-time events via Server-Sent Events.

    Returns a ``text/event-stream`` response that streams events
    published to the internal event bus.  The stream terminates
    when the client disconnects.

    Event format (SSE)::

        event: queue_changed
        data: {"album_id":"...","action":"approved"}

    """
    async def event_generator():
        try:
            async for event in event_bus.subscribe():
                # Check if client is still connected
                if await request.is_disconnected():
                    logger.debug("SSE client disconnected")
                    break

                event_type = event["type"]
                data_str = json.dumps(event["data"], default=str)
                yield f"event: {event_type}\ndata: {data_str}\n\n"
        except asyncio.CancelledError:
            logger.debug("SSE stream cancelled")
        except Exception:
            logger.exception("SSE stream error")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering for SSE
        },
    )
