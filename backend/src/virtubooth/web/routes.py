"""HTML pages and static files of the built frontend (not part of the API schema).

| Path                     | Answer                                                    |
|--------------------------|-----------------------------------------------------------|
| `/`, `/x/<id>/<route>`   | access → index.html; no access → gate (404); unknown or    |
|                          | disabled extension → not found (404)                      |
| `/x/<id>`                | 308 → `/x/<id>/`                                          |
| `/admin`, `/admin/`      | 303 → `/admin/live`                                       |
| `/admin/login`           | admin.html (public)                                       |
| `/admin/<route>`         | session → admin.html; else 303 `/admin/login?next=<path+query>` |
| `/assets/<file>`         | public, immutable, precompressed `.br`/`.gz` sibling       |
| `/<file>`                | an allow-listed root file of the build (boot-check.js,    |
|                          | icon.svg, ...: `PUBLIC_ROOT_FILES`), served by the 404    |
|                          | handler (`not_found_page`)                                |
| anything else            | not found (404), or the gate (404) without access          |
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from ..api.deps import CoreDep, admin_from_cookie, has_access
from .frontend import safe_route

router = APIRouter(include_in_schema=False)


@router.get("/")
def home(request: Request, core: CoreDep) -> Response:
    if not has_access(request, core):
        return core.web.gate()
    return core.web.guest_app()


@router.get("/x/{ext_id}")
def extension_root(ext_id: str) -> Response:
    return RedirectResponse(f"/x/{quote(ext_id)}/", status_code=308)


@router.get("/x/{ext_id}/{rest:path}")
def extension_page(ext_id: str, rest: str, request: Request, core: CoreDep) -> Response:
    if not has_access(request, core):
        return core.web.gate()
    if ext_id not in core.extensions or not safe_route(rest):
        return core.web.not_found()
    return core.web.guest_app()


@router.get("/admin")
def admin_root() -> Response:
    return RedirectResponse("/admin/live", status_code=303)


@router.get("/admin/login")
def admin_login(core: CoreDep) -> Response:
    return core.web.admin_app()


@router.get("/admin/{rest:path}")
def admin_page(rest: str, request: Request, core: CoreDep) -> Response:
    if not rest:
        return RedirectResponse("/admin/live", status_code=303)
    if admin_from_cookie(request, core) is None:
        target = f"/admin/{rest}" + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/admin/login?next={quote(target, safe='/')}", status_code=303)
    if not safe_route(rest):
        return core.web.not_found()
    return core.web.admin_app()


@router.get("/assets/{rel:path}")
def asset(rel: str, request: Request, core: CoreDep) -> Response:
    response = core.web.asset(rel, request.headers.get("accept-encoding", ""))
    return response if response is not None else _not_found(request, core)


def not_found_page(request: Request, core: CoreDep) -> Response:
    """For every other GET: an allow-listed root file of the build, else the 404 page
    (the gate without access: every unknown page says "scan the QR code" too)."""
    name = request.url.path.removeprefix("/")
    if request.method in ("GET", "HEAD"):
        response = core.web.public_file(name)
        if response is not None:
            return response
    return _not_found(request, core)


def _not_found(request: Request, core: CoreDep) -> Response:
    return core.web.not_found() if has_access(request, core) else core.web.gate()
