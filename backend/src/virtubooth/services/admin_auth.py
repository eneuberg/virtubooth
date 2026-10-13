"""Admin login. One shared password from VB_ADMIN_PASSWORD.

Sessions are random 256-bit tokens; the DB stores only their SHA-256. The
cookie is HttpOnly + SameSite=Strict, sessions expire after
VB_ADMIN_SESSION_HOURS and die when the password changes. Login attempts are
rate limited per IP and globally.
"""

from __future__ import annotations

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

    def login(self, password: str, *, ip: str, user_agent: str) -> str:
        """A new session token, or an ApiError (429 rate_limited / login_locked,
        401 wrong_password)."""
        limits = self.core.limits
        for limiter in (limits.login_ip, limits.login_ip_hourly):
            if not limiter.hit(ip):
                raise errors.rate_limited(limiter.retry_after(ip))

        settings = self.core.settings
        if not constant_time_equals(password, settings.admin_password.get_secret_value()):
            # The global budget slows down guessing spread over many IPs. It only
            # ever refuses wrong passwords: otherwise anyone could lock the real
            # admin out by failing 50 times. The password itself is long and random.
            failures = limits.login_failures_global
            failures.hit("global")
            self.repos.audit.log("anonymous", "admin.login_failed", f"ip:{ip}", at=now_iso())
            if not failures.available("global"):
                raise errors.ApiError(
                    429,
                    "login_locked",
                    "Zu viele Fehlversuche. Login ist kurz gesperrt.",
                    headers={"Retry-After": str(failures.retry_after("global"))},
                )
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
