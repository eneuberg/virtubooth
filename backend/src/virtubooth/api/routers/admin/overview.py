"""Admin overview data: stats, Instagram handles, audit log, extensions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ....domain.constants import MAX_ID
from ....domain.models import Photo, PhotoQuery
from ...deps import CoreDep
from ...schemas.admin import (
    AdminExtension,
    AdminExtensionsOut,
    AdminPhoto,
    AuditEntryOut,
    AuditOut,
    InstagramHandleOut,
    InstagramOut,
    InstagramUserOut,
    StatsOut,
)

router = APIRouter()

INSTAGRAM_PREVIEW = 8


@router.get("/stats")
def stats(core: CoreDep) -> StatsOut:
    return StatsOut.model_validate(core.repos.read_models.stats())


@router.get("/instagram")
def instagram(core: CoreDep) -> InstagramOut:
    """All handles, most active first, each with its newest visible photos."""
    handles: list[InstagramHandleOut] = []
    for entry in core.repos.read_models.instagram_handles():
        recent: list[Photo] = []
        for user in entry.users:
            if user.photos:
                recent += core.repos.photos.list(
                    PhotoQuery(user_id=user.id, hidden=False, limit=INSTAGRAM_PREVIEW)
                )
        recent.sort(key=lambda p: p.id, reverse=True)
        handles.append(
            InstagramHandleOut(
                handle=entry.handle,
                users=[InstagramUserOut.model_validate(u) for u in entry.users],
                photos=entry.photos,
                visible=entry.visible,
                hidden=entry.hidden,
                last_upload_at=entry.last_upload_at,
                recent=[AdminPhoto.of(p) for p in recent[:INSTAGRAM_PREVIEW]],
            )
        )
    return InstagramOut(handles=handles)


@router.get("/audit")
def audit(
    core: CoreDep,
    before: Annotated[int | None, Query(ge=1, lt=MAX_ID, description="next page: `next`")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> AuditOut:
    entries = core.repos.audit.page(before=before, limit=limit + 1)
    page = entries[:limit]
    return AuditOut(
        entries=[AuditEntryOut.model_validate(e) for e in page],
        next=page[-1].id if len(entries) > limit else None,
    )


@router.get("/extensions")
def extensions(core: CoreDep) -> AdminExtensionsOut:
    """Loaded extensions plus ids that only still exist in old photos."""
    result = [
        AdminExtension(
            id=e.id,
            title=e.title,
            emoji=e.emoji,
            tagline=e.tagline,
            url=e.url,
            uploads=e.upload is not None,
            meta_labels=dict(e.meta_labels),
            loaded=True,
        )
        for e in core.extensions.values()
    ]
    for ext_id in core.repos.read_models.extensions_with_photos():
        if ext_id not in core.extensions:
            result.append(
                AdminExtension(
                    id=ext_id,
                    title=ext_id,
                    emoji="📷",
                    tagline="",
                    url=None,
                    uploads=True,
                    meta_labels={},
                    loaded=False,
                )
            )
    return AdminExtensionsOut(extensions=result)
