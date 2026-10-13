"""Serving stored photos. Only the admin and the guest who took a photo can
fetch it. Photos are looked up by their random public id, never by path."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from ...core import errors
from ...core.errors import error_responses
from ...domain.constants import PHOTO_ID_RE
from ...domain.models import Photo
from ...runtime import Core
from ..deps import CoreDep, admin_from_cookie, guest_from_cookie, has_access

router = APIRouter(tags=["media"], responses=error_responses(404, 422))

JPEG_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "The JPEG (`thumb`: 400 px). Cache-Control: private, max-age=86400.",
        "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}},
    }
}


def photo_file_response(
    core: Core, photo: Photo, *, thumb: bool = False, download: bool = False
) -> FileResponse:
    """Use this from extensions that want to show photos to other viewers."""
    name = photo.thumb_filename if thumb else photo.filename
    path = core.repos.photos.path(photo.extension, name)
    if not path.is_file():
        raise errors.not_found()
    headers = {"Cache-Control": "private, max-age=86400"}
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="{photo.extension}-{photo.seq:05d}.jpg"'
        )
    return FileResponse(path, media_type="image/jpeg", headers=headers)


@router.get("/media/{public_id}", response_class=FileResponse, responses=JPEG_RESPONSE)
def media(
    public_id: str,
    request: Request,
    core: CoreDep,
    thumb: bool = False,
    download: bool = False,
) -> FileResponse:
    """A photo for the admin, or for the guest who took it (also when hidden).
    Everyone else gets 404, without learning whether it exists."""
    if not PHOTO_ID_RE.match(public_id):
        raise errors.not_found()
    photo = core.repos.photos.get(public_id)
    if photo is None:
        raise errors.not_found()
    if admin_from_cookie(request, core) is None:
        guest = guest_from_cookie(request, core) if has_access(request, core) else None
        if guest is None or guest.id != photo.user_id:
            raise errors.not_found()
    return photo_file_response(core, photo, thumb=thumb, download=download)
