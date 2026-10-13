"""`GET /api/admin/events`: every admin event as Server-Sent Events.

Wire format: first `retry: 3000`, then per event `event: <type>`, `data: <json>`,
`id: <epoch>-<n>`; `: ping` after 15 s without events (FastAPI's keep-alive).

- The stream ends once the admin session is gone (logout, expiry, password
  change; checked at most every SESSION_RECHECK_SECONDS); the browser then
  reconnects, gets 401 and goes to the login page.
- It also ends when the client falls more than 256 events behind; the browser
  reconnects with `Last-Event-ID` and the missed events are replayed.
- Resuming: `Last-Event-ID` (sent by the browser on reconnects) or `?since=`
  (for the first connect: the `X-VB-Event-Id` header of the page's first API
  answer, so nothing between that fetch and the stream is lost). Events after
  that id are replayed; when they are no longer kept (or the server restarted),
  the stream starts with a `stream.resync` event: refetch everything.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Annotated

from anyio import to_thread
from fastapi import APIRouter, Header, Query, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from ....core.events import Event, EventBus, Overflowed, Resync
from ....runtime import Core
from ...deps import CoreDep, admin_from_cookie
from ...schemas.events import AdminEvent

router = APIRouter()

# an open event stream re-checks the admin session this often (logout, expiry)
SESSION_RECHECK_SECONDS = 30.0
# how long the browser waits before it reconnects
RETRY_MS = 3000
# the longest the stream sleeps between two session checks
_MAX_WAIT = 15.0


def sse_message(bus: EventBus, event: Event) -> ServerSentEvent:
    # json.dumps (not the model's compact JSON): the same text as before the overhaul
    return ServerSentEvent(
        raw_data=json.dumps(event["data"]), event=event["type"], id=bus.wire_id(event)
    )


def _resync(reason: Resync) -> ServerSentEvent:
    return ServerSentEvent(raw_data=json.dumps({"reason": reason}), event="stream.resync")


async def admin_event_stream(
    request: Request, core: Core, cursor: int | Resync | None
) -> AsyncIterator[ServerSentEvent]:
    bus = core.bus
    sub = bus.subscribe(cursor)
    try:
        yield ServerSentEvent(retry=RETRY_MS)
        if sub.resync is not None:
            yield _resync(sub.resync)
        for event in sub.replay:
            yield sse_message(bus, event)
        checked = time.monotonic()
        while True:
            recheck = SESSION_RECHECK_SECONDS
            try:
                item: Event | None = await asyncio.wait_for(
                    sub.get(), timeout=min(max(recheck, 1.0), _MAX_WAIT)
                )
            except TimeoutError:
                item = None
            except Overflowed:
                return  # the browser reconnects and catches up from the history
            now = time.monotonic()
            if now - checked >= recheck:
                checked = now
                if await to_thread.run_sync(admin_from_cookie, request, core) is None:
                    return
            if item is not None:
                yield sse_message(bus, item)
    finally:
        bus.unsubscribe(sub)


@router.get(
    "/events",
    response_class=EventSourceResponse,
    response_description="Server-Sent Events; each message's `data` is the event's `data`.",
)
async def events(
    request: Request,
    core: CoreDep,
    last_event_id: Annotated[str | None, Header(max_length=64)] = None,
    since: Annotated[
        str | None, Query(max_length=64, description="Resume after this event id.")
    ] = None,
) -> AsyncIterator[AdminEvent]:
    """The admin live stream (see the module docs for resuming and resync)."""
    cursor = core.bus.parse_cursor(last_event_id if last_event_id else since)
    async for message in admin_event_stream(request, core, cursor):
        # FastAPI writes ServerSentEvent items as they are; `AdminEvent` only
        # documents the messages (type, id, data) in the OpenAPI schema
        yield message  # type: ignore[misc]
