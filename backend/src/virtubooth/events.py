"""In-process event bus plus a Server-Sent Events helper.

Core publishes: photo.created, photo.hidden, photo.unhidden, photo.deleted,
user.created, user.banned, user.unbanned, user.uploads_changed,
settings.upload_pause, settings.upload_stop. Payloads are small JSON dicts.
publish() is safe to call from worker threads (sync endpoints).
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any

from starlette.requests import Request
from starlette.responses import StreamingResponse

Event = dict[str, Any]


class EventBus:
    def __init__(self, queue_size: int = 256) -> None:
        self._subs: set[asyncio.Queue[Event]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ids = itertools.count(1)
        self._queue_size = queue_size

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, type_: str, data: dict[str, Any]) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        event = {"id": next(self._ids), "type": type_, "data": data}
        self._loop.call_soon_threadsafe(self._fanout, event)

    def _fanout(self, event: Event) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # a stalled client must not hold memory forever; it reconnects
                self._subs.discard(q)

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(self._queue_size)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self._subs.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)


def format_sse(event: Event) -> str:
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"


async def sse_stream(
    request: Request,
    bus: EventBus,
    *,
    types: Iterable[str] | None = None,
    transform: Callable[[Event], Event | None] | None = None,
    heartbeat: float = 15.0,
) -> AsyncIterator[str]:
    wanted = set(types) if types else None
    q = bus.subscribe()
    try:
        yield "retry: 3000\n\n"
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=heartbeat)
            except TimeoutError:
                if await request.is_disconnected():
                    return
                yield ": ping\n\n"
                continue
            if wanted is not None and event["type"] not in wanted:
                continue
            if transform is not None:
                event = transform(event)
                if event is None:
                    continue
            yield format_sse(event)
    finally:
        bus.unsubscribe(q)


def sse_response(
    request: Request,
    bus: EventBus,
    *,
    types: Iterable[str] | None = None,
    transform: Callable[[Event], Event | None] | None = None,
) -> StreamingResponse:
    """Stream bus events to the client. `transform` may rewrite or drop
    (return None) each event, e.g. to strip fields a viewer must not see."""
    return StreamingResponse(
        sse_stream(request, bus, types=types, transform=transform),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
