"""Photo files for the wall: `s` = the 400 px thumbnail, `m` = a 1280 px
derivative made on first use and cached at `<data>/wall/cache/m/<public_id>.jpg`,
`l` = the stored photo.

The cached copy goes with its photo: deleting a photo removes it with the
photo's own files (`Extension.derived_files`, no event needed), and
`sweep_cache` (at the wall's start, after its translator missed events, and
every SWEEP_SECONDS) removes every copy whose photo is deleted, hidden or
unknown, plus temp files a crash left behind (WALL-02). An unhidden photo
gets a new copy on its next request."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from PIL import Image

from ...domain.models import Photo

if TYPE_CHECKING:
    from ...runtime import Core

log = logging.getLogger("virtubooth.wall")

Size = Literal["s", "m", "l"]
M_SIDE = 1280
M_QUALITY = 82
SWEEP_SECONDS = 3600.0
# a temp file older than this is a leftover (making one copy takes < 1 s)
_TMP_MAX_AGE = 600.0
_CHUNK = 500


def cache_dir(core: Core) -> Path:
    return core.settings.data_dir / "wall" / "cache" / "m"


def cache_path(core: Core, public_id: str) -> Path:
    return cache_dir(core) / f"{public_id}.jpg"


def _make_medium(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as original:
        # JPEG draft mode decodes at a reduced scale: much less memory and time
        original.draft("RGB", (M_SIDE, M_SIDE))
        image = original.convert("RGB")
    image.thumbnail((M_SIDE, M_SIDE), Image.Resampling.LANCZOS)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".m-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            image.save(f, "JPEG", quality=M_QUALITY)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def photo_file(core: Core, photo: Photo, size: Size) -> Path | None:
    """The file to send for `size`, or None when it is missing."""
    original = core.repos.photos.path(photo.extension, photo.filename)
    if size == "s":
        path = core.repos.photos.path(photo.extension, photo.thumb_filename)
        return path if path.is_file() else None
    if size == "l" or max(photo.width, photo.height) <= M_SIDE:
        return original if original.is_file() else None
    cached = cache_path(core, photo.public_id)
    if cached.is_file():
        return cached
    if not original.is_file():
        return None
    try:
        _make_medium(original, cached)
    except OSError:
        log.exception("wall: could not make the 1280 px copy of %s", photo.public_id)
        return original
    return cached


def drop_cached(core: Core, public_id: str) -> None:
    try:
        cache_path(core, public_id).unlink(missing_ok=True)
    except OSError:
        log.warning("wall: could not remove the cached copy of %s", public_id, exc_info=True)


def derived_files(core: Core, public_id: str) -> list[Path]:
    """`Extension.derived_files`: the cached copy goes with the photo."""
    return [cache_path(core, public_id)]


def sweep_cache(core: Core) -> int:
    """Remove the cached copies of photos that are deleted, hidden or unknown,
    and stale temp files. Returns how many files went."""
    folder = cache_dir(core)
    try:
        entries = list(os.scandir(folder))
    except FileNotFoundError:
        return 0
    copies: dict[str, Path] = {}
    leftovers: list[Path] = []
    now = time.time()
    for entry in entries:
        if entry.name.endswith(".jpg") and not entry.name.startswith("."):
            copies[entry.name[:-4]] = Path(entry.path)
        elif entry.name.startswith(".m-") and entry.name.endswith(".tmp"):
            try:
                if now - entry.stat().st_mtime > _TMP_MAX_AGE:
                    leftovers.append(Path(entry.path))
            except OSError:
                continue
    ids = list(copies)
    keep: set[str] = set()
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start : start + _CHUNK]
        marks = ", ".join("?" for _ in chunk)
        keep.update(
            r[0]
            for r in core.db.all(
                f"SELECT public_id FROM photos WHERE public_id IN ({marks}) "
                "AND deleted_at IS NULL AND hidden_at IS NULL",
                chunk,
            )
        )
    removed = 0
    for path in [p for pid, p in copies.items() if pid not in keep] + leftovers:
        try:
            path.unlink(missing_ok=True)
            removed += 1
        except OSError:
            log.warning("wall: could not remove %s", path, exc_info=True)
    if removed:
        log.info("wall: removed %d cached copies of deleted or hidden photos", removed)
    return removed
