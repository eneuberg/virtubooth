"""Fotobox: live camera preview with WebGL filters, countdown, save + upload.

The page lives in the frontend (frontend/src/extensions/booth/). This package
keeps the filter catalogue:

- `filters.json`  ids, German names, icons, strip order. It is the single
                  source of truth for filter ids: `validate_meta` only accepts
                  ids listed there, and the page gets the enabled ones from
                  `GET /api/x/booth/filters`.

The host switches filters off and on in the admin (`/api/admin/x/booth/filters`,
the extension's `admin_router`); at least one stays on. Stored as
`x.booth.filters` = {disabled: [ids], by}: the disabled ones, so a filter added
to filters.json later starts enabled. Guests see the change when the booth next
fetches the catalogue (every 30 s while it is open). Uploads keep accepting
every catalogue id: a photo taken just before the switch may still be on its
way (the outbox drops what the server rejects).

`GET /api/x/booth/stats` → {"next_number": n}: the number the film edge shows
before a guest's first photo (the photo's `booth_number` once it is uploaded).

Photos are 1080×1440 JPEGs (3:4 portrait), exactly what the preview showed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints

from virtubooth.api.deps import AdminDep, CoreDep, require_access
from virtubooth.core import errors
from virtubooth.core.clock import now_iso
from virtubooth.domain.constants import FACINGS, PHOTO_HEIGHT, PHOTO_WIDTH
from virtubooth.extensions.sdk import Extension, UploadContext, UploadPolicy
from virtubooth.repositories.container import Repositories

FILTERS_FILE = Path(__file__).resolve().parent / "filters.json"

EXT_ID = "booth"
OUTPUT_WIDTH = PHOTO_WIDTH
OUTPUT_HEIGHT = PHOTO_HEIGHT
FILTER_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
# settings table: {disabled: [ids], by}
FILTER_SETTINGS_KEY = "x.booth.filters"


class BoothFilter(BaseModel):
    id: str = Field(pattern=FILTER_ID_RE.pattern)
    name: str
    icon: str


class BoothFilters(BaseModel):
    filters: list[BoothFilter] = Field(description="In strip order; the first is the default.")


class BoothStats(BaseModel):
    next_number: int = Field(
        description="The number the next photo gets, unless another guest is faster."
    )


class BoothUploadResult(BaseModel):
    booth_number: int = Field(description="This photo's number (never reused).")


class BoothFilterSetting(BoothFilter):
    enabled: bool


class BoothFilterSettingsOut(BaseModel):
    filters: list[BoothFilterSetting] = Field(
        description="Every filter of the catalogue, in strip order."
    )


FilterId = Annotated[str, StringConstraints(pattern=FILTER_ID_RE.pattern)]


class BoothFiltersIn(BaseModel):
    enabled: list[FilterId] = Field(
        max_length=50,
        description="The filters guests get, at least one (empty: 400 `no_filter_enabled`).",
    )


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


def disabled_filters(repos: Repositories) -> set[str]:
    """The ids the host switched off."""
    raw = repos.app_settings.get(FILTER_SETTINGS_KEY).get("disabled")
    return {f for f in raw if isinstance(f, str)} if isinstance(raw, list) else set()


def enabled_filters(repos: Repositories) -> BoothFilters:
    """The catalogue without the switched-off filters. Never empty: should every
    filter be off (it can't be switched so), the whole catalogue counts."""
    disabled = disabled_filters(repos)
    enabled = [f for f in CATALOGUE.filters if f.id not in disabled]
    return BoothFilters(filters=enabled) if enabled else CATALOGUE


def filter_settings(repos: Repositories) -> BoothFilterSettingsOut:
    disabled = disabled_filters(repos)
    return BoothFilterSettingsOut(
        filters=[
            BoothFilterSetting(**f.model_dump(), enabled=f.id not in disabled)
            for f in CATALOGUE.filters
        ]
    )


router = APIRouter()


@router.get("/filters", dependencies=[Depends(require_access)])
def filters(core: CoreDep) -> BoothFilters:
    """The filters the host has on (ids, German names, icons), in strip order."""
    return enabled_filters(core.repos)


@router.get("/stats", dependencies=[Depends(require_access)])
def stats(core: CoreDep) -> BoothStats:
    """The next photo number. Party access is enough (no join needed), like the
    Beer Cam's counter. Deleted photos keep their numbers (never reused)."""
    return BoothStats(next_number=core.repos.photos.next_seq(EXT_ID))


admin_router = APIRouter()


@admin_router.get("/filters")
def get_filter_settings(core: CoreDep) -> BoothFilterSettingsOut:
    """Every filter with whether guests get it."""
    return filter_settings(core.repos)


@admin_router.put("/filters")
def set_filter_settings(
    body: BoothFiltersIn, core: CoreDep, admin: AdminDep
) -> BoothFilterSettingsOut:
    """Which filters guests get (the others are off). 400 `no_filter_enabled`
    for an empty list, `unknown_filter` for an id not in the catalogue."""
    enabled = set(body.enabled)
    if not enabled:
        raise errors.bad_request("Mindestens ein Filter muss an bleiben.", "no_filter_enabled")
    unknown = [f for f in body.enabled if f not in FILTERS]
    if unknown:
        raise errors.bad_request(f"Unbekannter Filter: {unknown[0]}.", "unknown_filter")
    disabled = [f for f in FILTERS if f not in enabled]  # strip order
    with core.db.tx():
        if set(disabled) != disabled_filters(core.repos):
            at = now_iso()
            core.repos.app_settings.put(
                FILTER_SETTINGS_KEY, {"disabled": disabled, "by": admin.actor}, at=at
            )
            core.repos.audit.log(
                admin.actor, "extension.settings", f"x:{EXT_ID}", {"disabled": disabled}, at=at
            )
            core.services.events.extension_settings(EXT_ID)
        return filter_settings(core.repos)


def validate_meta(meta: dict[str, Any]) -> dict[str, Any]:
    # every catalogue id, switched off or not: a photo taken just before the
    # switch may still be in a guest's outbox
    if meta.get("filter") not in FILTERS:
        raise ValueError("Unbekannter Filter.")
    if meta.get("facing") not in FACINGS:
        raise ValueError("Unbekannte Kamera.")
    return {"filter": meta["filter"], "facing": meta["facing"]}


def on_upload(ctx: UploadContext) -> dict[str, Any]:
    return {"booth_number": ctx.photo.seq}


extension = Extension(
    id=EXT_ID,
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
    admin_router=admin_router,
    on_upload=on_upload,
    upload_result=BoothUploadResult,
    order=20,
    meta_labels={"filter": "Filter", "facing": "Kamera"},
)
