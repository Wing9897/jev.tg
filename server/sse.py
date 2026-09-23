"""SSE fan-out for the filter stage."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sse_starlette.sse import EventSourceResponse

from server.util import camelize

logger = logging.getLogger(__name__)

_QUEUE_MAX = 512
_KEEPALIVE_SECONDS = 15
_MAX_SUBSCRIBERS = 16
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


class SseCapacityError(Exception):
    pass


@dataclass
class SseBroadcaster:
    _subscribers: set[asyncio.Queue] = field(default_factory=set)

    def subscribe(self) -> asyncio.Queue:
        if len(self._subscribers) >= _MAX_SUBSCRIBERS:
            raise SseCapacityError("SSE 訂閱已滿")
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        body = json.dumps({"type": event_type, "payload": camelize(payload)}, ensure_ascii=False)
        frame = {"event": event_type, "data": body, "retry": 2000}
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(frame)
                except Exception:
                    logger.warning("Dropping SSE event %s for a slow subscriber", event_type)


def event_stream(broadcaster: SseBroadcaster, request: Request, queue: asyncio.Queue) -> EventSourceResponse:
    async def generator() -> AsyncIterator[dict[str, Any]]:
        try:
            yield {"event": "ready", "data": json.dumps({"type": "ready", "payload": {}}, ensure_ascii=False), "retry": 2000}
            while True:
                if await request.is_disconnected():
                    return
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                    yield frame
                except TimeoutError:
                    yield {"comment": "keep-alive", "retry": 2000}
        finally:
            broadcaster.unsubscribe(queue)

    return EventSourceResponse(generator(), headers=_SSE_HEADERS)
