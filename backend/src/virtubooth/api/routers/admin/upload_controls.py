"""Admin upload switches: stop all uploads, pause new guests (see services)."""

from __future__ import annotations

from fastapi import APIRouter

from ...deps import AdminDep, CoreDep
from ...schemas.admin import PauseIn, PauseOut, PauseState, StopIn, StopOut, StopState

router = APIRouter()


@router.get("/upload-stop")
def get_upload_stop(core: CoreDep) -> StopState:
    return core.services.upload_controls.stop_state()


@router.post("/upload-stop")
def set_upload_stop(body: StopIn, core: CoreDep, admin: AdminDep) -> StopOut:
    """Stop (or resume) all uploads. Per-guest pauses and the lock stay as they are."""
    state, changed = core.services.upload_controls.set_stop(body.enabled, actor=admin.actor)
    return StopOut(**state.model_dump(), changed=changed)


@router.get("/upload-pause")
def get_upload_pause(core: CoreDep) -> PauseState:
    return core.services.upload_controls.pause_state()


@router.post("/upload-pause")
def set_upload_pause(body: PauseIn, core: CoreDep, admin: AdminDep) -> PauseOut:
    """Pause new guests (a new lock period), or end the pause: `restore` true
    frees the guests this period paused, false keeps them paused (required)."""
    result = core.services.upload_controls.set_pause(
        body.enabled, restore=body.restore, actor=admin.actor
    )
    return PauseOut(
        **result.state.model_dump(),
        changed=result.changed,
        restored=len(result.restored),
        kept=len(result.kept),
    )
