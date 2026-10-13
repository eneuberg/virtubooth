"""The Instagram board: an "Erledigt" mark per handle (posted and tagged) and
a ZIP of the photos to post for one handle.

The marks live in the settings table (`instagram_done` = {"handles":
{<handle>: {"at", "by"}}}). Handles are normalized exactly like the guests'
input (lower case, no "@", profile links accepted).
"""

from __future__ import annotations

import io
import os
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from ..core import errors
from ..core.clock import now_iso
from ..db.database import Database
from ..domain.models import Photo
from ..repositories.container import Repositories
from .events import AdminEvents
from .identity import normalize_instagram

INSTAGRAM_DONE_KEY: Final = "instagram_done"
# read photo files in pieces this big while streaming a zip
CHUNK: Final = 256 * 1024


class InstagramService:
    def __init__(self, db: Database, repos: Repositories, events: AdminEvents) -> None:
        self.db = db
        self.repos = repos
        self.events = events

    @staticmethod
    def normalize(raw: str) -> str:
        """The handle as stored on guests; 400 invalid_instagram otherwise."""
        handle = normalize_instagram(raw)
        if handle is None:
            raise errors.bad_request("Bitte einen Instagram-Namen angeben.", "invalid_instagram")
        return handle

    def _marks(self) -> dict[str, Any]:
        handles = self.repos.app_settings.get(INSTAGRAM_DONE_KEY).get("handles")
        return dict(handles) if isinstance(handles, dict) else {}

    def done_handles(self) -> set[str]:
        return set(self._marks())

    def set_done(self, raw_handle: str, done: bool, *, actor: str) -> tuple[str, bool]:
        """Mark a handle done (or not); (handle, changed). 404 for a handle no
        guest gave."""
        handle = self.normalize(raw_handle)
        with self.db.tx():
            if not self.repos.instagram.handle_exists(handle):
                raise errors.not_found("Diesen Instagram-Namen hat kein Gast angegeben.")
            marks = self._marks()
            changed = (handle in marks) != done
            if changed:
                at = now_iso()
                if done:
                    marks[handle] = {"at": at, "by": actor}
                else:
                    del marks[handle]
                self.repos.app_settings.put(INSTAGRAM_DONE_KEY, {"handles": marks}, at=at)
                self.repos.audit.log(
                    actor,
                    "instagram.done" if done else "instagram.undone",
                    f"instagram:{handle}",
                    at=at,
                )
                self.events.instagram_done(handle, done)
        return handle, changed

    def photos_to_post(self, raw_handle: str) -> tuple[str, list[Photo]]:
        """The handle's visible photos of guests who aren't banned, upload
        order; 404 when there are none."""
        handle = self.normalize(raw_handle)
        photos = self.repos.instagram.postable_photos(handle)
        if not photos:
            raise errors.not_found("Für diesen Instagram-Namen gibt es keine sichtbaren Fotos.")
        return handle, photos

    def zip_entries(self, photos: list[Photo]) -> list[tuple[Path, str]]:
        """(file, name in the zip): 0001-beer-<id>.jpg, … in upload order."""
        width = max(4, len(str(len(photos))))
        return [
            (
                self.repos.photos.path(p.extension, p.filename),
                f"{i:0{width}d}-{p.extension}-{p.public_id}.jpg",
            )
            for i, p in enumerate(photos, 1)
        ]


class _Sink(io.RawIOBase):
    """A write-only, unseekable buffer: zipfile then writes a streamable zip
    (sizes in data descriptors) that we hand out piece by piece."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        chunk = bytes(data)
        self._chunks.append(chunk)
        return len(chunk)

    def take(self) -> bytes:
        out = b"".join(self._chunks)
        self._chunks.clear()
        return out


def stream_zip(entries: list[tuple[Path, str]]) -> Iterator[bytes]:
    """A zip of these files, produced while it is sent. JPEGs are stored (they
    don't compress); a file deleted in the meantime is left out."""
    sink = _Sink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED) as zf:
        for path, name in entries:
            try:
                src = path.open("rb")
            except FileNotFoundError:
                continue
            with src:
                st = os.fstat(src.fileno())
                info = zipfile.ZipInfo(name, date_time=time.localtime(st.st_mtime)[:6])
                info.file_size = st.st_size
                info.external_attr = 0o644 << 16
                with zf.open(info, "w") as dest:
                    while block := src.read(CHUNK):
                        dest.write(block)
                        if chunk := sink.take():
                            yield chunk
            if chunk := sink.take():
                yield chunk
    yield sink.take()
