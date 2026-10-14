"""Live-Wall: the party's photos on a big screen (a TV at `/livewall`).

Not a guest activity: no uploads, not on the home screen. It brings its own
page and screen API under `/livewall` (`web_router`, see screen_api.py), its
admin API under `/api/x/wall/admin/...` (admin_api.py, enrich/admin_api.py), a
live side that
runs with the app (`on_start`/`on_stop`, hub.py). Photo analysis for the fun
categories comes through the port in enrichment.py (enrich/: the worker).

Settings keys: `x.wall.config` (config.py), `x.wall.password` (auth.py).
Files: `<data>/wall/cache/m/` (media.py).
"""

from __future__ import annotations

from fastapi import APIRouter

from virtubooth.extensions.sdk import Extension

from . import admin_api, media, screen_api
from .enrich import admin_api as analysis_admin_api
from .enrichment import Enrichment
from .hub import Wall

EXT_ID = "wall"


def make_extension(enrichment: Enrichment | None = None) -> Extension:
    """The wall extension; `enrichment` replaces the photo analysis (tests)."""
    wall = Wall(enrichment)
    # /api/x/wall/admin/...: the wall's settings and the photo analysis
    router = APIRouter()
    router.include_router(admin_api.build_router(wall))
    router.include_router(analysis_admin_api.router)
    return Extension(
        id=EXT_ID,
        title="Live-Wall",
        emoji="📺",
        tagline="Fotos auf dem großen Bildschirm",
        router=router,
        show_on_home=False,
        web_router=screen_api.build_router(wall),
        on_start=wall.on_start,
        on_stop=wall.on_stop,
        derived_files=media.derived_files,
    )


extension = make_extension()
