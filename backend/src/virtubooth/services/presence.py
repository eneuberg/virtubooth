"""Who is on the party right now: first-party, aggregate statistics for the
host's dashboard (see domain/overview.py for what is counted).

- Every browser that opens a valid QR link gets a random visitor id in the
  `vb_vid` cookie (signed, HttpOnly, SameSite=Lax, Secure like the other
  cookies). Its row in `visitors` holds only that id, first and last seen and,
  once the browser joined, the guest it became. No IP, no user agent.
- Guest API requests refresh `users.last_seen_at` (joined guests) or the
  visitor's `last_seen_at` (not joined yet), at most once per device and
  THROTTLE_SECONDS, so a busy party does not turn into a write per request.
- The heartbeat (`POST /api/here`, `here()`): the guest page reports every
  minute while it is visible and once when it is hidden. For a joined guest
  each beat is one small UPDATE that adds up the online time and the visits
  (domain/overview.py) and refreshes `last_seen_at`, so an idle open page stays
  "active now". A browser that has not joined yet only refreshes its visitor
  (throttled). 300 guests are about 5 writes a second.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response

from ..core.clock import now_iso
from ..core.security import GUEST_COOKIE_MAX_AGE, UID_COOKIE, VISITOR_COOKIE, set_cookie
from ..domain.models import User
from ..repositories.container import Repositories

if TYPE_CHECKING:
    from ..runtime import Core

THROTTLE_SECONDS = 60.0
# the throttle remembers this many devices before it forgets the stale ones
_MAX_REMEMBERED = 5000
_VISITOR_PURPOSE = "vid"


class PresenceService:
    def __init__(
        self, core: Core, repos: Repositories, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.core = core
        self.repos = repos
        self.clock = clock
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ visitors

    def visitor_id(self, request: Request) -> str | None:
        """The browser's visitor id, if it carries a valid one."""
        return self.core.signer.unsign(_VISITOR_PURPOSE, request.cookies.get(VISITOR_COOKIE))

    def enter(self, request: Request, response: Response, *, user: User | None = None) -> str:
        """The browser opened the party (QR link, identify, join): give it a
        visitor id when it has none, note it as seen, and link it to `user`."""
        vid = self.visitor_id(request)
        if vid is None:
            vid = secrets.token_urlsafe(12)
            set_cookie(
                response,
                request,
                self.core.settings,
                VISITOR_COOKIE,
                self.core.signer.sign(_VISITOR_PURPOSE, vid),
                max_age=GUEST_COOKIE_MAX_AGE,
            )
        self.repos.presence.visit(vid, at=now_iso(), user_id=user.id if user else None)
        self._remember(f"v:{vid}")
        return vid

    # ------------------------------------------------------------ last seen

    def note(self, request: Request) -> None:
        """A guest API request: refresh the device's last-seen time (throttled)."""
        if request.url.path == "/api/here":
            return  # the heartbeat writes it itself, in its one UPDATE: here()
        public_id = self.core.signer.unsign("uid", request.cookies.get(UID_COOKIE))
        if public_id:
            if self._due(f"u:{public_id}"):
                self.repos.presence.touch_user(public_id, at=now_iso())
            return
        vid = self.visitor_id(request)
        if vid and self._due(f"v:{vid}"):
            self.repos.presence.touch_visitor(vid, at=now_iso())

    def _due(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < THROTTLE_SECONDS:
                return False
            if len(self._last) >= _MAX_REMEMBERED:
                self._last = {k: t for k, t in self._last.items() if now - t < THROTTLE_SECONDS}
            self._last[key] = now
            return True

    def _remember(self, key: str) -> None:
        with self._lock:
            self._last[key] = self.clock()

    # ------------------------------------------------------------ online time

    def now(self) -> datetime:
        """The wall-clock time of a beat (tests replace it on the instance)."""
        return datetime.now(UTC)

    def here(self, request: Request, *, visible: bool) -> None:
        """The guest page's heartbeat. A joined guest (signed `vb_uid` cookie):
        online time, visits and last seen in one write (repositories/presence.py
        `beat()`); then `note()` leaves the device alone for THROTTLE_SECONDS.
        Not joined yet: the visitor's last seen, throttled like `note()`."""
        public_id = self.core.signer.unsign("uid", request.cookies.get(UID_COOKIE))
        if public_id:
            self.repos.presence.beat(public_id, visible=visible, now=self.now())
            self._remember(f"u:{public_id}")
            return
        vid = self.visitor_id(request)
        if vid and self._due(f"v:{vid}"):
            self.repos.presence.touch_visitor(vid, at=now_iso())
