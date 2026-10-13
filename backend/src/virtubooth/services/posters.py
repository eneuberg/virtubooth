"""The poster template: the host's own PDF and where the QR code goes on it.

The server only keeps the bytes and the rectangle; the admin's browser renders
the page (pdf.js), places the QR field and builds the printable PDFs.

- file `<data>/poster/template.pdf`, written atomically (`.part`, fsync, replace);
- settings key `poster.template` = {sha256, bytes, uploaded_at, by, pages, page,
  page_width, page_height, rect}; the layout fields are null until the first
  layout save, and a new upload resets them. `{}` (or no row) = no template.

Upload: at most MAX_BYTES, Content-Length required (411), larger declared → 413
before reading, the body must start with `%PDF-` within its first 1024 bytes.
Every change is audit-logged in its transaction (target ""). No admin events:
other admin screens refetch on focus.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from anyio import to_thread

from ..api.schemas.poster import PosterLayoutIn, PosterOut, PosterRect, PosterTemplate
from ..core import errors
from ..core.clock import now_iso
from ..db.database import Database
from ..repositories.container import Repositories

if TYPE_CHECKING:
    from ..runtime import Core

POSTER_KEY = "poster.template"
# the documented reverse-proxy body limit (docs/DEPLOY.md)
MAX_BYTES = 8_000_000
PDF_MAGIC = b"%PDF-"
MAGIC_WITHIN = 1024
MAX_PAGES = 500
# PDF's largest page side (200 in), points
MAX_SIDE = 14_400.0
MIN_REL = 0.03
EPS = 1e-6
# the field is square in PDF points within this share
SQUARE_TOLERANCE = 0.02


def too_large() -> errors.ApiError:
    return errors.ApiError(413, "too_large", "Die PDF ist zu groß (höchstens 8 MB).")


def length_required() -> errors.ApiError:
    return errors.ApiError(411, "length_required", "Ungültige Anfrage.")


def invalid_pdf() -> errors.ApiError:
    return errors.bad_request("Das ist keine PDF-Datei.", "invalid_pdf")


def invalid_layout() -> errors.ApiError:
    return errors.bad_request(
        "Das QR-Feld muss ganz auf der Seite liegen und quadratisch sein.", "invalid_layout"
    )


def no_template() -> errors.ApiError:
    return errors.ApiError(409, "no_template", "Erst eine Vorlage hochladen.")


def layout_ok(layout: PosterLayoutIn) -> bool:
    """The rectangle lies on the page, is at least MIN_REL big and square in points."""
    r = layout.rect
    pw, ph = layout.page_width, layout.page_height
    numbers = (pw, ph, r.x, r.y, r.w, r.h)
    if not all(math.isfinite(n) for n in numbers):
        return False
    if not (0 <= layout.page < layout.pages <= MAX_PAGES):
        return False
    if not (0 < pw <= MAX_SIDE and 0 < ph <= MAX_SIDE):
        return False
    if r.x < 0 or r.y < 0 or r.w < MIN_REL or r.h < MIN_REL:
        return False
    if r.x + r.w > 1 + EPS or r.y + r.h > 1 + EPS:
        return False
    width, height = r.w * pw, r.h * ph
    return abs(width - height) <= SQUARE_TOLERANCE * max(width, height)


def _fsync_dir(path: Path) -> None:
    """Make the rename durable (POSIX; a no-op where directories can't be opened)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class PosterService:
    def __init__(self, core: Core, db: Database, repos: Repositories) -> None:
        self.core = core
        self.db = db
        self.repos = repos
        # one upload at a time writes the .part file
        self._write_lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self.core.settings.data_dir / "poster" / "template.pdf"

    # ------------------------------------------------------------- reads

    def template(self) -> PosterTemplate | None:
        raw = self.repos.app_settings.get(POSTER_KEY)
        if not raw.get("sha256") or not self.path.is_file():
            return None
        return PosterTemplate.model_validate(raw)

    def state(self) -> PosterOut:
        return PosterOut(template=self.template(), max_bytes=MAX_BYTES)

    def read(self) -> bytes:
        """The template's bytes (409 `no_template` without one)."""
        if self.template() is None:
            raise no_template()
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            raise no_template() from None

    # ----------------------------------------------------------- changes

    async def upload(
        self,
        body: AsyncIterator[bytes],
        *,
        content_length: str | None,
        chunked: bool,
        actor: str,
    ) -> PosterOut:
        """Store a new template (replaces the old one and resets the layout)."""
        if chunked or content_length is None or not content_length.isdigit():
            raise length_required()
        if int(content_length) > MAX_BYTES:
            raise too_large()
        chunks: list[bytes] = []
        size = 0
        async for chunk in body:
            size += len(chunk)
            if size > MAX_BYTES:
                raise too_large()
            chunks.append(chunk)
        data = b"".join(chunks)
        if PDF_MAGIC not in data[:MAGIC_WITHIN]:
            raise invalid_pdf()
        return await to_thread.run_sync(lambda: self._store(data, actor))

    def _store(self, data: bytes, actor: str) -> PosterOut:
        folder = self.path.parent
        folder.mkdir(parents=True, exist_ok=True)
        part = folder / f"{self.path.name}.part"
        with self._write_lock:
            with part.open("wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            try:
                with self.db.tx():
                    at = now_iso()
                    meta = PosterTemplate(
                        sha256=hashlib.sha256(data).hexdigest(),
                        bytes=len(data),
                        uploaded_at=at,
                        by=actor,
                        pages=None,
                        page=None,
                        page_width=None,
                        page_height=None,
                        rect=None,
                    )
                    self.repos.app_settings.put(POSTER_KEY, meta.model_dump(), at=at)
                    self.repos.audit.log(actor, "poster.template", "", {"bytes": len(data)}, at=at)
                    # last: a failed rename rolls the record back
                    os.replace(part, self.path)
            finally:
                part.unlink(missing_ok=True)
            _fsync_dir(folder)
        return self.state()

    def set_layout(self, layout: PosterLayoutIn, *, actor: str) -> PosterOut:
        with self.db.tx():
            current = self.template()
            if current is None:
                raise no_template()
            if not layout_ok(layout):
                raise invalid_layout()
            at = now_iso()
            meta: dict[str, Any] = current.model_dump()
            meta.update(
                pages=layout.pages,
                page=layout.page,
                page_width=layout.page_width,
                page_height=layout.page_height,
                rect=PosterRect.model_validate(layout.rect).model_dump(),
            )
            self.repos.app_settings.put(POSTER_KEY, meta, at=at)
            self.repos.audit.log(
                actor, "poster.layout", "", {"page": layout.page, "pages": layout.pages}, at=at
            )
        return self.state()

    def delete(self, *, actor: str) -> PosterOut:
        """Remove the template (idempotent: without one nothing happens)."""
        path = self.path
        with self.db.tx():
            raw = self.repos.app_settings.get(POSTER_KEY)
            if raw.get("sha256"):
                at = now_iso()
                self.repos.app_settings.put(POSTER_KEY, {}, at=at)
                self.repos.audit.log(actor, "poster.template_delete", "", at=at)
            # also a file a lost record left behind
            self.db.on_commit(lambda: path.unlink(missing_ok=True))
        return self.state()
