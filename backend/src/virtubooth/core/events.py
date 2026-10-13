"""In-process event bus for the admin live stream.

Services publish `(type, data)` after their transaction committed; the bus
numbers every event, keeps the last `history` events for replay, and fans them
out to the subscribers (one per open admin event stream). `publish()` is safe
from worker threads (sync endpoints).

Overflow: a subscriber that falls `queue_size` events behind is dropped and
marked `overflowed`; its next `get()` raises `Overflowed`, the stream ends, the
browser reconnects with `Last-Event-ID` and gets the missed events from the
history (or a resync signal when they are gone).

Sessions: a subscription belongs to an admin session. `end_session()` (logout)
closes all of that session's subscriptions at once: a waiting `get()` raises
`Closed` right away, so the stream ends and the browser's reconnect gets 401.
A session holds at most `per_session` subscriptions; opening one more closes
its oldest (a tab that went to sleep may hold a dead connection for a while).

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


class Closed(Exception):
    """The subscription was ended (its session logged out, or it was replaced)."""


class Overflowed(Closed):
    """The subscriber fell too far behind and was dropped."""


Resync = Literal["gap", "restart"]
_CURSOR_RE = re.compile(r"^([0-9a-f]{8})-(\d{1,18})$")


class Subscription:
    def __init__(self, queue_size: int, after: int | None, session: str | None = None) -> None:
        # None (never an event) only wakes a waiting get() when the subscription closes
        self.queue: asyncio.Queue[Event | None] = asyncio.Queue(queue_size)
        self.overflowed = False
        self.closed = False
        # the admin session (token hash) the stream belongs to
        self.session = session
        # live events at or before this id are already known to the client
        self.after = after
        # events the client missed before it subscribed (from the history)
        self.replay: list[Event] = []
        # the client's cursor can't be served from the history: refetch everything
        self.resync: Resync | None = None

    async def get(self) -> Event:
        if self.overflowed:
            raise Overflowed
        if self.closed:
            raise Closed
        item = await self.queue.get()
        if item is None or self.closed:
            raise Closed
        return item

    def close(self) -> None:
        """Call on the event loop. Ends the subscription; wakes a waiting get()."""
        if self.closed:
            return
        self.closed = True
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            pass  # a full queue means get() is not waiting; it sees `closed` next

    def qsize(self) -> int:
        return self.queue.qsize()


class EventBus:
    def __init__(self, queue_size: int = 256, history: int = 1024, per_session: int = 4) -> None:
        self.epoch = secrets.token_hex(4)
        # insertion-ordered (oldest first): a dict used as an ordered set
        self._subs: dict[Subscription, None] = {}
        self.per_session = per_session
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
                self._subs.pop(sub, None)

    def subscribe(
        self, after: int | Resync | None = None, *, session: str | None = None
    ) -> Subscription:
        """Call on the event loop. `after`: the id the client saw last;
        `session`: the admin session the stream belongs to (see end_session)."""
        if after == "gap" or after == "restart":
            sub = Subscription(self._queue_size, None, session)
            sub.resync = after
        elif after is None or after >= self._fanned_id:
            sub = Subscription(self._queue_size, after, session)
        else:
            sub = Subscription(self._queue_size, after, session)
            oldest = self._history[0]["id"] if self._history else self._fanned_id + 1
            if oldest <= after + 1:
                sub.replay = [e for e in self._history if e["id"] > after]
            else:
                sub.resync = "gap"
        if session is not None:
            mine = [s for s in self._subs if s.session == session]
            for old in mine[: max(0, len(mine) - self.per_session + 1)]:
                self._close(old)
        self._subs[sub] = None
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.pop(sub, None)

    def _close(self, sub: Subscription) -> None:
        self._subs.pop(sub, None)
        sub.close()

    def end_session(self, session: str) -> None:
        """Close every subscription of an admin session. Safe from any thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._end_session, session)

    def _end_session(self, session: str) -> None:
        for sub in [s for s in self._subs if s.session == session]:
            self._close(sub)

    def session_count(self, session: str) -> int:
        return sum(1 for s in self._subs if s.session == session)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
