"""Admin pages: gating, CSP-safe markup, assets, and the live screen's limits."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import virtubooth.admin

STATIC = Path(virtubooth.admin.__file__).parent / "static"
ASSETS = STATIC / "assets"
PAGES = ["live", "manage", "user"]
HTML_FILES = sorted(STATIC.glob("*.html"))
JS_FILES = sorted(ASSETS.glob("*.js"))


def js_code(path: Path) -> str:
    """The script without // comments (they may name what the code avoids)."""
    return re.sub(r"^\s*//.*$|\s//\s.*$", "", path.read_text(encoding="utf-8"), flags=re.M)


def test_expected_files_exist():
    assert {p.stem for p in HTML_FILES} == {"login", *PAGES}
    assert {p.name for p in JS_FILES} >= {"admin.js", "login.js", "live.js", "manage.js", "user.js"}
    assert (ASSETS / "admin.css").is_file()


@pytest.mark.parametrize("page", PAGES)
def test_pages_need_admin(client, guest, page):
    r = client.get(f"/admin/{page}")
    assert r.status_code == 303
    assert r.headers["location"] == f"/admin/login?next=/admin/{page}"
    assert guest().get(f"/admin/{page}").status_code == 303


@pytest.mark.parametrize("page", PAGES)
def test_pages_served_to_admin(admin, page):
    r = admin.get(f"/admin/{page}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert f'src="/admin/assets/{page}.js"' in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_login_page_is_public(client):
    r = client.get("/admin/login?next=/admin/manage")
    assert r.status_code == 200 and 'id="password"' in r.text


def test_assets_are_public_with_right_types(client):
    r = client.get("/admin/assets/admin.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert client.get("/admin/assets/admin.css").headers["content-type"].startswith("text/css")
    assert client.get("/admin/assets/%2e%2e/api.py").status_code == 404
    assert client.get("/admin/assets/nope.js").status_code == 404


@pytest.mark.parametrize("path", HTML_FILES, ids=lambda p: p.name)
def test_html_is_csp_safe(path):
    html = path.read_text(encoding="utf-8")
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) is None, "inline <script>"
    assert "<style" not in html, "inline <style>"
    assert re.search(r"\sstyle\s*=", html) is None, "style attribute"
    assert re.search(r"\son[a-z]+\s*=", html) is None, "inline event handler"
    assert re.search(r'(src|href)="(https?:)?//', html) is None, "external resource"
    assert '<html lang="de">' in html


@pytest.mark.parametrize("path", HTML_FILES, ids=lambda p: p.name)
def test_html_references_resolve(admin, path):
    html = path.read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="(/(?:admin/assets|static/core)/[^"]+)"', html)
    assert refs
    for ref in refs:
        assert admin.get(ref).status_code == 200, ref


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_js_avoids_unsafe_dom_and_csp_traps(path):
    js = js_code(path)
    for bad in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "eval(",
        "new Function",
        "document.write",
    ):
        assert bad not in js, bad
    # h(tag, {style: ...}) would set a style attribute, which the CSP blocks
    assert re.search(r"\bstyle\s*:", js) is None
    assert "setAttribute('style'" not in js and 'setAttribute("style"' not in js


def test_js_imports_resolve():
    for path in JS_FILES:
        for spec in re.findall(r"from '([^']+)'", path.read_text(encoding="utf-8")):
            if spec.startswith("./"):
                assert (ASSETS / spec[2:]).is_file(), (path.name, spec)
            else:
                assert spec == "/static/core/vb.js", (path.name, spec)


def test_live_screen_cannot_delete():
    """The host's rule: the live screen only takes photos down and back up."""
    js = js_code(ASSETS / "live.js")
    html = (STATIC / "live.html").read_text(encoding="utf-8")
    for needle in (
        "'DELETE'", "'delete'", "Löschen", "/bulk", "deletePhoto", "confirmAndDelete",
        "managementActions", "photoTile",
    ):  # fmt: skip
        assert needle not in js, needle
    # it does listen for deletions made elsewhere, to drop those cards
    assert "photo.deleted" in js
    assert "Löschen" not in html and "delete" not in html
