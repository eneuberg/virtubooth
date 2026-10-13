"""Guest API: identify the device, join, own handle and photos, the activity list."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from ...core.errors import error_responses
from ...core.security import GUEST_COOKIE_MAX_AGE, UID_COOKIE, client_ip, set_cookie
from ...domain.models import User
from ...runtime import Core
from ..deps import AccessDep, CoreDep, MeDep, guest_from_cookie
from ..schemas.guest import (
    ExtensionsOut,
    GuestPhoto,
    GuestUser,
    IdentifiedOut,
    IdentifyIn,
    IdentifyOut,
    JoinIn,
    JoinOut,
    MeIn,
    MeOut,
    MyPhotosOut,
    NeedsConsentOut,
    PublicExtension,
)

router = APIRouter(
    prefix="/api", tags=["guest"], responses=error_responses(403, 404, 411, 413, 422, 429)
)


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:300]


def _identified(request: Request, response: Response, core: Core, user: User) -> IdentifiedOut:
    """The device's identity, pinned with the signed `vb_uid` cookie."""
    token = core.signer.sign("uid", user.public_id)
    set_cookie(response, request, core.settings, UID_COOKIE, token, max_age=GUEST_COOKIE_MAX_AGE)
    identity = core.services.identity
    return IdentifiedOut(
        state="banned" if user.banned else "ok",
        user=GuestUser.of(user),
        uploads_stopped=identity.uploads_stopped(),
        uid_token=token,
        join_text=identity.consent_info(),
    )


@router.post("/identify", dependencies=[AccessDep], response_model=IdentifyOut)
def identify(
    body: IdentifyIn, request: Request, response: Response, core: CoreDep
) -> NeedsConsentOut | IdentifiedOut:
    """Called on every page load. Unknown device: the join dialog's text.
    Known device (cookie, or `uid` when the cookie is gone): its identity."""
    identity = core.services.identity
    user = identity.identify(
        guest_from_cookie(request, core),
        uid_token=body.uid,
        fp=body.fp,
        ip=client_ip(request),
        user_agent=_user_agent(request),
    )
    core.services.presence.enter(request, response, user=user)
    if user is None:
        return NeedsConsentOut(
            state="needs_consent",
            consent=identity.consent_info(),
            join_closed=core.services.join_controls.join_stopped(),
        )
    return _identified(request, response, core, user)


_JOIN_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": JoinOut, "description": "The device had joined already"},
    **error_responses(400, 409),
}


@router.post("/join", dependencies=[AccessDep], status_code=201, responses=_JOIN_RESPONSES)
def join(body: JoinIn, request: Request, response: Response, core: CoreDep) -> JoinOut:
    """Accept the join dialog: a new pseudonymous guest (201). A device that
    joined already keeps its identity (200, `already_joined`). While the host
    stopped joining, a new device gets 403 `join_closed`."""
    result = core.services.identity.join(
        guest_from_cookie(request, core),
        version=body.version,
        instagram=body.instagram,
        fp=body.fp,
        ip=client_ip(request),
        user_agent=_user_agent(request),
    )
    if not result.created:
        response.status_code = 200
    core.services.presence.enter(request, response, user=result.user)
    base = _identified(request, response, core, result.user)
    return JoinOut(
        **base.model_dump(),
        already_joined=not result.created,
        instagram_kept=result.instagram_kept,
    )


@router.patch("/me", responses=error_responses(400, 401))
def update_me(body: MeIn, user: MeDep, core: CoreDep) -> MeOut:
    """Set or clear (null/blank) the guest's Instagram handle. Paused guests may;
    banned ones get 403 `banned`."""
    updated = core.services.identity.set_instagram(user, body.instagram)
    return MeOut(user=GuestUser.of(updated))


@router.get("/me/photos", responses=error_responses(401))
def my_photos(user: MeDep, core: CoreDep) -> MyPhotosOut:
    """The guest's own photos that are still up (not hidden, not deleted),
    newest first, at most 60."""
    photos = core.services.identity.my_photos(user)
    return MyPhotosOut(photos=[GuestPhoto.of(p) for p in photos])


@router.get("/extensions", dependencies=[AccessDep])
def list_extensions(core: CoreDep) -> ExtensionsOut:
    """The activities on the start screen, in their configured order."""
    s = core.settings
    return ExtensionsOut(
        party_name=core.services.host_settings.event_name(),
        instagram_account=s.instagram_account,
        extensions=[
            PublicExtension(
                id=e.id,
                title=e.title,
                emoji=e.emoji,
                tagline=e.tagline,
                url=e.url,
                uploads=e.upload is not None,
            )
            for e in core.extensions.values()
            if e.show_on_home
        ],
    )
