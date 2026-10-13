"""Admin login. One shared password: VB_ADMIN_PASSWORD, until the host changes it
in the admin (or `virtubooth reset-admin-password` sets one). From then on the
scrypt hash in the `settings` table (`admin.password`, core/passwords.py) is the
only valid password; `reset-admin-password --from-env` deletes it again.

Sessions are random 256-bit tokens; the DB stores only their SHA-256. The
cookie is HttpOnly + SameSite=Strict, sessions expire after
VB_ADMIN_SESSION_HOURS and die when the password changes: each stores a tag of
the password it logged in with (an HMAC of the stored hash, or of the env
password), and `session()` compares it with the current one, read from the DB on
every check, so a reset from the CLI (another process) applies at once.
Changing the password in the admin keeps the session that did it and ends every
other one, their event streams included. Logging out ends the session's open
event streams at once.

Login attempts are rate limited per IP (IPv6: per /64) and globally: after
LOGIN_FAILURES_GLOBAL wrong passwords within LOGIN_FAILURES_WINDOW, every login
is refused for LOGIN_LOCK_SECONDS (429 `login_locked`), the right password
included, so distributed guessing gains nothing. Changing the password shares
these limits: the current password it asks for is a login attempt too. That trades a few minutes of
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
from typing import TYPE_CHECKING, Literal

from ..core import errors
from ..core.clock import iso, now_iso
from ..core.passwords import MIN_LENGTH, hash_password, verify_password
from ..core.security import constant_time_equals, sha256_hex
from ..db.database import Database
from ..repositories.container import Repositories

if TYPE_CHECKING:
    from ..runtime import Core

MAX_TOKEN_LENGTH = 128

PasswordSource = Literal["env", "admin"]

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

    # -------------------------------------------------------------- password

    def password_source(self) -> PasswordSource:
        """`admin` when a hash is stored (VB_ADMIN_PASSWORD no longer logs in), else `env`."""
        return "admin" if self.repos.app_settings.admin_password() is not None else "env"

    def password_tag(self) -> str:
        """The tag sessions carry: changes whenever the valid password changes.
        Without a stored hash it is the tag of the env password, as before
        passwords could be changed, so existing sessions survive the update."""
        stored = self.repos.app_settings.admin_password()
        if stored is not None:
            return self._tag(stored.hash)
        return self._tag(self.core.settings.admin_password.get_secret_value())

    def _tag(self, secret: str) -> str:
        return self.core.signer.mac("admin-pw", secret)[:22]

    def _verify(self, password: str) -> bool:
        stored = self.repos.app_settings.admin_password()
        if stored is not None:
            return verify_password(password, stored.hash)
        return constant_time_equals(password, self.core.settings.admin_password.get_secret_value())

    # ---------------------------------------------------------------- limits

    def _check_limits(self, ip: str, *, local: bool) -> None:
        """Before a password is compared: the global lock (not for direct
        loopback requests), then the per-IP budgets."""
        limits = self.core.limits
        if not local:
            remaining = limits.login_lock.remaining()
            if remaining:
                # not even compared: a lucky guess must not get through either
                raise login_locked(remaining)
        for limiter in (limits.login_ip, limits.login_ip_hourly):
            if not limiter.hit(ip):
                raise errors.rate_limited(limiter.retry_after(ip))

    def _count_failure(self, *, local: bool) -> None:
        """A wrong password counts towards the global lock; raises 429
        `login_locked` when this one used up the budget."""
        if local:
            return
        limits = self.core.limits
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

    # ------------------------------------------------------------- sessions

    def login(self, password: str, *, ip: str, user_agent: str, local: bool = False) -> str:
        """A new session token, or an ApiError (429 rate_limited / login_locked,
        401 wrong_password). `local`: the request came straight from this
        machine (see `is_direct_loopback`); it is exempt from the global lock."""
        self._check_limits(ip, local=local)
        if not self._verify(password):
            self.repos.audit.log("anonymous", "admin.login_failed", f"ip:{ip}", at=now_iso())
            self._count_failure(local=local)
            raise errors.ApiError(401, "wrong_password", "Falsches Passwort.")

        settings = self.core.settings
        token = secrets.token_urlsafe(32)
        token_hash = sha256_hex(token)
        now = datetime.now(UTC)
        with self.db.tx():
            self.repos.admin_sessions.create(
                token_hash,
                now=iso(now),
                expires_at=iso(now + timedelta(hours=settings.admin_session_hours)),
                pw_tag=self.password_tag(),
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
        # read from the DB every time: a reset from the CLI applies at once
        if not constant_time_equals(session.pw_tag, self.password_tag()):
            return None
        return Admin(token_hash)

    def logout(self, admin: Admin) -> None:
        with self.db.tx():
            self.repos.admin_sessions.delete(admin.session_hash)
            self.repos.audit.log(admin.actor, "admin.logout", at=now_iso())
            # its open event streams end now, not at their next session check
            self.db.on_commit(lambda: self.core.bus.end_session(admin.session_hash))

    def change_password(
        self, admin: Admin, current: str, new: str, *, ip: str, local: bool = False
    ) -> int:
        """Store `new` as the admin password; returns how many other sessions
        ended. The admin's own session stays valid.

        400 `password_too_short` / `password_unchanged`; with the login's limits
        (429 `rate_limited` / `login_locked`), a wrong `current` is 403
        `wrong_password` (not 401: the admin UI reads 401 as "logged out") and
        counts towards the global lock like a failed login."""
        if len(new) < MIN_LENGTH:
            raise errors.bad_request(
                "Das neue Passwort braucht mindestens 12 Zeichen.", "password_too_short"
            )
        # both come from the client: nothing secret to time
        if new == current:
            raise errors.bad_request(
                "Das neue Passwort ist dasselbe wie das alte.", "password_unchanged"
            )
        self._check_limits(ip, local=local)
        if not self._verify(current):
            self.repos.audit.log(
                admin.actor, "admin.password_change_failed", f"ip:{ip}", at=now_iso()
            )
            self._count_failure(local=local)
            raise errors.ApiError(403, "wrong_password", "Das aktuelle Passwort stimmt nicht.")

        encoded = hash_password(new)  # slow: outside the transaction
        at = now_iso()
        with self.db.tx():
            self.repos.app_settings.put_admin_password(encoded, by=admin.actor, at=at)
            self.repos.admin_sessions.update_tag(admin.session_hash, self._tag(encoded))
            ended = self.repos.admin_sessions.delete_others(admin.session_hash, now=at)
            self.repos.audit.log(
                admin.actor, "admin.password_change", details={"sessions_ended": len(ended)}, at=at
            )
            bus = self.core.bus

            def end_streams() -> None:
                # their open event streams end now, not at their next session check
                for session_hash in ended:
                    bus.end_session(session_hash)

            self.db.on_commit(end_streams)
        return len(ended)
