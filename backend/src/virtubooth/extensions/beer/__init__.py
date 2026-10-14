"""Beer Cam: guests photograph their drink, every photo is one frame of the
"1 million beers" timelapse.

Every upload is a 1080x1440 (3:4 portrait) JPEG framed by the bottle or cup
outline in the browser, so all frames line up. The page lives in the frontend
(frontend/src/extensions/beer/).

POST /api/x/beer/upload   X-VB-Meta {"vessel": "bottle"|"cup", "facing": "user"|"environment"}
                          → 201 {"photo": {...}, "beer_number": seq, "total": n}
GET  /api/x/beer/stats    → {"total": n, "goal": 1000000, "next_number": seq}

Two numbers: `total` is the board (visible, not deleted beers: what counts towards
the million), a beer's own number is its photo's `seq` (never reused; the frame
number the guest sees on the print, in "Deine Bilder" and in the file name).
"""

from __future__ import annotations

from typing import Any, Final, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from virtubooth.api.deps import CoreDep, require_access
from virtubooth.domain.constants import FACING_NAMES, FACINGS, PHOTO_HEIGHT, PHOTO_WIDTH
from virtubooth.extensions.sdk import Extension, UploadContext, UploadPolicy
from virtubooth.runtime import Core

EXT_ID = "beer"
GOAL: Final = 1_000_000
# the browser captures exactly this
WIDTH, HEIGHT = PHOTO_WIDTH, PHOTO_HEIGHT
VESSELS = frozenset({"bottle", "cup"})

router = APIRouter()


class BeerStats(BaseModel):
    total: int = Field(description="Beers on the board: visible, not deleted.")
    goal: Literal[1_000_000]
    next_number: int = Field(
        description="The number the next beer gets (its seq), unless another guest is faster."
    )


class BeerUploadResult(BaseModel):
    beer_number: int = Field(description="This photo's number (never reused).")
    total: int = Field(description="Beers on the board now (what the counter shows).")


def total_beers(core: Core) -> int:
    """Beers on the board: photos an admin took down or deleted don't count."""
    return core.repos.photos.count(EXT_ID, hidden=False)


@router.get("/stats", dependencies=[Depends(require_access)])
def stats(core: CoreDep) -> BeerStats:
    """The counter. Party access is enough (no join needed)."""
    return BeerStats(
        total=total_beers(core), goal=GOAL, next_number=core.repos.photos.next_seq(EXT_ID)
    )


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
    tagline="Fotografier dein Getränk im Umriss.",
    upload=UploadPolicy(
        max_side=max(WIDTH, HEIGHT),
        min_side=480,
        # every frame of the timelapse has the same shape
        exact_size=(WIDTH, HEIGHT),
        quality=85,
        meta_keys=frozenset({"vessel", "facing"}),
        validate_meta=validate_meta,
    ),
    router=router,
    on_upload=on_upload,
    upload_result=BeerUploadResult,
    order=10,
    meta_labels={"vessel": "Gefäß", "facing": "Kamera"},
    meta_values={"vessel": {"bottle": "Flasche", "cup": "Becher"}, "facing": FACING_NAMES},
)
