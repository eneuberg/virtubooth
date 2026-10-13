"""Who is on the party right now: first-party, aggregate statistics for the
host's dashboard (see domain/overview.py for what is counted).

- Every browser that opens a valid QR link gets a random visitor id in the
  `vb_vid` cookie (signed, HttpOnly, SameSite=Lax, Secure like the other
  cookies). Its row in `visitors` holds only that id, first and last seen and,
  once the browser joined, the guest it became. No IP, no user agent.
- Guest API requests refresh `users.last_seen_at` (joined guests) or the
  visitor's `last_seen_at` (not joined yet), at most once per device and
  THROTTLE_SECONDS, so a busy party does not turn into a write per request.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
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
