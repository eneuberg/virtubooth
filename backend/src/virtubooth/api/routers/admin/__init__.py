"""The admin API, mounted at /api/admin. Every route requires an admin session
(`require_admin`, which also adds `X-VB-Event-Id`); mutations need the CSRF
origin check (middleware). Login/logout/session are in `auth.py`, outside it.

Photos are addressed by their public id, users by their numeric id. Every
mutation goes through a service with the admin's actor name (audit log) and
publishes events so every open admin screen stays in sync.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ....core.errors import error_responses
from ...deps import require_admin
from . import (
    bans,
    codes,
    dashboard,
    events,
    exports,
    host_settings,
    instagram,
    overview,
    photos,
    theme,
    upload_controls,
    users,
)
from ._params import ADMIN_ERROR_STATUSES

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
    responses=error_responses(*ADMIN_ERROR_STATUSES),
)
router.include_router(codes.router)
for _module in (
    photos, users, bans, overview, events, upload_controls, exports, instagram, dashboard,
):  # fmt: skip
    router.include_router(_module.router)
router.include_router(host_settings.router)
router.include_router(theme.router)
