"""Einstellungen: the event name and the admin password (`/api/admin/settings`).
Extensions add their own settings under `/api/admin/x/<id>/` (Extension.admin_router)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ....core.security import client_ip, is_direct_loopback
from ...deps import AdminDep, CoreDep
from ...schemas.host_settings import (
    AdminSettingsOut,
    EventNameIn,
    EventSettingsOut,
    PasswordChangedOut,
    PasswordChangeIn,
)

router = APIRouter()


@router.get("/settings")
def get_settings(core: CoreDep) -> AdminSettingsOut:
    """The event name and where the admin password comes from."""
    return core.services.host_settings.admin_settings()


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
