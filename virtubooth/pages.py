"""HTML pages: home, extension pages, admin pages, the "scan the QR code" gate."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from .context import Core
from .deps import admin_from_cookie, get_core, has_access, require_access

PKG_DIR = Path(__file__).resolve().parent
STATIC_DIR = PKG_DIR / "static"
CORE_STATIC = STATIC_DIR / "core"
ADMIN_STATIC = PKG_DIR / "admin" / "static"

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/manifest+json", ".webmanifest")

router = APIRouter()


def _html(name: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse((CORE_STATIC / name).read_text(encoding="utf-8"), status_code=status)


def gate_page() -> HTMLResponse:
    """Shown for every page request without a valid party QR scan."""
    return _html("gate.html", 404)


def not_found_page() -> HTMLResponse:
    return _html("notfound.html", 404)


def safe_file(base: Path, rel: str) -> Path | None:
    """Resolve `rel` inside `base`, refusing traversal, dotfiles and directories."""
    if "\x00" in rel or "\\" in rel:
        return None
    if any(part.startswith(".") for part in rel.split("/") if part):
        return None
    root = base.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def _file(path: Path) -> FileResponse:
    media_type, _ = mimetypes.guess_type(path.name)
    return FileResponse(path, media_type=media_type or "application/octet-stream")


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, bool]:
    return {"ok": True}


@router.get("/", include_in_schema=False)
def home(request: Request, core: Core = Depends(get_core)) -> Response:
    if not has_access(request, core):
        return gate_page()
    return _html("home.html")


@router.get("/api/extensions", dependencies=[Depends(require_access)])
def list_extensions(core: Core = Depends(get_core)) -> dict:
    return {
        "party_name": core.settings.party_name,
        "instagram_account": core.settings.instagram_account,
        "extensions": [e.public_view() for e in core.extensions.values() if e.show_on_home],
    }


@router.get("/x/{ext_id}", include_in_schema=False)
def extension_root(ext_id: str) -> RedirectResponse:
    return RedirectResponse(f"/x/{quote(ext_id)}/", status_code=308)


@router.get("/x/{ext_id}/{rel:path}", include_in_schema=False)
def extension_file(
    ext_id: str, rel: str, request: Request, core: Core = Depends(get_core)
) -> Response:
    if not has_access(request, core):
        return gate_page()
    ext = core.extensions.get(ext_id)
    if ext is None:
        return not_found_page()
    path = safe_file(ext.static_dir, rel or "index.html")
    return _file(path) if path else not_found_page()


# ------------------------------------------------------------------ admin


@router.get("/admin", include_in_schema=False)
def admin_root() -> RedirectResponse:
    return RedirectResponse("/admin/live", status_code=303)


@router.get("/admin/login", include_in_schema=False)
def admin_login_page() -> Response:
    path = safe_file(ADMIN_STATIC, "login.html")
    return _file(path) if path else not_found_page()


@router.get("/admin/assets/{rel:path}", include_in_schema=False)
def admin_asset(rel: str) -> Response:
    path = safe_file(ADMIN_STATIC / "assets", rel)
    return _file(path) if path else not_found_page()


@router.get("/admin/{page}", include_in_schema=False)
def admin_page(page: str, request: Request, core: Core = Depends(get_core)) -> Response:
    if admin_from_cookie(request, core) is None:
        return RedirectResponse(f"/admin/login?next=/admin/{quote(page)}", status_code=303)
    if not page.replace("-", "").isalnum():
        return not_found_page()
    path = safe_file(ADMIN_STATIC, f"{page}.html")
    return _file(path) if path else not_found_page()
