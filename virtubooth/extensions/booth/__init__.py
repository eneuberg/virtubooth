"""Fotobox: live camera preview with WebGL filters, countdown, save + upload.

The page lives in `static/` (index.html + ES modules, no build step):

- `filters.json`  the filter catalogue: ids, German names, strip order. It is
                  the single source of truth for filter ids: the page loads it
                  and `validate_meta` below only accepts ids listed there.
- `filters.js`    the filter registry: one object per id with the WebGL
                  fragment shader snippet, optional overlay (frame, stickers)
                  and optional Canvas2D fallback.
- `renderer.js`   WebGL1 renderer (+ Canvas2D fallback) for preview and capture.
- `booth.js`      the page: camera, filter strip, swipe, countdown, result.

Photos are 1080×1440 JPEGs (3:4 portrait), exactly what the preview showed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from virtubooth.extension import Extension, UploadContext, UploadPolicy

STATIC_DIR = Path(__file__).resolve().parent / "static"
FILTERS_FILE = STATIC_DIR / "filters.json"

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1440
FACINGS = ("user", "environment")
FILTER_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def load_filters(path: Path = FILTERS_FILE) -> dict[str, str]:
    """Read the filter catalogue → {id: German name}, in strip order."""
    data = json.loads(path.read_text(encoding="utf-8"))
    filters: dict[str, str] = {}
    for entry in data["filters"]:
        fid, name = entry["id"], entry["name"]
        if not FILTER_ID_RE.match(fid):
            raise ValueError(f"{path.name}: invalid filter id {fid!r}")
        if fid in filters:
            raise ValueError(f"{path.name}: duplicate filter id {fid!r}")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path.name}: filter {fid!r} needs a name")
        filters[fid] = name
    if not filters:
        raise ValueError(f"{path.name}: no filters")
    return filters


FILTERS = load_filters()


def validate_meta(meta: dict[str, Any]) -> dict[str, Any]:
    if meta.get("filter") not in FILTERS:
        raise ValueError("Unbekannter Filter.")
    if meta.get("facing") not in FACINGS:
        raise ValueError("Unbekannte Kamera.")
    return {"filter": meta["filter"], "facing": meta["facing"]}


def on_upload(ctx: UploadContext) -> dict[str, Any]:
    return {"booth_number": ctx.photo.seq}


extension = Extension(
    id="booth",
    title="Fotobox",
    emoji="📸",
    tagline="Filter drauf, lächeln, klick! 🤳",
    static_dir=STATIC_DIR,
    upload=UploadPolicy(
        max_side=OUTPUT_HEIGHT,
        min_side=480,
        exact_size=(OUTPUT_WIDTH, OUTPUT_HEIGHT),
        quality=88,
        meta_keys=frozenset({"filter", "facing"}),
        validate_meta=validate_meta,
    ),
    on_upload=on_upload,
    order=20,
    meta_labels={"filter": "Filter", "facing": "Kamera"},
)
