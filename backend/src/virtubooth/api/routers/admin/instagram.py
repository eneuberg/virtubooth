"""The Instagram board's actions: the „Erledigt“ mark and a ZIP of the photos
to post. The list itself is `GET /api/admin/instagram` (overview.py)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Response
from fastapi.responses import StreamingResponse

from ....core.errors import json_error_responses
from ....services.instagram import stream_zip
from ...deps import EVENT_CURSOR_HEADER, AdminDep, CoreDep
from ...schemas.exports import InstagramDoneIn, InstagramDoneOut
from ._params import ADMIN_ERROR_STATUSES

router = APIRouter()

# as guests type it: "@Name" and profile links work too
Handle = Annotated[str, Path(min_length=1, max_length=200)]

ZIP_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "A zip of the photos: 0001-<activity>-<photo id>.jpg, … in upload order.",
        "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
    },
    **json_error_responses(*ADMIN_ERROR_STATUSES),
}


@router.post("/instagram/{handle}/done")
def set_instagram_done(
    handle: Handle, body: InstagramDoneIn, core: CoreDep, admin: AdminDep
) -> InstagramDoneOut:
    """Mark a handle „Erledigt“ (or not). 404 for a handle no guest gave."""
    normalized, changed = core.services.instagram.set_done(handle, body.done, actor=admin.actor)
    return InstagramDoneOut(handle=normalized, done=body.done, changed=changed)


@router.get(
    "/instagram/{handle}/photos.zip", response_class=StreamingResponse, responses=ZIP_RESPONSES
)
def instagram_photos_zip(handle: Handle, response: Response, core: CoreDep) -> StreamingResponse:
    """The handle's visible photos of guests who aren't banned, as a zip
    attachment (streamed). 404 `not_found` when there are none."""
    service = core.services.instagram
    normalized, photos = service.photos_to_post(handle)
    return StreamingResponse(
        stream_zip(service.zip_entries(photos)),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="fotos-{normalized}.zip"',
            EVENT_CURSOR_HEADER: response.headers[EVENT_CURSOR_HEADER],
        },
    )
