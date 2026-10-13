"""Photo files for the wall: `s` = the 400 px thumbnail, `m` = a 1280 px
derivative made on first use and cached at `<data>/wall/cache/m/<public_id>.jpg`,
`l` = the stored photo. The cached file goes when the photo is deleted."""

from __future__ import annotations

import logging
import os
import tempfile
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
