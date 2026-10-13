"""Admin login, logout and session check (`/api/admin`, no session required)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ....core.errors import error_responses
from ....core.security import ADMIN_COOKIE, client_ip, is_direct_loopback, set_cookie
from ...deps import CoreDep, admin_from_cookie
from ...schemas.admin import LoginIn, OkOut, SessionOut

router = APIRouter(
    prefix="/api/admin", tags=["admin-auth"], responses=error_responses(403, 411, 413, 422, 429)
)


@router.post("/login", responses=error_responses(401))
def login(body: LoginIn, request: Request, response: Response, core: CoreDep) -> OkOut:
    """Sets the `vb_admin` session cookie (HttpOnly, SameSite=Strict).
    401 `wrong_password`; 429 `rate_limited` or `login_locked` with Retry-After."""
    token = core.services.admin_auth.login(
        body.password,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        local=is_direct_loopback(request),
    )
    set_cookie(
        response,
        request,
        core.settings,
        ADMIN_COOKIE,
        token,
        max_age=core.settings.admin_session_hours * 3600,
        samesite="strict",
    )
    return OkOut(ok=True)


@router.post("/logout")
def logout(request: Request, response: Response, core: CoreDep) -> OkOut:
    admin = admin_from_cookie(request, core)
    if admin is not None:
        core.services.admin_auth.logout(admin)
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return OkOut(ok=True)


@router.get("/session")
def session(request: Request, core: CoreDep) -> SessionOut:
    return SessionOut(authenticated=admin_from_cookie(request, core) is not None)
