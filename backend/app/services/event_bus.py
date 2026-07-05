"""In-process async event bus for real-time SSE notifications.

Provides a simple publish/subscribe mechanism using asyncio.Queue.
Each connected SSE client gets its own queue; events published to the
bus are fanned out to all current subscribers.

Usage::

    from app.services.event_bus import event_bus

    # In an SSE endpoint:
    async for event in event_bus.subscribe():
        ...

    # In a mutation handler:
    event_bus.publish("queue_changed", {"album_id": "...", "action": "approved"})
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    """In-process async event bus.

    Maintains a set of subscriber queues.  ``publish()`` fans out to
    every queue; slow consumers are dropped to avoid back-pressure
    from blocking the producer.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any] | None]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self):
        """Subscribe to the event bus.

        Returns an async iterator that yields event dicts indefinitely.
        The iterator cleans up its queue automatically on unsubscribe
        (e.g. client disconnect).

        Each event is a ``dict`` with keys ``"type"`` (str) and ``"data"``
        (dict).
        """
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=256)

        async with self._lock:
            self._subscribers.add(queue)

        logger.debug("EventBus subscriber added (total=%d)", len(self._subscribers))

        try:
            while True:
                event = await queue.get()
                if event is None:  # sentinel to break out
                    break
                yield event
        except asyncio.CancelledError:
            logger.debug("EventBus subscriber cancelled")
        finally:
            async with self._lock:
                self._subscribers.discard(queue)
            # Drain the queue to avoid warnings about unretrieved items
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            logger.debug("EventBus subscriber removed (total=%d)", len(self._subscribers))

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish an event to all subscribers.

        Args:
            event_type: One of ``queue_changed``, ``album_status``,
                        ``download_progress``, ``task_completed``.
            data: Arbitrary JSON-serialisable payload dict.

        Slow subscribers (full queue) are silently skipped.
        """
        event = {"type": event_type, "data": data}
        logger.debug("EventBus publish: type=%s data=%s", event_type, data)

        # Snapshot subscribers under lock, then publish outside lock
        # to avoid holding the lock during queue.put().
        subs: list[asyncio.Queue[dict[str, Any] | None]] = []
        # We can't hold the lock for the snapshot because we're in a sync method
        # and _lock is async. Use a simple approach: iterate the set directly;
        # the set is only modified in subscribe()'s finally block which runs
        # in an async context. Since publish() is called from async code (or
        # sync code that doesn't hold the event loop), this is safe enough
        # for an in-process event bus.
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("EventBus: dropping event for slow subscriber")
                continue


# Module-level singleton instance
event_bus = EventBus()
