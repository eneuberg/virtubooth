"""In-process event bus for the admin live stream.

Services publish `(type, data)` after their transaction committed; the bus
numbers every event, keeps the last `history` events for replay, and fans them
out to the subscribers (one per open admin event stream). `publish()` is safe
from worker threads (sync endpoints).

Overflow: a subscriber that falls `queue_size` events behind is dropped and
marked `overflowed`; its next `get()` raises `Overflowed`, the stream ends, the
browser reconnects with `Last-Event-ID` and gets the missed events from the
history (or a resync signal when they are gone).

Cursors: the wire id of an event is `<epoch>-<n>`. The epoch changes with every
process start, so a cursor from before a restart is recognised as stale.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import threading
from collections import deque
from typing import Any, Literal, TypedDict


class Event(TypedDict):
    id: int
    type: str
    data: dict[str, Any]


class Overflowed(Exception):
    """The subscriber fell too far behind and was dropped."""


Resync = Literal["gap", "restart"]
_CURSOR_RE = re.compile(r"^([0-9a-f]{8})-(\d{1,18})$")


class Subscription:
    def __init__(self, queue_size: int, after: int | None) -> None:
        self.queue: asyncio.Queue[Event] = asyncio.Queue(queue_size)
        self.overflowed = False
        # live events at or before this id are already known to the client
        self.after = after
        # events the client missed before it subscribed (from the history)
        self.replay: list[Event] = []
        # the client's cursor can't be served from the history: refetch everything
        self.resync: Resync | None = None

    async def get(self) -> Event:
        if self.overflowed:
            raise Overflowed
        return await self.queue.get()

    def qsize(self) -> int:
        return self.queue.qsize()


class EventBus:
    def __init__(self, queue_size: int = 256, history: int = 1024) -> None:
        self.epoch = secrets.token_hex(4)
        self._subs: set[Subscription] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._last_id = 0  # assigned (published)
        self._fanned_id = 0  # delivered to subscribers and the history
        self._history: deque[Event] = deque(maxlen=history)
        self._queue_size = queue_size

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def last_id(self) -> int:
        return self._last_id

    def cursor(self) -> str:
        """Wire id of the newest published event (`<epoch>-0` before the first)."""
        return f"{self.epoch}-{self._last_id}"

    def wire_id(self, event: Event) -> str:
        return f"{self.epoch}-{event['id']}"

    def parse_cursor(self, raw: str | None) -> int | Resync | None:
        """`<epoch>-<n>` from Last-Event-ID / ?last_event_id= → n; None when
        absent; "restart" when it belongs to another process (or is garbage)."""
        if raw is None or not raw.strip():
            return None
        match = _CURSOR_RE.match(raw.strip())
        if match is None or match.group(1) != self.epoch:
            return "restart"
        n = int(match.group(2))
        return n if n <= self._last_id else "restart"

    def publish(self, type_: str, data: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with self._lock:
            # numbering and scheduling under one lock: events fan out in id order
            self._last_id += 1
            event: Event = {"id": self._last_id, "type": type_, "data": data}
            loop.call_soon_threadsafe(self._fanout, event)

    def _fanout(self, event: Event) -> None:
        self._history.append(event)
        self._fanned_id = event["id"]
        for sub in list(self._subs):
            if sub.after is not None and event["id"] <= sub.after:
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # a stalled client must not hold memory forever; it reconnects
                # and catches up from the history
                sub.overflowed = True
                self._subs.discard(sub)

    def subscribe(self, after: int | Resync | None = None) -> Subscription:
        """Call on the event loop. `after`: the id the client saw last."""
        if after == "gap" or after == "restart":
            sub = Subscription(self._queue_size, None)
            sub.resync = after
        elif after is None or after >= self._fanned_id:
            sub = Subscription(self._queue_size, after)
        else:
            sub = Subscription(self._queue_size, after)
            oldest = self._history[0]["id"] if self._history else self._fanned_id + 1
            if oldest <= after + 1:
                sub.replay = [e for e in self._history if e["id"] > after]
            else:
                sub.resync = "gap"
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
