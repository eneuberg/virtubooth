"""The dashboard: the live overview and the join stop („Anmeldung stoppen“).
The upload stop it shows next to it is `upload_controls.py`."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from ....domain.overview import ACTIVE_MINUTES
from ...deps import AdminDep, CoreDep
from ...schemas.admin import StopIn, StopOut, StopState
from ...schemas.dashboard import (
    OverviewActivity,
    OverviewGuests,
    OverviewOut,
    OverviewPhotos,
    OverviewScans,
)

router = APIRouter()


@router.get("/overview")
def overview(core: CoreDep) -> OverviewOut:
    """Live counters: guests active and uploading now, scans and joins, photos
    in the last 15/60 minutes, per activity. Cheap; poll it every ~10 s."""
    data = core.repos.overview.overview()
    counts = {a.id: a for a in data.activities}
    activities = [
        OverviewActivity(
            id=e.id,
            title=e.title,
            photos=counts[e.id].photos if e.id in counts else 0,
            visible=counts[e.id].visible if e.id in counts else 0,
            last_60_min=counts[e.id].last_60_min if e.id in counts else 0,
        )
        for e in core.extensions.values()
        if e.upload is not None
    ]
    activities += [
        OverviewActivity(**asdict(a), title=a.id)
        for a in data.activities
        if a.id not in core.extensions
    ]
    return OverviewOut(
        at=data.at,
        active_minutes=ACTIVE_MINUTES,
        guests=OverviewGuests.model_validate(data.guests),
        scans=OverviewScans.model_validate(data.scans),
        photos=OverviewPhotos.model_validate(data.photos),
        activities=activities,
    )


@router.get("/join-stop")
def get_join_stop(core: CoreDep) -> StopState:
    return core.services.join_controls.state()


@router.post("/join-stop")
def set_join_stop(body: StopIn, core: CoreDep, admin: AdminDep) -> StopOut:
    """Stop (or reopen) joining: new devices get 403 `join_closed`. Guests who
    joined already are not affected."""
    state, changed = core.services.join_controls.set_stop(body.enabled, actor=admin.actor)
    return StopOut(**state.model_dump(), changed=changed)
