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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from virtubooth.extensions.sdk import Extension
    from virtubooth.runtime import Core

    from .enrichment import Enrichment

EXT_ID = "wall"


def make_extension(enrichment: Enrichment | None = None) -> Extension:
    """The wall extension; `enrichment` replaces the photo analysis (tests)."""
    # imported here, not at the top: the analysis worker imports this package
    # (as the parent of enrich/) and needs none of the web side (FastAPI)
    from fastapi import APIRouter

    from virtubooth.extensions.sdk import Extension

    from . import admin_api, media, screen_api
    from .enrich import admin_api as analysis_admin_api
    from .hub import Wall
    from .llm import admin_api as llm_admin_api
    from .llm.service import LlmRuntime

    wall = Wall(enrichment)
    llm = LlmRuntime()
    # /api/x/wall/admin/...: the wall's settings and the photo analysis
    router = APIRouter()
    router.include_router(admin_api.build_router(wall))
    router.include_router(analysis_admin_api.router)
    router.include_router(llm_admin_api.router)
    return Extension(
        id=EXT_ID,
        title="Live-Wall",
        emoji="📺",
        tagline="Fotos auf dem großen Bildschirm",
        router=router,
        show_on_home=False,
        web_router=screen_api.build_router(wall),
        on_start=_both(wall.on_start, llm.on_start),
        on_stop=_both(llm.on_stop, wall.on_stop),
        derived_files=media.derived_files,
    )


def __getattr__(name: str) -> Extension:
    """`extension` (what discover_extensions reads) is made on first access."""
    if name == "extension":
        ext = make_extension()
        globals()["extension"] = ext
        return ext
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _both(first: Callable[[Core], None], second: Callable[[Core], None]) -> Callable[[Core], None]:
    """Run two lifecycle hooks in order; the second runs even if the first fails.
    Like a bound method, the result's `__self__` is the first hook's owner (the
    wall tests reach the hub through `on_start.__self__`)."""

    def run(core: Core) -> None:
        try:
            first(core)
        finally:
            second(core)

    run.__self__ = getattr(first, "__self__", None)  # type: ignore[attr-defined]
    return run
