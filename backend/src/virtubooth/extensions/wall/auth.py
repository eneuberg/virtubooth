"""Who may watch the wall (PLAN-WALL D4).

A wall screen logs in with the wall password (settings key `x.wall.password =
{hash, gen, changed_at, by}`) and gets the cookie `vb_wall` =
`signer.sign("wall", "<gen>.<issued unix>")`: HttpOnly, SameSite=Strict, Path
`/livewall` (page, screen API and images; nothing else), 30 days. It is valid
while `gen` equals the stored generation, which grows whenever the password is
set, changed or removed and when the admin logs every wall out. A valid admin
session passes everywhere too.

Logins are limited per IP (IPv6: per /64) to 5 per minute and 20 per hour;
every wrong password is audited (`wall.login_failed`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, Request, Response

from ...api.deps import CoreDep, admin_from_cookie
from ...core import errors
from ...core.clock import now_iso
from ...core.ratelimit import IpRateLimiter
from ...core.security import client_ip, cookie_secure
from ...repositories.app_settings import AppSettingsRepo
from ...core.passwords import verify_password
from .schemas import Via

if TYPE_CHECKING:
    from ...runtime import Core

COOKIE = "vb_wall"
COOKIE_PATH = "/livewall"
COOKIE_MAX_AGE = 30 * 24 * 3600
PASSWORD_KEY = "x.wall.password"
MIN_PASSWORD = 6
MAX_PASSWORD = 256
# a cookie "issued" this far in the future (clock skew) still counts
_FUTURE_SLACK = 300
NO_STORE = {"Cache-Control": "no-store"}


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


def password_too_short() -> errors.ApiError:
    return errors.ApiError(
        400, "wall_password_too_short", "Das Passwort braucht mindestens 6 Zeichen."
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
    value = core.signer.sign("wall", f"{gen}.{int(time.time())}")
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
    gen_text, _, issued_text = value.partition(".")
    try:
        gen, issued = int(gen_text), int(issued_text)
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


# ------------------------------------------------------------------- login


@dataclass
class LoginLimits:
    per_minute: IpRateLimiter
    per_hour: IpRateLimiter

    @classmethod
    def create(cls) -> LoginLimits:
        return cls(per_minute=IpRateLimiter(5, 60), per_hour=IpRateLimiter(20, 3600))


def login(core: Core, limits: LoginLimits, request: Request, password: str) -> PasswordState:
    """The password state when `password` is right; else an ApiError (409 no
    password set, 429 too many attempts, 403 wrong password)."""
    state = password_state(core.repos.app_settings)
    if not state.is_set:
        raise no_password()
    ip = client_ip(request)
    for limiter in (limits.per_minute, limits.per_hour):
        if not limiter.hit(ip):
            raise rate_limited(limiter.retry_after(ip))
    if state.hash is None or not verify_password(password, state.hash):
        core.repos.audit.log("anonymous", "wall.login_failed", f"ip:{ip}", at=now_iso())
        raise wrong_password()
    return state
