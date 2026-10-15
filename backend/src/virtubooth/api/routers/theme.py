"""The theme for every guest page and the Live Wall (public, no auth).

`GET /api/theme` is JSON, `GET /api/theme.css` the same colours as CSS custom
properties (`--t-<name>`), linked from every guest page's <head>. Both carry
an ETag and answer `If-None-Match` with 304; caches must revalidate."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from ...services.theme import css_variables
from ..deps import CoreDep
from ..schemas.theme import PublicTheme

router = APIRouter(tags=["theme"])

THEME_CACHE = "public, no-cache"


def _not_modified(request: Request, etag: str) -> bool:
    wanted = request.headers.get("if-none-match", "")
    return any(tag.strip() in (etag, "*") for tag in wanted.split(",") if tag.strip())


@router.get("/api/theme", response_model=PublicTheme, responses={304: {"description": "unchanged"}})
def get_theme(request: Request, core: CoreDep) -> Response:
    """The colours of the guest UI and the wall (the default preset when the
    host never saved one)."""
    theme = core.services.theme.public()
    etag = core.services.theme.etag(theme)
    headers = {"ETag": etag, "Cache-Control": THEME_CACHE}
    if _not_modified(request, etag):
        return Response(status_code=304, headers=headers)
    return JSONResponse(theme.model_dump(mode="json"), headers=headers)


@router.get("/api/theme.css", include_in_schema=False)
def get_theme_css(request: Request, core: CoreDep) -> Response:
    theme = core.services.theme.public()
    etag = core.services.theme.etag(theme)
    headers = {"ETag": etag, "Cache-Control": THEME_CACHE}
    if _not_modified(request, etag):
        return Response(status_code=304, headers=headers)
    return Response(css_variables(theme), media_type="text/css", headers=headers)
