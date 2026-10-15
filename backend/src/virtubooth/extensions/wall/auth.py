"""Who may watch the wall (PLAN-WALL D4).

A wall screen logs in with the wall password (settings key `x.wall.password =
{hash, gen, changed_at, by}`) and gets the cookie `vb_wall` =
`signer.sign("wall", "<gen>.<issued unix>.<nonce>")` (cookies without the
nonce, from before it, stay valid): HttpOnly, SameSite=Strict, Path
`/livewall` (page, screen API and images; nothing else), 30 days. It is valid
while `gen` equals the stored generation, which grows whenever the password is
set, changed or removed and when the admin logs every wall out. A valid admin
session passes everywhere too.

Logins are limited per IP (IPv6: per /64) to 5 per minute and 20 per hour,
and globally like the admin login: after FAILURES_GLOBAL wrong passwords within
FAILURES_WINDOW, from any address, every wall login is refused for
LOCK_SECONDS (429 `login_locked`), the right password included, so spreading
guesses over many addresses gains nothing (the wall password may be as short
as 6 characters and opens every photo on the wall). Walls that are logged in
keep working, an admin session still passes, and a restart clears the lock.
Every wrong password is audited (`wall.login_failed`).
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, Request, Response

from ...api.deps import CoreDep, admin_from_cookie
from ...core import errors
from ...core.clock import now_iso
from ...core.passwords import verify_password
from ...core.ratelimit import IpRateLimiter, Lockout, RateLimiter, ip_bucket
from ...core.security import client_ip, cookie_secure
from ...repositories.app_settings import AppSettingsRepo
from .schemas import Via

if TYPE_CHECKING:
    from ...runtime import Core

log = logging.getLogger("virtubooth.wall")

COOKIE = "vb_wall"
COOKIE_PATH = "/livewall"
COOKIE_MAX_AGE = 30 * 24 * 3600
PASSWORD_KEY = "x.wall.password"
# the wall login is online: like the admin password, at least 12 characters
# (a password set before this rule keeps working; see docs/DEPLOY.md)
MIN_PASSWORD = 12
MAX_PASSWORD = 256
# a cookie "issued" this far in the future (clock skew) still counts
_FUTURE_SLACK = 300
_NONCE = re.compile(r"[0-9a-f]{8}")
NO_STORE = {"Cache-Control": "no-store"}
# wrong wall passwords from anywhere; running out locks every wall login
FAILURES_GLOBAL = 20
FAILURES_WINDOW = 15 * 60
LOCK_SECONDS = 5 * 60


# ------------------------------------------------------------------ errors


def login_required() -> errors.ApiError:
    return errors.ApiError(
        401, "wall_login_required", "Bitte das Live-Wall-Passwort eingeben.", headers=NO_STORE
    )


def no_password() -> errors.ApiError:
    return errors.ApiError(
        409,
        "wall_no_password",
        "Für die Live-Wall ist noch kein Passwort gesetzt. Setze es im Admin unter „Live-Wall“.",
        headers=NO_STORE,
    )


def wrong_password() -> errors.ApiError:
    return errors.ApiError(403, "wrong_password", "Das Passwort stimmt nicht.", headers=NO_STORE)


def login_locked(retry_after: int) -> errors.ApiError:
    return errors.ApiError(
        429,
        "login_locked",
        "Zu viele Fehlversuche. Die Anmeldung ist kurz gesperrt.",
        headers={"Retry-After": str(max(1, retry_after)), **NO_STORE},
    )


def password_too_short() -> errors.ApiError:
    return errors.ApiError(
        400,
        "wall_password_too_short",
        f"Das Passwort braucht mindestens {MIN_PASSWORD} Zeichen.",
    )


def rate_limited(retry_after: int) -> errors.ApiError:
    err = errors.rate_limited(retry_after)
    err.headers.update(NO_STORE)
    return err


# ------------------------------------------------------------ password row


@dataclass(frozen=True)
class PasswordState:
    hash: str | None
    gen: int
    changed_at: str | None
    by: str | None

    @property
    def is_set(self) -> bool:
        return bool(self.hash)

    def as_json(self) -> dict[str, Any]:
        return {"hash": self.hash, "gen": self.gen, "changed_at": self.changed_at, "by": self.by}


def password_state(repo: AppSettingsRepo) -> PasswordState:
    raw = repo.get(PASSWORD_KEY)
    gen = raw.get("gen")
    hash_ = raw.get("hash")
    return PasswordState(
        hash=hash_ if isinstance(hash_, str) and hash_ else None,
        gen=gen if isinstance(gen, int) else 0,
        changed_at=raw.get("changed_at"),
        by=raw.get("by"),
    )


def store_password_state(repo: AppSettingsRepo, state: PasswordState, *, at: str) -> None:
    repo.put(PASSWORD_KEY, state.as_json(), at=at)


# ------------------------------------------------------------------ cookie


def set_wall_cookie(response: Response, request: Request, core: Core, gen: int) -> None:
    # the nonce tells screens that logged in within the same second apart
    # (the stream cap counts per cookie); cookies without one stay valid
    value = core.signer.sign("wall", f"{gen}.{int(time.time())}.{secrets.token_hex(4)}")
    response.set_cookie(
        COOKIE,
        value,
        max_age=COOKIE_MAX_AGE,
        path=COOKIE_PATH,
        httponly=True,
        secure=cookie_secure(core.settings, request),
        samesite="strict",
    )


def clear_wall_cookie(response: Response, request: Request, core: Core) -> None:
    response.delete_cookie(
        COOKIE,
        path=COOKIE_PATH,
        httponly=True,
        secure=cookie_secure(core.settings, request),
        samesite="strict",
    )


def cookie_valid(core: Core, request: Request, state: PasswordState) -> bool:
    if not state.is_set:
        return False
    value = core.signer.unsign("wall", request.cookies.get(COOKIE))
    if value is None:
        return False
    parts = value.split(".")
    if len(parts) not in (2, 3) or (len(parts) == 3 and not _NONCE.fullmatch(parts[2])):
        return False
    try:
        gen, issued = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    age = time.time() - issued
    return gen == state.gen and -_FUTURE_SLACK <= age <= COOKIE_MAX_AGE


def wall_auth(request: Request, core: Core) -> Via | None:
    """How this request may watch the wall: its wall cookie, an admin session, or not."""
    if cookie_valid(core, request, password_state(core.repos.app_settings)):
        return "password"
    if admin_from_cookie(request, core) is not None:
        return "admin"
    return None


def require_wall(request: Request, core: CoreDep) -> Via:
    via = wall_auth(request, core)
    if via is None:
        raise login_required()
    return via


# the wall cookie or an admin session; else 401 `wall_login_required`
WallDep = Annotated[Via, Depends(require_wall)]


# ------------------------------------------------------------ screen limits

# the screen's GET routes, per wall cookie (else per address): generous for a
# TV (a feed refetch per reconnect, a few images a second), a ceiling for
# someone with a stolen cookie or a script
SCREEN_REQUESTS_PER_MIN = 120  # session, feed, categories, stream
MEDIA_REQUESTS_PER_MIN = 1200


@dataclass
class ScreenLimits:
    api: RateLimiter
    media: RateLimiter

    @classmethod
    def create(cls) -> ScreenLimits:
        return cls(
            api=RateLimiter(SCREEN_REQUESTS_PER_MIN, 60),
            media=RateLimiter(MEDIA_REQUESTS_PER_MIN, 60, burst=MEDIA_REQUESTS_PER_MIN // 2),
        )


def screen_key(core: Core, request: Request) -> str:
    """Whose budget a screen request uses: its wall cookie when the signature
    holds (no DB read), else its address (IPv6: the /64)."""
    cookie = request.cookies.get(COOKIE)
    if cookie and core.signer.unsign("wall", cookie) is not None:
        return "w:" + hashlib.sha256(cookie.encode()).hexdigest()[:32]
    return "ip:" + ip_bucket(client_ip(request))


# ------------------------------------------------------------------- login


@dataclass
class LoginLimits:
    per_minute: IpRateLimiter
    per_hour: IpRateLimiter
    # wrong passwords from any address; running out trips `lock`
    failures: RateLimiter
    lock: Lockout

    @classmethod
    def create(cls) -> LoginLimits:
        return cls(
            per_minute=IpRateLimiter(5, 60),
            per_hour=IpRateLimiter(20, 3600),
            failures=RateLimiter(FAILURES_GLOBAL, FAILURES_WINDOW),
            lock=Lockout(LOCK_SECONDS),
        )


def login(core: Core, limits: LoginLimits, request: Request, password: str) -> PasswordState:
    """The password state when `password` is right; else an ApiError (409 no
    password set, 429 `login_locked` / `rate_limited`, 403 wrong password)."""
    state = password_state(core.repos.app_settings)
    if not state.is_set:
        raise no_password()
    remaining = limits.lock.remaining()
    if remaining:
        # not even compared: a lucky guess must not get through either
        raise login_locked(remaining)
    ip = client_ip(request)
    for limiter in (limits.per_minute, limits.per_hour):
        if not limiter.hit(ip):
            raise rate_limited(limiter.retry_after(ip))
    if state.hash is None or not verify_password(password, state.hash):
        core.repos.audit.log("anonymous", "wall.login_failed", f"ip:{ip}", at=now_iso())
        limits.failures.hit("global")
        if not limits.failures.available("global"):
            limits.lock.trip()
            log.warning(
                "wall login locked for %d s: %d wrong passwords within %d min, from any address",
                LOCK_SECONDS,
                FAILURES_GLOBAL,
                FAILURES_WINDOW // 60,
            )
            raise login_locked(limits.lock.remaining())
        raise wrong_password()
    return state
