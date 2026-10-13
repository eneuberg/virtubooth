"""The poster template (`/api/admin/poster`): upload the host's PDF, fetch it back,
save where the QR code goes, remove it (see services/posters.py). The admin's
browser renders the page and builds the printable PDFs."""

from __future__ import annotations

from typing import Any

from anyio import to_thread
from fastapi import APIRouter, Depends, Request, Response

from ....core.errors import error_responses, json_error_responses
from ...deps import EVENT_CURSOR_HEADER, AdminDep, CoreDep, require_admin
from ...schemas.poster import PosterLayoutIn, PosterOut
from ._params import ADMIN_ERROR_STATUSES

router = APIRouter(
    prefix="/api/admin/poster",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
    responses=error_responses(*ADMIN_ERROR_STATUSES),
)

_PDF = {"schema": {"type": "string", "format": "binary"}}
TEMPLATE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "The template PDF as an attachment (plakat-vorlage.pdf).",
        "content": {"application/pdf": _PDF},
    },
    # errors are JSON, not the file's type (overrides the router's entries)
    **json_error_responses(*ADMIN_ERROR_STATUSES, 409),
}


@router.get("")
def get_poster(core: CoreDep) -> PosterOut:
    """The stored template (null without one) and the upload limit."""
    return core.services.posters.state()


@router.put(
    "/template",
    openapi_extra={"requestBody": {"required": True, "content": {"application/pdf": _PDF}}},
)
async def put_template(request: Request, core: CoreDep, admin: AdminDep) -> PosterOut:
    """Upload a new template (raw PDF, at most `max_bytes`, Content-Length required).
    Replaces the old one and resets the layout. 400 `invalid_pdf` when the body
    does not start like a PDF, 413 `too_large`, 411 `length_required`."""
    return await core.services.posters.upload(
        request.stream(),
        content_length=request.headers.get("content-length"),
        chunked="transfer-encoding" in request.headers,
        actor=admin.actor,
    )


@router.get("/template", response_class=Response, responses=TEMPLATE_RESPONSES)
async def get_template(response: Response, core: CoreDep) -> Response:
    """The template's bytes (409 `no_template` without one). Sandboxed, never cached."""
    data = await to_thread.run_sync(core.services.posters.read)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="plakat-vorlage.pdf"',
            "Cache-Control": "no-store",
            "Content-Security-Policy": "sandbox",
            # a returned response doesn't get the dependency's headers by itself
            EVENT_CURSOR_HEADER: response.headers[EVENT_CURSOR_HEADER],
        },
    )


@router.put("/layout", responses=error_responses(409))
def put_layout(body: PosterLayoutIn, core: CoreDep, admin: AdminDep) -> PosterOut:
    """Save where the QR code goes: a page and a square relative to it (origin top
    left). 400 `invalid_layout` when it leaves the page, is under 3 % or not
    square; 409 `no_template` without a template."""
    return core.services.posters.set_layout(body, actor=admin.actor)


@router.delete("/template")
def delete_template(core: CoreDep, admin: AdminDep) -> PosterOut:
    """Remove the template (idempotent); the standard poster is used again."""
    return core.services.posters.delete(actor=admin.actor)
