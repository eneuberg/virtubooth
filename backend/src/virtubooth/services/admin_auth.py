"""Admin login. One shared password from VB_ADMIN_PASSWORD.

Sessions are random 256-bit tokens; the DB stores only their SHA-256. The
cookie is HttpOnly + SameSite=Strict, sessions expire after
VB_ADMIN_SESSION_HOURS and die when the password changes. Logging out ends the
session's open event streams at once.

Login attempts are rate limited per IP (IPv6: per /64) and globally: after
LOGIN_FAILURES_GLOBAL wrong passwords within LOGIN_FAILURES_WINDOW, every login
is refused for LOGIN_LOCK_SECONDS (429 `login_locked`), the right password
included, so distributed guessing gains nothing. That trades a few minutes of
admin-login denial during an attack for real brute-force protection: admins
who are logged in already keep working, requests straight from the server
itself (loopback, no proxy) are exempt, and a restart clears the lock (the
buckets live in memory).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ..core import errors
from ..core.clock import iso, now_iso
from ..core.security import admin_password_tag, constant_time_equals, sha256_hex
from ..db.database import Database
from ..repositories.container import Repositories

if TYPE_CHECKING:
    from ..runtime import Core

MAX_TOKEN_LENGTH = 128

log = logging.getLogger("virtubooth.auth")


def login_locked(retry_after: int) -> errors.ApiError:
    return errors.ApiError(
        429,
        "login_locked",
        "Zu viele Fehlversuche. Login ist kurz gesperrt.",
        headers={"Retry-After": str(max(1, retry_after))},
    )


@dataclass(frozen=True)
class Admin:
    session_hash: str

    @property
    def actor(self) -> str:
        """Name for the audit log."""
        return f"admin:{self.session_hash[:8]}"


class AdminAuthService:
    def __init__(self, core: Core, db: Database, repos: Repositories) -> None:
        self.core = core
        self.db = db
        self.repos = repos

    def login(self, password: str, *, ip: str, user_agent: str, local: bool = False) -> str:
        """A new session token, or an ApiError (429 rate_limited / login_locked,
        401 wrong_password). `local`: the request came straight from this
        machine (see `is_direct_loopback`); it is exempt from the global lock."""
        limits = self.core.limits
        if not local:
            remaining = limits.login_lock.remaining()
            if remaining:
                # not even compared: a lucky guess must not get through either
                raise login_locked(remaining)
        for limiter in (limits.login_ip, limits.login_ip_hourly):
            if not limiter.hit(ip):
                raise errors.rate_limited(limiter.retry_after(ip))

        settings = self.core.settings
        if not constant_time_equals(password, settings.admin_password.get_secret_value()):
            self.repos.audit.log("anonymous", "admin.login_failed", f"ip:{ip}", at=now_iso())
            if not local:
                failures = limits.login_failures_global
                failures.hit("global")
                if not failures.available("global"):
                    limits.login_lock.trip()
                    log.warning(
                        "admin login locked for %d s: too many wrong passwords "
                        "(%d within %d min, from any address)",
                        limits.login_lock.seconds,
                        failures.capacity,
                        round(failures.capacity / failures.refill / 60),
                    )
                    raise login_locked(limits.login_lock.remaining())
            raise errors.ApiError(401, "wrong_password", "Falsches Passwort.")

        token = secrets.token_urlsafe(32)
        token_hash = sha256_hex(token)
        now = datetime.now(UTC)
        with self.db.tx():
            self.repos.admin_sessions.create(
                token_hash,
                now=iso(now),
                expires_at=iso(now + timedelta(hours=settings.admin_session_hours)),
                pw_tag=admin_password_tag(settings, self.core.signer),
                ip=ip,
                user_agent=user_agent,
            )
            self.repos.audit.log(f"admin:{token_hash[:8]}", "admin.login", f"ip:{ip}", at=iso(now))
        return token

    def session(self, token: str | None) -> Admin | None:
        """The admin behind a session cookie: valid, unexpired, current password."""
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return None
        token_hash = sha256_hex(token)
        session = self.repos.admin_sessions.get(token_hash, now=now_iso())
        if session is None:
            return None
        tag = admin_password_tag(self.core.settings, self.core.signer)
        if not constant_time_equals(session.pw_tag, tag):
            return None
        return Admin(token_hash)

    def logout(self, admin: Admin) -> None:
        with self.db.tx():
            self.repos.admin_sessions.delete(admin.session_hash)
            self.repos.audit.log(admin.actor, "admin.logout", at=now_iso())
            # its open event streams end now, not at their next session check
            self.db.on_commit(lambda: self.core.bus.end_session(admin.session_hash))
