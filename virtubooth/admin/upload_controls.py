"""Upload controls, mounted into the admin router (/api/admin, admin session).

Three levels, independent of each other and of bans:

- stop all uploads for a while (every guest, existing and new):
  GET/POST /upload-stop {"enabled": bool}
- pause new guests: whoever joins while it is on starts with uploads paused.
  Turning it off needs a choice: restore the guests this pause period paused,
  or keep them paused: GET/POST /upload-pause {"enabled": bool, "restore": bool}
- pause or allow one guest: POST /users/{id}/uploads {"paused": bool}

Paused guests get 403 uploads_paused, everyone gets 403 uploads_stopped during
a stop. Their photos stay visible and they can still browse.

Events (only when something changed):
  settings.upload_stop    {"upload_stop": stop state}
  settings.upload_pause   {"upload_pause": pause state, "restored": [ids], "kept": [ids]}
  user.uploads_changed    {"users": [admin_view, ...], "paused": bool}
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel

from .. import errors
from ..context import Core
from ..deps import Admin, get_core, require_admin
from ..repo import User

MAX_ID = 2**62

# require_admin also comes with the admin router this one is mounted into
router = APIRouter(dependencies=[Depends(require_admin)])

UserId = Annotated[int, Path(ge=1, lt=MAX_ID)]


def stop_state(core: Core) -> dict[str, Any]:
    return core.repo.upload_stop()


def pause_state(core: Core) -> dict[str, Any]:
    """The new-guest lock plus how many guests it paused (`affected`, this
    period, still paused by it) and how many guests are paused at all."""
    lock = core.repo.upload_lock()
    affected = core.repo.count_paused_users(lock_period=lock["period"]) if lock["enabled"] else 0
    return lock | {"affected": affected, "paused_total": core.repo.count_paused_users()}


# ---------------------------------------------------------------- stop all


class StopIn(BaseModel):
    enabled: bool


@router.get("/upload-stop")
def get_upload_stop(core: Core = Depends(get_core)) -> dict[str, Any]:
    return stop_state(core)


@router.post("/upload-stop")
def set_upload_stop(
    body: StopIn, core: Core = Depends(get_core), admin: Admin = Depends(require_admin)
) -> dict[str, Any]:
    changed = core.repo.set_upload_stop(body.enabled, admin.actor)
    state = stop_state(core)
    if changed:
        core.bus.publish("settings.upload_stop", {"upload_stop": state})
    return state | {"changed": changed}


# ------------------------------------------------------- pause new guests


class PauseIn(BaseModel):
    enabled: bool
    # turning it off: True = unpause the guests this pause period paused,
    # False = they stay paused. Required then, so nobody picks by accident.
    restore: bool | None = None


@router.get("/upload-pause")
def get_upload_pause(core: Core = Depends(get_core)) -> dict[str, Any]:
    return pause_state(core)


@router.post("/upload-pause")
def set_upload_pause(
    body: PauseIn, core: Core = Depends(get_core), admin: Admin = Depends(require_admin)
) -> dict[str, Any]:
    restored: list[int] = []
    kept: list[int] = []
    if body.enabled:
        changed = core.repo.start_upload_lock(admin.actor)
    else:
        if body.restore is None:
            raise errors.bad_request(
                "Bitte wählen: die pausierten neuen Gäste freischalten oder pausiert lassen.",
                "restore_required",
            )
        result = core.repo.end_upload_lock(admin.actor, restore=body.restore)
        changed = result is not None
        if result is not None:
            restored, kept = result["restored"], result["kept"]
    state = pause_state(core)
    if changed:
        core.bus.publish(
            "settings.upload_pause", {"upload_pause": state, "restored": restored, "kept": kept}
        )
    if restored:
        users = [u for u in (core.repo.get_user(i) for i in restored) if u is not None]
        core.bus.publish(
            "user.uploads_changed", {"users": [u.admin_view() for u in users], "paused": False}
        )
    return state | {"changed": changed, "restored": len(restored), "kept": len(kept)}


# -------------------------------------------------------------- one guest


class UserUploadsIn(BaseModel):
    paused: bool


def _user_or_404(core: Core, user_id: int) -> User:
    user = core.repo.get_user(user_id)
    if user is None:
        raise errors.not_found("Gast nicht gefunden.")
    return user


@router.post("/users/{user_id}/uploads")
def set_user_uploads(
    user_id: UserId,
    body: UserUploadsIn,
    core: Core = Depends(get_core),
    admin: Admin = Depends(require_admin),
) -> dict[str, Any]:
    _user_or_404(core, user_id)
    changed = core.repo.set_uploads_paused(user_id, body.paused, admin.actor)
    user = _user_or_404(core, user_id)
    if changed:
        core.bus.publish(
            "user.uploads_changed", {"users": [user.admin_view()], "paused": body.paused}
        )
    return {"user": user.admin_view(), "changed": changed}
