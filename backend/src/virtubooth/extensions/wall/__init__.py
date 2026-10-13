"""Live-Wall: the party's photos on a big screen (a TV at `/livewall`).

Not a guest activity: no uploads, not on the home screen. It brings its own
page and screen API under `/livewall` (`web_router`, see screen_api.py), its
admin API under `/api/x/wall/admin/...` (admin_api.py), and a live side that
runs with the app (`on_start`/`on_stop`, hub.py). Photo analysis for the fun
categories comes through the port in enrichment.py.

Settings keys: `x.wall.config` (config.py), `x.wall.password` (auth.py).
Files: `<data>/wall/cache/m/` (media.py).
"""

from __future__ import annotations

from virtubooth.extensions.sdk import Extension

from . import admin_api, screen_api
from .enrichment import Enrichment
from .hub import Wall

EXT_ID = "wall"


def make_extension(enrichment: Enrichment | None = None) -> Extension:
    """The wall extension; `enrichment` replaces the photo analysis (tests)."""
    wall = Wall(enrichment)
    return Extension(
        id=EXT_ID,
        title="Live-Wall",
        emoji="📺",
        tagline="Fotos auf dem großen Bildschirm",
        router=admin_api.build_router(wall),
        show_on_home=False,
        web_router=screen_api.build_router(wall),
        on_start=wall.on_start,
        on_stop=wall.on_stop,
    )


extension = make_extension()
