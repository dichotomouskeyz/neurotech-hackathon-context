"""Fan-out of validated frames to every connected browser."""

import asyncio
from collections import deque
from typing import Any


class Hub:
    """Broadcasts frames to subscribers and keeps a short history for late joiners.

    Each subscriber gets its own bounded queue. A slow browser loses its oldest
    frames instead of stalling producers or other browsers. The latest ``status``
    frame per source is kept outside the history so it never ages out.
    """

    def __init__(self, history: int = 2400, queue_size: int = 4800) -> None:
        self._history: deque[dict[str, Any]] = deque(maxlen=history)
        self._statuses: dict[str, dict[str, Any]] = {}
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def publish(self, frames: list[dict[str, Any]]) -> None:
        for frame in frames:
            if frame.get("type") == "status":
                self._statuses[frame["source"]] = frame
            else:
                self._history.append(frame)
        for queue in self._subscribers:
            for frame in frames:
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(frame)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._queue_size)
        for frame in [*self._statuses.values(), *self._history]:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(frame)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


async def drain(queue: asyncio.Queue[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wait for one frame, then take everything else already queued, as one batch."""
    batch = [await queue.get()]
    while not queue.empty():
        batch.append(queue.get_nowait())
    return batch
