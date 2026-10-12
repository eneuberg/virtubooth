"""FastAPI dependencies for access control. Use these in every route:

- `require_access`: the browser scanned a valid party QR code
- `require_guest`: ... and accepted the consent banner and is not banned → `User`
- `optional_guest`: the identified guest or None (no consent/ban checks)
- `require_admin`: a valid admin session → `Admin`
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from . import errors
from .context import Core
from .repo import User
from .security import (
    ACCESS_COOKIE,
    ADMIN_COOKIE,
    UID_COOKIE,
    access_cookie_value,
    admin_password_tag,
    constant_time_equals,
    sha256_hex,
)


def get_core(request: Request) -> Core:
    return request.app.state.core


def has_access(request: Request, core: Core) -> bool:
    cookie = request.cookies.get(ACCESS_COOKIE)
    if not cookie:
        return False
    return constant_time_equals(cookie, access_cookie_value(core.settings, core.signer))


def guest_from_cookie(request: Request, core: Core) -> User | None:
    public_id = core.signer.unsign("uid", request.cookies.get(UID_COOKIE))
    return core.repo.get_user_by_public_id(public_id) if public_id else None


def require_access(request: Request, core: Core = Depends(get_core)) -> None:
    if not has_access(request, core):
        raise errors.scan_qr()


def optional_guest(request: Request, core: Core = Depends(get_core)) -> User | None:
    if not has_access(request, core):
        return None
    return guest_from_cookie(request, core)


def require_guest(
    request: Request,
    core: Core = Depends(get_core),
    _access: None = Depends(require_access),
) -> User:
    user = guest_from_cookie(request, core)
    if user is None:
        raise errors.needs_consent()
    if user.banned:
        raise errors.banned()
    return user


@dataclass(frozen=True)
class Admin:
    session_hash: str

    @property
    def actor(self) -> str:
        """Name for the audit log."""
        return f"admin:{self.session_hash[:8]}"


def admin_from_cookie(request: Request, core: Core) -> Admin | None:
    token = request.cookies.get(ADMIN_COOKIE)
    if not token or len(token) > 128:
        return None
    token_hash = sha256_hex(token)
    session = core.repo.get_admin_session(token_hash)
    if session is None:
        return None
    if not constant_time_equals(session["pw_tag"], admin_password_tag(core.settings, core.signer)):
        return None
    return Admin(token_hash)


def require_admin(request: Request, core: Core = Depends(get_core)) -> Admin:
    admin = admin_from_cookie(request, core)
    if admin is None:
        raise errors.admin_required()
    return admin
