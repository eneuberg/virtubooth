"""The generic upload pipeline every extension with an UploadPolicy gets.

POST /api/x/<id>/upload   (403 uploads_paused / uploads_stopped while uploads are paused)
  body:     the JPEG bytes (Content-Type: image/jpeg)
  X-VB-Meta (optional): encodeURIComponent(JSON.stringify({...})), keys from
            UploadPolicy.meta_keys
  X-VB-Raw-Bytes (optional, UploadPolicy.accepts_raw): the body is the photo
            followed by its unfiltered original, a second JPEG of this many bytes
            at the end. Both parts pass the same checks (each at most the size
            limit, exact size, re-encoded); the original is dropped when the meta
            says the photo has no filter (UploadPolicy.raw_differs) or both are
            the same bytes. Old clients send just the photo.
  → 201 {"photo": {...}, ...whatever extension.on_upload returned}

Checks run in this order (architecture.md §2.5): extension, pause, stop,
free disk space (503 storage_full below VB_MIN_FREE_MB), content type, the
guest's own rate limit (charged on every attempt), the shared IP/global budgets
(only checked), the guest's photo cap (403 photo_limit at
VB_MAX_PHOTOS_PER_GUEST photos that are not deleted), declared size, meta, the
body (streamed with a cap), decode + re-encode, then the shared budgets are
charged.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from anyio import to_thread

from ..api.schemas.admin import AdminPhoto
from ..core import errors
from ..core.clock import local_now, now_iso
from ..db.database import Database
from ..domain.models import Photo, User, new_public_id
from ..extensions.sdk import Extension, UploadContext, UploadPolicy
from ..repositories.container import Repositories
from .events import AdminEvents
from .images import ProcessedImage, process_jpeg

if TYPE_CHECKING:
    from ..runtime import Core

log = logging.getLogger(__name__)

MAX_META_HEADER = 2048
# at most one "disk almost full" log line per this many seconds
DISK_WARN_EVERY = 60.0


def too_large() -> errors.ApiError:
    return errors.ApiError(413, "too_large", "Das Bild ist zu groß.")


def invalid_meta(message: str) -> errors.ApiError:
    return errors.bad_request(message, "invalid_meta")


async def read_limited(stream: AsyncIterator[bytes], limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in stream:
        size += len(chunk)
        if size > limit:
            raise too_large()
        chunks.append(chunk)
    if size == 0:
        raise errors.bad_request("Der Upload war leer.", "empty_upload")
    return b"".join(chunks)


def invalid_raw(message: str = "Das Original ohne Filter ist unlesbar.") -> errors.ApiError:
    return errors.bad_request(message, "invalid_raw")


def parse_raw_bytes(header: str | None, policy: UploadPolicy) -> int | None:
    """The length of the appended original (X-VB-Raw-Bytes), None: no original."""
    if header is None or header == "":
        return None
    if not policy.accepts_raw:
        raise errors.bad_request(
            "Diese Aktivität speichert kein Original ohne Filter.", "raw_not_allowed"
        )
    if not header.isdigit() or len(header) > 12 or int(header) <= 0:
        raise invalid_raw()
    return int(header)


def split_raw(body: bytes, raw_len: int | None, max_bytes: int) -> tuple[bytes, bytes | None]:
    """(photo, original) of a body; each part at most `max_bytes` (413)."""
    if raw_len is None:
        return body, None
    if raw_len >= len(body):
        raise invalid_raw()
    photo, raw = body[:-raw_len], body[-raw_len:]
    if len(photo) > max_bytes or len(raw) > max_bytes:
        raise too_large()
    return photo, raw


def parse_meta(header: str | None, policy: UploadPolicy) -> dict[str, Any]:
    meta: dict[str, Any]
    if not header:
        meta = {}
    else:
        if len(header) > MAX_META_HEADER:
            raise invalid_meta("Metadaten zu lang.")
        try:
            parsed = json.loads(unquote(header))
        except ValueError as exc:
            raise invalid_meta("Metadaten unlesbar.") from exc
        if not isinstance(parsed, dict):
            raise invalid_meta("Metadaten unlesbar.")
        meta = parsed
        unknown = set(meta) - policy.meta_keys
        if unknown:
            raise invalid_meta(f"Unbekannte Metadaten: {sorted(unknown)}")
        for key, value in meta.items():
            if isinstance(value, str):
                if len(value) > 100:
                    raise invalid_meta(f"Metadaten-Wert zu lang: {key}")
            elif not (value is None or isinstance(value, bool | int | float)):
                raise invalid_meta(f"Ungültiger Metadaten-Wert: {key}")
    if policy.validate_meta is not None:
        try:
            meta = policy.validate_meta(meta)
        except ValueError as exc:
            raise invalid_meta(str(exc)) from exc
    return meta


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


@dataclass(frozen=True)
class UploadRequest:
    content_type: str
    content_length: str
    meta_header: str | None
    ip: str
    body: AsyncIterator[bytes]
    # X-VB-Raw-Bytes: the appended unfiltered original's length
    raw_header: str | None = None


@dataclass(frozen=True)
class UploadResult:
    photo: Photo
    extra: dict[str, Any]


class UploadService:
    def __init__(self, core: Core, db: Database, repos: Repositories, events: AdminEvents) -> None:
        self.core = core
        self.db = db
        self.repos = repos
        self.events = events
        self._disk_warned_at: float | None = None
        self._disk_lock = threading.Lock()

    def free_bytes(self) -> int:
        """Free space on the disk of the data dir (tests replace it)."""
        return shutil.disk_usage(self.core.settings.data_dir).free

    def check_disk(self) -> None:
        """Refuse the upload while the data dir's disk has less than
        VB_MIN_FREE_MB free: a full disk would break SQLite and the server."""
        min_free = self.core.settings.min_free_mb * 1024 * 1024
        if min_free <= 0:
            return
        free = self.free_bytes()
        if free >= min_free:
            return
        now = time.monotonic()
        with self._disk_lock:
            warn = self._disk_warned_at is None or now - self._disk_warned_at >= DISK_WARN_EVERY
            if warn:
                self._disk_warned_at = now
        if warn:
            log.warning(
                "uploads refused: %d MB free under %s, below VB_MIN_FREE_MB=%d",
                free // (1024 * 1024),
                self.core.settings.data_dir,
                self.core.settings.min_free_mb,
            )
        raise errors.storage_full()

    async def upload(self, ext_id: str, user: User, req: UploadRequest) -> UploadResult:
        core = self.core
        ext = core.extensions.get(ext_id)
        if ext is None or ext.upload is None:
            raise errors.not_found()
        policy = ext.upload
        # a paused guest hears about their own pause first: it outlasts a stop
        if user.uploads_paused:
            raise errors.uploads_paused()
        if self.repos.app_settings.upload_stop().enabled:
            raise errors.uploads_stopped()
        self.check_disk()

        if req.content_type.split(";")[0].strip().lower() != "image/jpeg":
            raise errors.ApiError(415, "unsupported_type", "Nur JPEG-Bilder sind erlaubt.")

        limits = core.limits
        # The guest's own budget is charged for every attempt. The budgets shared
        # with everyone on the venue WiFi (per IP, global) are only checked here and
        # charged once the photo is valid, so junk uploads can't use them up.
        user_key = f"user:{user.id}"
        if not limits.upload_user.hit(user_key):
            raise errors.rate_limited(limits.upload_user.retry_after(user_key))
        shared = ((limits.upload_ip, req.ip), (limits.upload_global, "global"))
        for limiter, key in shared:
            if not limiter.available(key):
                raise errors.rate_limited(limiter.retry_after(key))
        cap = core.settings.max_photos_per_guest
        # the admin guest is the host: no photo cap (the rate limits still apply)
        if cap > 0 and not user.is_host and self.repos.photos.count(user_id=user.id) >= cap:
            raise errors.photo_limit()

        max_bytes = policy.max_bytes or core.settings.max_upload_bytes
        raw_len = parse_raw_bytes(req.raw_header, policy)
        # with an original the body holds two JPEGs, each up to the limit
        body_limit = max_bytes * 2 if raw_len is not None else max_bytes
        if req.content_length.isdigit() and int(req.content_length) > body_limit:
            raise too_large()
        meta = parse_meta(req.meta_header, policy)
        body = await read_limited(req.body, body_limit)
        photo_bytes, raw_bytes = split_raw(body, raw_len, max_bytes)
        del body
        if raw_bytes is not None and (
            raw_bytes == photo_bytes
            or (policy.raw_differs is not None and not policy.raw_differs(meta))
        ):
            raw_bytes = None  # the photo is its own original: stored once

        def process(data: bytes) -> ProcessedImage:
            return process_jpeg(
                data,
                max_side=policy.max_side,
                min_side=policy.min_side,
                quality=policy.quality,
                thumb_side=policy.thumb_side,
                exact_size=policy.exact_size,
            )

        image = await to_thread.run_sync(lambda: process(photo_bytes))
        raw_image: ProcessedImage | None = None
        if raw_bytes is not None:
            original = raw_bytes
            try:
                raw_image = await to_thread.run_sync(lambda: process(original))
            except errors.ApiError as exc:
                # the photo is fine, its original is not: say which one
                raise errors.ApiError(
                    exc.status, "invalid_raw", f"Original ohne Filter: {exc.message}"
                ) from exc
            if (raw_image.width, raw_image.height) != (image.width, image.height):
                raise invalid_raw("Das Original muss so groß sein wie das Foto.")
        for limiter, key in shared:
            if not limiter.hit(key):
                raise errors.rate_limited(limiter.retry_after(key))
        photo = await to_thread.run_sync(lambda: self.store(ext, user, image, meta, raw_image))

        extra: dict[str, Any] = {}
        if ext.on_upload is not None:
            on_upload = ext.on_upload
            context = UploadContext(core, ext, user, photo)
            extra = await to_thread.run_sync(lambda: on_upload(context)) or {}
        self.events.photo_created(AdminPhoto.of(photo))
        return UploadResult(photo, extra)

    def store(
        self,
        ext: Extension,
        user: User,
        image: ProcessedImage,
        meta: dict[str, Any],
        raw: ProcessedImage | None = None,
    ) -> Photo:
        """Write the photo and its thumbnail atomically (and the unfiltered original
        with its thumbnail below raw/), then record them."""
        now = local_now(self.core.settings.timezone)
        stem = f"{now:%Y%m%d-%H%M%S}-{now.microsecond // 1000:03d}_{secrets.token_hex(3)}"
        filename, thumb_filename = f"{stem}.jpg", f"thumbs/{stem}.jpg"
        raw_filename = raw_thumb_filename = None
        photos = self.repos.photos
        path = photos.path(ext.id, filename)
        thumb_path = photos.path(ext.id, thumb_filename)
        written = [path, thumb_path]
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        public_id = new_public_id()
        try:
            _write_atomic(path, image.data)
            _write_atomic(thumb_path, image.thumb)
            if raw is not None:
                raw_filename, raw_thumb_filename = f"raw/{stem}.jpg", f"raw/thumbs/{stem}.jpg"
                raw_path = photos.path(ext.id, raw_filename)
                raw_thumb_path = photos.path(ext.id, raw_thumb_filename)
                written += [raw_path, raw_thumb_path]
                raw_thumb_path.parent.mkdir(parents=True, exist_ok=True)
                _write_atomic(raw_path, raw.data)
                _write_atomic(raw_thumb_path, raw.thumb)
            photos.insert(
                public_id=public_id,
                extension=ext.id,
                user_id=user.id,
                filename=filename,
                thumb_filename=thumb_filename,
                width=image.width,
                height=image.height,
                size=len(image.data),
                meta=meta,
                created_at=now_iso(),
                raw_filename=raw_filename,
                raw_thumb_filename=raw_thumb_filename,
            )
        except BaseException:
            for written_path in written:
                written_path.unlink(missing_ok=True)
            raise
        photo = photos.get(public_id)
        assert photo is not None
        return photo
