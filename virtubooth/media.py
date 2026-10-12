"""Serving stored photos. Only the admin and the guest who took a photo can
fetch it. Photos are looked up by their random public id, never by path."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from . import errors
from .context import Core
from .deps import admin_from_cookie, get_core, guest_from_cookie, has_access
from .repo import Photo

router = APIRouter()

PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,32}$")


def photo_file_response(
    core: Core, photo: Photo, *, thumb: bool = False, download: bool = False
) -> FileResponse:
    """Use this from extensions that want to show photos to other viewers."""
    path = core.repo.photo_path(photo.extension, photo.thumb_filename if thumb else photo.filename)
    if not path.is_file():
        raise errors.not_found()
    headers = {"Cache-Control": "private, max-age=86400"}
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="{photo.extension}-{photo.seq:05d}.jpg"'
        )
    return FileResponse(path, media_type="image/jpeg", headers=headers)


@router.get("/media/{public_id}")
def media(
    public_id: str,
    request: Request,
    thumb: bool = False,
    download: bool = False,
    core: Core = Depends(get_core),
) -> FileResponse:
    if not PUBLIC_ID_RE.match(public_id):
        raise errors.not_found()
    photo = core.repo.get_photo(public_id)
    if photo is None:
        raise errors.not_found()
    if admin_from_cookie(request, core) is None:
        guest = guest_from_cookie(request, core) if has_access(request, core) else None
        if guest is None or guest.id != photo.user_id:
            raise errors.not_found()
    return photo_file_response(core, photo, thumb=thumb, download=download)
