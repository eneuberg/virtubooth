"""Beer Cam: guests photograph their drink, every photo is one frame of the
"1 million beers" timelapse.

Every upload is a 1080x1440 (3:4 portrait) JPEG framed by the bottle or cup
outline in the browser, so all frames line up. The page lives in `static/`.

POST /api/x/beer/upload   X-VB-Meta {"vessel": "bottle"|"cup", "facing": "user"|"environment"}
                          → 201 {"photo": {...}, "beer_number": seq, "total": n}
GET  /api/x/beer/stats    → {"total": n, "goal": 1000000}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from virtubooth.context import Core
from virtubooth.deps import get_core, require_access
from virtubooth.extension import Extension, UploadContext, UploadPolicy

EXT_ID = "beer"
GOAL = 1_000_000
# the browser captures exactly this (see static/beer.js: captureFrame(video, 1080, 1440))
WIDTH, HEIGHT = 1080, 1440
VESSELS = frozenset({"bottle", "cup"})
FACINGS = frozenset({"user", "environment"})

router = APIRouter()


def total_beers(core: Core) -> int:
    """Every beer photo that still exists (hidden ones count, deleted ones don't)."""
    return core.repo.count_photos(EXT_ID)


@router.get("/stats", dependencies=[Depends(require_access)])
def stats(core: Core = Depends(get_core)) -> dict[str, int]:
    return {"total": total_beers(core), "goal": GOAL}


def validate_meta(meta: dict[str, Any]) -> dict[str, Any]:
    vessel = meta.get("vessel")
    if vessel not in VESSELS:
        raise ValueError("Unbekanntes Gefäß. Flasche oder Becher?")
    clean: dict[str, Any] = {"vessel": vessel}
    facing = meta.get("facing")
    if facing is not None:
        if facing not in FACINGS:
            raise ValueError("Unbekannte Kamera.")
        clean["facing"] = facing
    return clean


def on_upload(ctx: UploadContext) -> dict[str, Any]:
    return {"beer_number": ctx.photo.seq, "total": total_beers(ctx.core)}


extension = Extension(
    id=EXT_ID,
    title="Beer Cam",
    emoji="🍺",
    tagline="Knips dein Bier – auf zur Million!",
    static_dir=Path(__file__).parent / "static",
    upload=UploadPolicy(
        max_side=max(WIDTH, HEIGHT),
        min_side=480,
        quality=85,
        meta_keys=frozenset({"vessel", "facing"}),
        validate_meta=validate_meta,
    ),
    router=router,
    on_upload=on_upload,
    order=10,
    meta_labels={"vessel": "Gefäß", "facing": "Kamera"},
)
