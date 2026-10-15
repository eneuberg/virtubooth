"""Allgemeines: the event name, the admin password and the public address
(`/api/admin/settings`).
Extensions add their own settings under `/api/admin/x/<id>/` (Extension.admin_router)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ....core.security import client_ip, is_direct_loopback
from ...deps import AdminDep, CoreDep
from ...schemas.host_settings import (
    AddressCheck,
    AdminSettingsOut,
    EventNameIn,
    EventSettingsOut,
    PasswordChangedOut,
    PasswordChangeIn,
    PublicAddress,
    PublicAddressIn,
)

router = APIRouter()


def _origin(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get("/settings")
def get_settings(request: Request, core: CoreDep) -> AdminSettingsOut:
    """The event name, where the admin password comes from, and the public
    address with its last check."""
    return core.services.host_settings.admin_settings(_origin(request))


@router.put("/settings/public-address")
def set_public_address(
    body: PublicAddressIn, request: Request, core: CoreDep, admin: AdminDep
) -> PublicAddress:
    """Set the public address (null or blank: VB_PUBLIC_BASE_URL, else
    automatic) and check it at once. 400 `invalid_public_address`. A failed
    check never blocks saving."""
    return core.services.host_settings.set_public_address(
        body.address, actor=admin.actor, origin=_origin(request)
    )


@router.post("/settings/public-address/check")
def check_public_address(core: CoreDep) -> AddressCheck:
    """Check the public address now: does `<address>/healthz` reach this server?"""
    return core.services.host_settings.check_public_address()


@router.put("/settings/event")
def set_event_name(body: EventNameIn, core: CoreDep, admin: AdminDep) -> EventSettingsOut:
    """Set the event name, or reset it to VB_PARTY_NAME (null or blank).
    400 `invalid_event_name`."""
    state, changed = core.services.host_settings.set_event_name(body.name, actor=admin.actor)
    return EventSettingsOut(**state.model_dump(), changed=changed)


@router.post("/settings/password")
def change_password(
    body: PasswordChangeIn, request: Request, core: CoreDep, admin: AdminDep
) -> PasswordChangedOut:
    """Change the admin password. This session stays, every other one ends.
    400 `password_too_short` / `password_unchanged`; 403 `wrong_password` (the
    current one is wrong); 429 `rate_limited` / `login_locked` (the login's limits)."""
    ended = core.services.admin_auth.change_password(
        admin,
        body.current,
        body.new,
        ip=client_ip(request),
        local=is_direct_loopback(request),
    )
    return PasswordChangedOut(ok=True, sessions_ended=ended)
