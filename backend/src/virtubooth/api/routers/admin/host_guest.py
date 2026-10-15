"""The admin guest: „Als Gast teilnehmen“. The admin session signs its own
browser in to the guest app as the party's one admin guest (`users.is_host`),
created on first use. No QR code and no party token are involved: the admin
session is the proof, and the admin guest needs no access cookie
(api/deps.py `has_access`)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ....core.errors import error_responses
from ....core.security import GUEST_COOKIE_MAX_AGE, client_ip, set_cookie, uid_cookie_name
from ...deps import AdminDep, CoreDep, guest_from_cookie
from ...schemas.admin import HostGuestOut, HostGuestState

router = APIRouter()

# the guest app's start page
GUEST_START_URL = "/"


@router.get("/guest")
def get_host_guest(request: Request, core: CoreDep) -> HostGuestState:
    """The admin guest (null until „Als Gast teilnehmen“ was pressed once) and
    whether this browser is signed in as it or as another guest."""
    host = core.repos.users.host()
    current = guest_from_cookie(request, core)
    is_host = current is not None and current.is_host
    return HostGuestState(
        user=core.services.views.user(host) if host else None,
        browser_is_host=is_host,
        browser_guest=current.name if current is not None and not is_host else None,
    )


@router.post("/guest", responses=error_responses(403))
def sign_in_host_guest(
    request: Request, response: Response, core: CoreDep, admin: AdminDep
) -> HostGuestOut:
    """Sign this browser in to the guest app as the admin guest (created on the
    first call, the same one on every later call). Sets the guest id cookie
    like a join; a different guest identity this browser had is replaced
    (`replaced`). Not affected by the join stop or the new-guest lock. Audited
    (`host_guest.sign_in`)."""
    result = core.services.identity.host_guest(
        guest_from_cookie(request, core),
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:300],
        actor=admin.actor,
    )
    token = core.signer.sign("uid", result.user.public_id)
    name = uid_cookie_name(core.settings, request)
    set_cookie(response, request, core.settings, name, token, max_age=GUEST_COOKIE_MAX_AGE)
    return HostGuestOut(
        user=core.services.views.user(result.user),
        created=result.created,
        url=GUEST_START_URL,
        replaced=result.previous.name if result.previous is not None else None,
    )
