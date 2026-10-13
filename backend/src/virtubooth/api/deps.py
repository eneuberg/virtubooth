"""FastAPI dependencies for access control. Use these in every route:

- `require_access` / `AccessDep`: the browser scanned a valid party QR code
  (see `has_access`)
- `GuestDep`: ... and accepted the join dialog and is not banned → `User`
  (banned → 403 "Dieses Gerät wurde für Uploads gesperrt.")
- `MeDep`: the same for everything that isn't an upload (banned → 403
  "Dieses Gerät ist gesperrt.")
- `AdminDep`: a valid admin session → `Admin`. Admin responses carry
  `X-VB-Event-Id` (the event stream cursor at the time of the request).
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request, Response

from ..core import errors
from ..core.security import ADMIN_COOKIE, UID_COOKIE
from ..domain.models import User
from ..runtime import Core
from ..services.admin_auth import Admin

EVENT_CURSOR_HEADER = "X-VB-Event-Id"


def get_core(request: Request) -> Core:
    return cast(Core, request.app.state.core)


CoreDep = Annotated[Core, Depends(get_core)]


def has_access(request: Request, core: Core) -> bool:
    """The browser may see the party (services/codes.py `access_state`):
    its access cookie is from an active QR code with its current token, or it
    is from a code revoked or re-tokened since and the browser is a joined
    guest (joined guests keep their session; anyone else must scan a valid
    code again)."""
    state = core.services.codes.access_state(request)
    if state == "current":
        return True
    return state == "stale" and guest_from_cookie(request, core) is not None


def guest_from_cookie(request: Request, core: Core) -> User | None:
    public_id = core.signer.unsign("uid", request.cookies.get(UID_COOKIE))
    return core.repos.users.get_by_public_id(public_id) if public_id else None


def admin_from_cookie(request: Request, core: Core) -> Admin | None:
    return core.services.admin_auth.session(request.cookies.get(ADMIN_COOKIE))


def require_access(request: Request, core: CoreDep) -> None:
    if not has_access(request, core):
        raise errors.scan_qr()
    # every guest API route passes here once per request: the dashboard's
    # "active now" (throttled to one write per device and minute)
    core.services.presence.note(request)


AccessDep = Depends(require_access)


def _consented(request: Request, core: Core) -> User:
    user = guest_from_cookie(request, core)
    if user is None:
        raise errors.needs_consent()
    return user


def require_guest(request: Request, core: CoreDep, _access: None = AccessDep) -> User:
    user = _consented(request, core)
    if user.banned:
        raise errors.banned()
    return user


def require_me(request: Request, core: CoreDep, _access: None = AccessDep) -> User:
    user = _consented(request, core)
    if user.banned:
        raise errors.device_banned()
    return user


def require_admin(request: Request, response: Response, core: CoreDep) -> Admin:
    admin = admin_from_cookie(request, core)
    if admin is None:
        raise errors.admin_required()
    # taken before the route reads anything: events after it are not in the answer
    response.headers[EVENT_CURSOR_HEADER] = core.bus.cursor()
    return admin


GuestDep = Annotated[User, Depends(require_guest)]
MeDep = Annotated[User, Depends(require_me)]
AdminDep = Annotated[Admin, Depends(require_admin)]
