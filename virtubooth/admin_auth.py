"""Admin login. One shared password from VB_ADMIN_PASSWORD.

Sessions are random 256-bit tokens; the DB stores only their SHA-256. The
cookie is HttpOnly + SameSite=Strict, sessions expire after
VB_ADMIN_SESSION_HOURS and die when the password changes. Login attempts are
rate limited per IP and globally.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import errors
from .context import Core
from .deps import admin_from_cookie, get_core
from .security import (
    ADMIN_COOKIE,
    admin_password_tag,
    client_ip,
    constant_time_equals,
    set_cookie,
    sha256_hex,
)

router = APIRouter(prefix="/api/admin")


class LoginIn(BaseModel):
    password: str = Field(max_length=256)


@router.post("/login")
def login(body: LoginIn, request: Request, core: Core = Depends(get_core)) -> JSONResponse:
    ip = client_ip(request)
    limits = core.limits
    for limiter in (limits.login_ip, limits.login_ip_hourly):
        if not limiter.hit(ip):
            raise errors.rate_limited(limiter.retry_after(ip))

    if not constant_time_equals(body.password, core.settings.admin_password):
        # The global budget slows down guessing spread over many IPs. It only
        # ever refuses wrong passwords: otherwise anyone could lock the real
        # admin out by failing 50 times. The password itself is long and random.
        limits.login_failures_global.hit("global")
        core.repo.audit("anonymous", "admin.login_failed", f"ip:{ip}")
        if not limits.login_failures_global.available("global"):
            raise errors.ApiError(
                429, "login_locked", "Zu viele Fehlversuche. Login ist kurz gesperrt."
            )
        raise errors.ApiError(401, "wrong_password", "Falsches Passwort.")

    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(hours=core.settings.admin_session_hours)
    token_hash = sha256_hex(token)
    core.repo.create_admin_session(
        token_hash,
        expires_at=expires.isoformat(timespec="milliseconds"),
        pw_tag=admin_password_tag(core.settings, core.signer),
        ip=ip,
        user_agent=request.headers.get("user-agent", ""),
    )
    core.repo.audit(f"admin:{token_hash[:8]}", "admin.login", f"ip:{ip}")
    response = JSONResponse({"ok": True})
    set_cookie(
        response,
        request,
        core.settings,
        ADMIN_COOKIE,
        token,
        max_age=core.settings.admin_session_hours * 3600,
        samesite="strict",
    )
    return response


@router.post("/logout")
def logout(request: Request, core: Core = Depends(get_core)) -> JSONResponse:
    admin = admin_from_cookie(request, core)
    if admin is not None:
        core.repo.delete_admin_session(admin.session_hash)
        core.repo.audit(admin.actor, "admin.logout")
    response = JSONResponse({"ok": True})
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return response


@router.get("/session")
def session(request: Request, core: Core = Depends(get_core)) -> dict[str, bool]:
    return {"authenticated": admin_from_cookie(request, core) is not None}
