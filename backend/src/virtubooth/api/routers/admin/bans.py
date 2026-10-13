"""Admin device (fingerprint) bans."""

from __future__ import annotations

from fastapi import APIRouter

from ...deps import AdminDep, CoreDep
from ...schemas.admin import DeviceBanOut, DeviceBansOut, DeviceUnbanOut
from ._params import FpHash

router = APIRouter()


@router.get("/device-bans")
def device_bans(core: CoreDep) -> DeviceBansOut:
    return DeviceBansOut(
        bans=[DeviceBanOut.of(b) for b in core.repos.read_models.device_bans()]
    )


@router.delete("/device-bans/{fp_hash}")
def lift_device_ban(fp_hash: FpHash, core: CoreDep, admin: AdminDep) -> DeviceUnbanOut:
    """Lift a device ban; the identities it auto-banned are released too."""
    released = core.services.moderation.lift_device_ban(fp_hash, actor=admin.actor)
    return DeviceUnbanOut(ok=True, fp_hash=fp_hash, users_unbanned=released)
