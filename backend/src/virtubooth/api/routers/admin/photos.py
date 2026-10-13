"""Admin photos: list (paged, filtered), get, hide, unhide, delete, bulk."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ....core import errors
from ....domain.constants import EXT_ID_RE, MAX_ID, PHOTO_ID_RE
from ....domain.models import PhotoQuery
from ....runtime import Core
from ...deps import AdminDep, CoreDep
from ...schemas.admin import (
    AdminPhoto,
    BulkIn,
    BulkOut,
    DeletePhotoOut,
    PhotoChangeOut,
    PhotoListOut,
    PhotoOut,
)
from ._params import PhotoId, blank, parse_hidden

router = APIRouter()


def _cursor(core: Core, raw: str | None) -> int | None:
    value = blank(raw)
    if value is None:
        return None
    if not PHOTO_ID_RE.fullmatch(value):
        raise errors.bad_request("Unbekannter Cursor.", "invalid_cursor")
    internal = core.repos.photos.internal_id(value)
    if internal is None:
        raise errors.bad_request("Unbekannter Cursor.", "invalid_cursor")
    return internal


def _photo_not_found() -> errors.ApiError:
    return errors.not_found("Foto nicht gefunden.")


@router.get("/photos", response_model_exclude_unset=True)
def list_photos(
    core: CoreDep,
    extension: Annotated[str | None, Query(max_length=40)] = None,
    hidden: Annotated[
        str | None, Query(max_length=10, description="all | true/hidden | false/visible")
    ] = None,
    user_id: Annotated[str | None, Query(max_length=20)] = None,
    before: Annotated[str | None, Query(max_length=40, description="next page: `next`")] = None,
    after: Annotated[str | None, Query(max_length=40, description="poll: newest known id")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PhotoListOut:
    """Newest first. Page with `before=<next>`; poll for news with `after=<newest id>`."""
    ext = blank(extension)
    if ext is not None and not EXT_ID_RE.fullmatch(ext):
        raise errors.bad_request("Ungültige Aktivität.", "invalid_filter")
    uid: int | None = None
    raw_uid = blank(user_id)
    if raw_uid is not None:
        try:
            uid = int(raw_uid)
        except ValueError as exc:
            raise errors.bad_request("Ungültige Gast-ID.", "invalid_filter") from exc
        if not 1 <= uid < MAX_ID:
            raise errors.bad_request("Ungültige Gast-ID.", "invalid_filter")
    before_id, after_id = _cursor(core, before), _cursor(core, after)
    hidden_filter = parse_hidden(hidden)

    photos = core.repos.photos.list(
        PhotoQuery(
            extension=ext,
            user_id=uid,
            hidden=hidden_filter,
            before_id=before_id,
            after_id=after_id,
            limit=limit + 1,  # one more: is there a next page?
        )
    )
    page = photos[:limit]
    next_id = page[-1].public_id if len(photos) > limit else None
    views = [AdminPhoto.of(p) for p in page]
    if before_id is None and after_id is None:
        total = core.repos.photos.count(ext, user_id=uid, hidden=hidden_filter)
        return PhotoListOut(photos=views, next=next_id, total=total)
    return PhotoListOut(photos=views, next=next_id)


@router.get("/photos/{photo_id}")
def get_photo(photo_id: PhotoId, core: CoreDep) -> PhotoOut:
    photo = core.repos.photos.get(photo_id)
    if photo is None:
        raise _photo_not_found()
    return PhotoOut(photo=AdminPhoto.of(photo))


@router.post("/photos/{photo_id}/hide")
def hide_photo(photo_id: PhotoId, core: CoreDep, admin: AdminDep) -> PhotoChangeOut:
    """Take a photo down (idempotent: `changed` false when it already was)."""
    if core.repos.photos.get(photo_id) is None:
        raise _photo_not_found()
    result = core.services.moderation.hide_photo(photo_id, actor=admin.actor)
    if result.photo is None:
        raise _photo_not_found()
    return PhotoChangeOut(photo=AdminPhoto.of(result.photo), changed=result.changed)


@router.post("/photos/{photo_id}/unhide")
def unhide_photo(photo_id: PhotoId, core: CoreDep, admin: AdminDep) -> PhotoChangeOut:
    """Put a photo back up; also one a ban hid (the guest stays banned)."""
    if core.repos.photos.get(photo_id) is None:
        raise _photo_not_found()
    result = core.services.moderation.unhide_photo(photo_id, actor=admin.actor)
    if result.photo is None:
        raise _photo_not_found()
    return PhotoChangeOut(photo=AdminPhoto.of(result.photo), changed=result.changed)


@router.delete("/photos/{photo_id}")
def delete_photo(photo_id: PhotoId, core: CoreDep, admin: AdminDep) -> DeletePhotoOut:
    """Delete for good: the files go, the number stays taken."""
    if not core.services.moderation.delete_photo(photo_id, actor=admin.actor):
        raise _photo_not_found()
    return DeletePhotoOut(ok=True, id=photo_id)


@router.post("/photos/bulk")
def bulk(body: BulkIn, core: CoreDep, admin: AdminDep) -> BulkOut:
    """One action on up to 200 photos; one event per changed photo."""
    result = core.services.moderation.bulk(body.ids, body.action, actor=admin.actor)
    return BulkOut(
        action=body.action,
        changed=result.changed,
        unchanged=result.unchanged,
        missing=result.missing,
    )
