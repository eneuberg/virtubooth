"""REFERENCE ONLY, never collected (tests/e2e_legacy is in norecursedirs).

Static checks of the pre-overhaul frontend files (virtubooth/static/core,
virtubooth/admin/static, virtubooth/extensions/*/static), which the backend no
longer contains. They are kept verbatim so wave 2 can port the intent to the
new frontend (Vitest or e2e):

- admin pages: expected files, CSP-safe HTML, no unsafe DOM APIs in the JS,
  imports resolve, the live screen cannot delete (AD: port as an e2e/static
  check on the Live screen)
- Beer Cam: page assets, CSP-clean index.html with its test ids, every looked-up
  id exists (AC)
- Fotobox: every catalogue filter has an implementation, CSP rules, every
  looked-up id exists, the outbox store is best effort (AC)
- content blockers: cosmetic rules against the pages' elements and the join
  dialog's names (GP/INT: needs the rendered DOM of the new UI)

Moved here from tests/test_admin_pages.py, test_beer.py, test_booth.py and
test_core_blockers.py by BE-core (wave 1); the old paths below no longer exist.
"""

# ruff: noqa
# fmt: off

# ====================================================== test_admin_pages.py (old)

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

# ============================================== test_beer.py page tests (old)

@pytest.mark.parametrize(
    ("path", "mime"),
    [("beer.js", "text/javascript"), ("shapes.js", "text/javascript"), ("beer.css", "text/css")],
)
def test_page_assets_served(client, path, mime):
    scan(client)
    r = client.get(f"/x/beer/{path}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(mime)


class _CspAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []
        self.testids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        names = dict(attrs)
        if tag == "style":
            self.problems.append("inline <style>")
        if tag == "script" and "src" not in names:
            self.problems.append("inline <script>")
        for name, value in attrs:
            if name == "style":
                self.problems.append(f"style= on <{tag}>")
            if name.startswith("on"):
                self.problems.append(f"{name}= on <{tag}>")
            if name in ("src", "href") and value and re.match(r"^(https?:)?//", value):
                self.problems.append(f"external {name}={value}")
            if name == "data-testid":
                self.testids.add(value)


def test_page_is_csp_clean():
    html = (beer.extension.static_dir / "index.html").read_text(encoding="utf-8")
    audit = _CspAudit()
    audit.feed(html)
    assert audit.problems == []
    assert {"shutter", "frame", "vessel-bottle", "vessel-cup", "success-title", "again"} <= audit.testids
    for js in beer.extension.static_dir.glob("*.js"):
        source = js.read_text(encoding="utf-8")
        assert "innerHTML" not in source, js.name
        assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", source), js.name


def test_every_element_the_page_script_looks_up_exists():
    """beer.js grabs its elements by id once at startup; a missing one breaks the page."""
    static = beer.extension.static_dir
    ids = set(re.findall(r'\bid="([^"]+)"', (static / "index.html").read_text(encoding="utf-8")))
    wanted = set(re.findall(r"\$\('([^']+)'\)", (static / "beer.js").read_text(encoding="utf-8")))
    assert {"goal-long", "goal-short", "retry", "success-num"} <= wanted
    assert wanted <= ids, wanted - ids

# ============================================= test_booth.py page tests (old)

def test_every_catalogue_filter_has_an_implementation():
    source = (STATIC / "filters.js").read_text(encoding="utf-8")
    implemented = re.findall(r"^\s{4}id: '([a-z][a-z0-9-]*)',$", source, re.MULTILINE)
    assert sorted(implemented) == sorted(booth.FILTERS)


def test_static_files_follow_the_csp_rules():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "inline <script>"
    assert "<style" not in html
    assert not re.search(r"\sstyle=", html)
    assert not re.search(r"\son[a-z]+=", html)
    for js in STATIC.glob("*.js"):
        text = js.read_text(encoding="utf-8")
        assert "innerHTML" not in text, js.name
        assert "ctx.filter" not in text, js.name
        assert not re.search(r"https?://", text), f"{js.name}: external URL"


def test_every_element_the_page_script_looks_up_exists():
    """booth.js grabs its elements by id once at startup; a missing one breaks the page."""
    ids = set(re.findall(r'\bid="([^"]+)"', (STATIC / "index.html").read_text(encoding="utf-8")))
    wanted = set(re.findall(r"\$\('([^']+)'\)", (STATIC / "booth.js").read_text(encoding="utf-8")))
    assert {"back", "outbox", "upload-retry", "upload-home"} <= wanted
    assert wanted <= ids, wanted - ids


def test_outbox_store_is_best_effort():
    """Every IndexedDB call of the outbox is wrapped: a phone without storage still works."""
    source = (STATIC / "outbox.js").read_text(encoding="utf-8")
    for name in ("keep", "forget", "kept"):
        body = source.split(f"export async function {name}(", 1)[1].split("\n}\n", 1)[0]
        assert "try {" in body and "catch" in body, name

# =================================== test_core_blockers.py DOM tests (old)

@pytest.fixture
def elements(app) -> list[bl.El]:  # type: ignore[no-untyped-def]
    els = bl.ui_elements(app)
    assert len(els) > 500
    return els




def test_ui_survives_vendored_cosmetic_rules(elements):
    assert cosmetic_hits(elements, vendored_lists()) == []


def test_join_dialog_avoids_cookie_notice_words(elements):
    roots = [e for e in elements if e.attrs.get("data-testid") == "join" and e.origin.endswith("core/vb.js")]
    assert len(roots) == 1, "the join dialog (askConsent in vb.js) was not found"
    dialog = list(roots[0].walk())
    assert any(e.attrs.get("role") == "dialog" for e in dialog)
    names = [v for e in dialog for k, v in e.attrs.items()
             if k in ("class", "id", "data-testid", "aria-labelledby", "for", "name")]
    bad = [n for n in names if any(w in n.lower() for w in COOKIE_NOTICE_WORDS)]
    assert bad == []




def test_ui_survives_full_lists(elements, full_lists):
    assert cosmetic_hits(elements, full_lists) == []
