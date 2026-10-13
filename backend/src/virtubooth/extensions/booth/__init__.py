"""Fotobox: live camera preview with WebGL filters, countdown, save + upload.

The page lives in the frontend (frontend/src/extensions/booth/). This package
keeps the filter catalogue:

- `filters.json`  ids, German names, icons, strip order. It is the single
                  source of truth for filter ids: `validate_meta` only accepts
                  ids listed there, and the page gets it from
                  `GET /api/x/booth/filters`.

Photos are 1080×1440 JPEGs (3:4 portrait), exactly what the preview showed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from virtubooth.api.deps import require_access
from virtubooth.domain.constants import FACINGS, PHOTO_HEIGHT, PHOTO_WIDTH
from virtubooth.extensions.sdk import Extension, UploadContext, UploadPolicy

FILTERS_FILE = Path(__file__).resolve().parent / "filters.json"

OUTPUT_WIDTH = PHOTO_WIDTH
OUTPUT_HEIGHT = PHOTO_HEIGHT
FILTER_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


class BoothFilter(BaseModel):
    id: str = Field(pattern=FILTER_ID_RE.pattern)
    name: str
    icon: str


class BoothFilters(BaseModel):
    filters: list[BoothFilter] = Field(description="In strip order; the first is the default.")


class BoothUploadResult(BaseModel):
    booth_number: int = Field(description="This photo's number (never reused).")


def load_catalogue(path: Path = FILTERS_FILE) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = data["filters"]
    return entries


def load_filters(path: Path = FILTERS_FILE) -> dict[str, str]:
    """Read the filter catalogue → {id: German name}, in strip order."""
    filters: dict[str, str] = {}
    for entry in load_catalogue(path):
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
CATALOGUE = BoothFilters(filters=[BoothFilter.model_validate(e) for e in load_catalogue()])

router = APIRouter()


@router.get("/filters", dependencies=[Depends(require_access)])
def filters() -> BoothFilters:
    """The filter catalogue (ids, German names, icons) in strip order."""
    return CATALOGUE


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
    tagline="Selfie mit Filter und Countdown.",
    upload=UploadPolicy(
        max_side=OUTPUT_HEIGHT,
        min_side=480,
        exact_size=(OUTPUT_WIDTH, OUTPUT_HEIGHT),
        quality=88,
        meta_keys=frozenset({"filter", "facing"}),
        validate_meta=validate_meta,
    ),
    router=router,
    on_upload=on_upload,
    upload_result=BoothUploadResult,
    order=20,
    meta_labels={"filter": "Filter", "facing": "Kamera"},
)
