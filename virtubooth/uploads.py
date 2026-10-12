"""The generic upload pipeline every extension with an UploadPolicy gets.

POST /api/x/<id>/upload
  body:     the JPEG bytes (Content-Type: image/jpeg)
  X-VB-Meta (optional): encodeURIComponent(JSON.stringify({...})), keys from
            UploadPolicy.meta_keys
  → 201 {"photo": {...}, ...whatever extension.on_upload returned}
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import errors
from .context import Core
from .deps import get_core, require_guest
from .extension import Extension, UploadContext, UploadPolicy
from .images import ProcessedImage, process_jpeg
from .repo import Photo, User
from .security import client_ip

router = APIRouter()

MAX_META_HEADER = 2048


def guest_photo_view(photo: Photo) -> dict[str, Any]:
    return {
        "id": photo.public_id,
        "extension": photo.extension,
        "seq": photo.seq,
        "created_at": photo.created_at,
        "width": photo.width,
        "height": photo.height,
        "url": photo.url(),
        "thumb_url": photo.url(thumb=True),
    }


def too_large() -> errors.ApiError:
    return errors.ApiError(413, "too_large", "Das Bild ist zu groß.")


async def read_limited(request: Request, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_large()
        chunks.append(chunk)
    if size == 0:
        raise errors.bad_request("Der Upload war leer.", "empty_upload")
    return b"".join(chunks)


def parse_meta(header: str | None, policy: UploadPolicy) -> dict[str, Any]:
    if not header:
        meta: dict[str, Any] = {}
    else:
        if len(header) > MAX_META_HEADER:
            raise errors.bad_request("Metadaten zu lang.", "invalid_meta")
        try:
            meta = json.loads(unquote(header))
        except ValueError as exc:
            raise errors.bad_request("Metadaten unlesbar.", "invalid_meta") from exc
        if not isinstance(meta, dict):
            raise errors.bad_request("Metadaten unlesbar.", "invalid_meta")
        unknown = set(meta) - policy.meta_keys
        if unknown:
            raise errors.bad_request(f"Unbekannte Metadaten: {sorted(unknown)}", "invalid_meta")
        for key, value in meta.items():
            if isinstance(value, str):
                if len(value) > 100:
                    raise errors.bad_request(f"Metadaten-Wert zu lang: {key}", "invalid_meta")
            elif not (value is None or isinstance(value, bool | int | float)):
                raise errors.bad_request(f"Ungültiger Metadaten-Wert: {key}", "invalid_meta")
    if policy.validate_meta is not None:
        try:
            meta = policy.validate_meta(meta)
        except ValueError as exc:
            raise errors.bad_request(str(exc), "invalid_meta") from exc
    return meta


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def store_photo(
    core: Core, ext: Extension, user: User, image: ProcessedImage, meta: dict[str, Any]
) -> Photo:
    now = datetime.now(ZoneInfo(core.settings.timezone))
    stem = f"{now:%Y%m%d-%H%M%S}-{now.microsecond // 1000:03d}_{secrets.token_hex(3)}"
    filename, thumb_filename = f"{stem}.jpg", f"thumbs/{stem}.jpg"
    path = core.repo.photo_path(ext.id, filename)
    thumb_path = core.repo.photo_path(ext.id, thumb_filename)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, image.data)
    _write_atomic(thumb_path, image.thumb)
    try:
        return core.repo.insert_photo(
            extension=ext.id,
            user_id=user.id,
            filename=filename,
            thumb_filename=thumb_filename,
            width=image.width,
            height=image.height,
            size=len(image.data),
            meta=meta,
        )
    except BaseException:
        path.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)
        raise


@router.post("/api/x/{ext_id}/upload")
async def upload(
    ext_id: str,
    request: Request,
    user: User = Depends(require_guest),
    core: Core = Depends(get_core),
) -> JSONResponse:
    ext = core.extensions.get(ext_id)
    if ext is None or ext.upload is None:
        raise errors.not_found()
    policy = ext.upload

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "image/jpeg":
        raise errors.ApiError(415, "unsupported_type", "Nur JPEG-Bilder sind erlaubt.")

    ip = client_ip(request)
    limits = core.limits
    for limiter, key in (
        (limits.upload_user, f"user:{user.id}"),
        (limits.upload_ip, ip),
        (limits.upload_global, "global"),
    ):
        if not limiter.hit(key):
            raise errors.rate_limited(limiter.retry_after(key))

    max_bytes = policy.max_bytes or core.settings.max_upload_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise too_large()
    meta = parse_meta(request.headers.get("x-vb-meta"), policy)
    raw = await read_limited(request, max_bytes)

    image = await run_in_threadpool(
        process_jpeg,
        raw,
        max_side=policy.max_side,
        min_side=policy.min_side,
        quality=policy.quality,
        thumb_side=policy.thumb_side,
    )
    photo = await run_in_threadpool(store_photo, core, ext, user, image, meta)

    extra: dict[str, Any] = {}
    if ext.on_upload is not None:
        extra = await run_in_threadpool(ext.on_upload, UploadContext(core, ext, user, photo)) or {}
    core.bus.publish("photo.created", {"photo": photo.admin_view()})
    return JSONResponse({"photo": guest_photo_view(photo), **extra}, status_code=201)
