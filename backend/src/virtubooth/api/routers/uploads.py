"""`POST /api/x/{ext_id}/upload`: the upload pipeline (see services/uploads.py)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from fastapi import APIRouter, Request
from pydantic import create_model

from ...core.errors import error_responses
from ...core.security import client_ip
from ...extensions.sdk import Extension
from ...services.uploads import UploadRequest
from ..deps import CoreDep, GuestDep
from ..schemas.guest import GuestPhoto, UploadOutBase


def upload_model(extensions: Sequence[Extension]) -> type[UploadOutBase]:
    """`UploadOut`: the photo plus every field an extension's `on_upload` may
    add (declared through `Extension.upload_result`), each optional."""
    fields: dict[str, Any] = {}
    for ext in extensions:
        if ext.upload_result is None:
            continue
        for name, info in ext.upload_result.model_fields.items():
            if name in fields or name == "photo":
                fields[name] = (Any, None)  # declared differently by two extensions
            else:
                fields[name] = (cast(Any, info.annotation) | None, None)
    return create_model("UploadOut", __base__=UploadOutBase, **fields)


def build_router(extensions: Sequence[Extension]) -> APIRouter:
    router = APIRouter(
        tags=["uploads"], responses=error_responses(400, 401, 403, 404, 413, 415, 422, 429, 503)
    )
    out = upload_model(extensions)

    @router.post(
        "/api/x/{ext_id}/upload",
        status_code=201,
        response_model=out,
        response_model_exclude_unset=True,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}},
            },
            "parameters": [
                {
                    "name": "X-VB-Meta",
                    "in": "header",
                    "required": False,
                    "description": "encodeURIComponent(JSON.stringify(meta)), at most 2048 chars; "
                    "keys per extension (beer: vessel, facing; booth: filter, facing).",
                    "schema": {"type": "string", "maxLength": 2048},
                },
                {
                    "name": "X-VB-Raw-Bytes",
                    "in": "header",
                    "required": False,
                    "description": "Only for activities that keep originals (booth): the body "
                    "is the filtered photo followed by its unfiltered original (same size), a "
                    "second JPEG of this many bytes. Each part may be up to the size limit. "
                    "Dropped when the photo has no filter (booth: `normal`). Other "
                    "activities: 400 `raw_not_allowed`; a bad value or original: 400 "
                    "`invalid_raw`.",
                    "schema": {"type": "string", "pattern": "^[0-9]{1,12}$"},
                },
            ],
        },
    )
    async def upload(ext_id: str, request: Request, user: GuestDep, core: CoreDep) -> Any:
        """Upload one JPEG for an activity. Answers 201 with the stored photo
        and the activity's extra fields (beer: `beer_number`, `total`; booth:
        `booth_number`)."""
        result = await core.services.uploads.upload(
            ext_id,
            user,
            UploadRequest(
                content_type=request.headers.get("content-type", ""),
                content_length=request.headers.get("content-length", ""),
                meta_header=request.headers.get("x-vb-meta"),
                raw_header=request.headers.get("x-vb-raw-bytes"),
                ip=client_ip(request),
                body=request.stream(),
            ),
        )
        return out.model_validate({"photo": GuestPhoto.of(result.photo), **result.extra})

    return router
