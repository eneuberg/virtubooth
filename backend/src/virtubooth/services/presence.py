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
  "active now". A visible beat less than BEAT_MIN_SECONDS after the guest's
  last written visible beat is skipped (HERE-01): the next written beat adds
  the time in between, so the online time stays exact. A browser that has
  not joined yet only refreshes its visitor (throttled). 300 guests are about
  5 writes a second.
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
# a visible heartbeat this soon after the last written one is not written
BEAT_MIN_SECONDS = 20.0
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
        # public id -> when its last visible beat was written (now())
        self._beats: dict[str, datetime] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ visitors

    def visitor_id(self, request: Request) -> str | None:
        """The browser's visitor id, if it carries a valid one."""
        return self.core.signer.unsign(_VISITOR_PURPOSE, request.cookies.get(VISITOR_COOKIE))

    def enter(
        self,
        request: Request,
        response: Response,
        *,
        user: User | None = None,
        code_id: int | None = None,
    ) -> str:
        """The browser opened the party (QR link, identify, join): give it a
        visitor id when it has none, note it as seen, and link it to `user`.
        `code_id`: it scanned that QR code (counted for the code)."""
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
        at = now_iso()
        self.repos.presence.visit(vid, at=at, user_id=user.id if user else None)
        if code_id is not None:
            self.repos.codes.record_visit(code_id, vid, at=at)
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
        `beat()`), skipped for a visible beat within BEAT_MIN_SECONDS of the
        last written one; then `note()` leaves the device alone for
        THROTTLE_SECONDS.
        Not joined yet: the visitor's last seen, throttled like `note()`."""
        public_id = self.core.signer.unsign("uid", request.cookies.get(UID_COOKIE))
        if public_id:
            now = self.now()
            if visible and not self._beat_due(public_id, now):
                return
            if self.repos.presence.beat(public_id, visible=visible, now=now):
                self._beat_written(public_id, now, visible=visible)
            self._remember(f"u:{public_id}")
            return
        vid = self.visitor_id(request)
        if vid and self._due(f"v:{vid}"):
            self.repos.presence.touch_visitor(vid, at=now_iso())

    def _beat_due(self, public_id: str, now: datetime) -> bool:
        """Whether a visible beat is worth a write: none was written within
        BEAT_MIN_SECONDS (on the beats' own clock, `now()`). A skipped beat
        loses nothing: `online_at` keeps the last written one, so the next
        write adds the whole time since."""
        with self._lock:
            last = self._beats.get(public_id)
        if last is None:
            return True
        elapsed = (now - last).total_seconds()
        # a clock that went backwards writes rather than skipping for long
        return not 0 <= elapsed < BEAT_MIN_SECONDS

    def _beat_written(self, public_id: str, now: datetime, *, visible: bool) -> None:
        with self._lock:
            if not visible:
                # the visit is closed; the next visible beat opens a new one
                self._beats.pop(public_id, None)
                return
            if len(self._beats) >= _MAX_REMEMBERED:
                self._beats = {
                    k: t
                    for k, t in self._beats.items()
                    if (now - t).total_seconds() < BEAT_MIN_SECONDS
                }
            self._beats[public_id] = now
