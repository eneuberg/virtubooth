"""Checks the backend makes on the frontend (retargeted from the old static
file tests). They run on frontend/src and frontend/dist when those exist and
skip otherwise; the HTML rules also run on the stub build the tests serve.

- built HTML is CSP-safe (no inline script/style, no style=/on*= attributes,
  no external resources) and German;
- every /assets/ or root file a built page references exists;
- gate.html carries the mode placeholder the server rewrites (web-serving.md);
- frontend sources avoid DOM APIs that inject HTML or code;
- the extension folders match the backend's extensions.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from virtubooth.extensions.sdk import discover_extensions
from virtubooth.settings import DEFAULT_WEB_DIR, REPO_ROOT
from virtubooth.web.frontend import ENTRIES, GATE_PLACEHOLDER

from ..conftest import STUB_WEB

FRONTEND = REPO_ROOT / "frontend"
SRC = FRONTEND / "src"
WEB_DIRS = [STUB_WEB] + ([DEFAULT_WEB_DIR] if DEFAULT_WEB_DIR.is_dir() else [])
BUILT_HTML = [d / name for d in WEB_DIRS for name in ENTRIES]


class _CspAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []
        self.refs: list[str] = []
        self.lang: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = dict(attrs)
        if tag == "html":
            self.lang = names.get("lang")
        if tag == "style":
            self.problems.append("inline <style>")
        if tag == "script" and "src" not in names:
            self.problems.append("inline <script>")
        for name, value in attrs:
            if name == "style":
                self.problems.append(f"style= on <{tag}>")
            if name.startswith("on"):
                self.problems.append(f"{name}= on <{tag}>")
            if name in ("src", "href") and value:
                if re.match(r"^(https?:)?//", value):
                    self.problems.append(f"external {name}={value}")
                elif value.startswith("/") and not value.startswith("//"):
                    self.refs.append(value)


def _audit(path: Path) -> _CspAudit:
    audit = _CspAudit()
    audit.feed(path.read_text(encoding="utf-8"))
    return audit


@pytest.mark.parametrize("path", BUILT_HTML, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_built_html_is_csp_safe(path):
    audit = _audit(path)
    assert audit.problems == []
    assert audit.lang == "de"


@pytest.mark.parametrize("path", BUILT_HTML, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_built_html_references_resolve(path):
    root = path.parent
    for ref in _audit(path).refs:
        target = ref.split("?")[0].split("#")[0]
        if not target.startswith("/assets/") and target.count("/") != 1:
            continue  # links to pages (e.g. href="/") are routes, not files
        if target == "/":
            continue
        assert (root / target.lstrip("/")).is_file(), f"{path.name}: {ref}"


@pytest.mark.parametrize("web", WEB_DIRS, ids=lambda d: d.parent.name)
def test_gate_has_the_mode_placeholder_once(web):
    text = (web / "gate.html").read_text(encoding="utf-8")
    assert text.count(GATE_PLACEHOLDER) == 1


def _sources() -> list[Path]:
    if not SRC.is_dir():
        pytest.skip("frontend/src does not exist yet")
    files = [
        p for p in SRC.rglob("*")
        if p.suffix in (".ts", ".tsx", ".js", ".jsx") and "node_modules" not in p.parts
    ]  # fmt: skip
    return [p for p in files if ".test." not in p.name and ".gen." not in p.name]


UNSAFE = ("innerHTML", "outerHTML", "insertAdjacentHTML", "dangerouslySetInnerHTML",
          "document.write", "new Function", "eval(")  # fmt: skip


def test_sources_avoid_unsafe_dom_and_csp_traps():
    """No HTML strings into the DOM, no code from strings (the CSP forbids eval)."""
    bad = []
    for path in _sources():
        code = re.sub(r"//.*$|/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.M | re.S)
        bad += [f"{path.relative_to(SRC)}: {word}" for word in UNSAFE if word in code]
    assert bad == []


def test_extension_folders_match_the_backend():
    folder = SRC / "extensions"
    if not folder.is_dir():
        pytest.skip("frontend/src/extensions does not exist yet")
    frontend_ids = {p.name for p in folder.iterdir() if p.is_dir() and not p.name.startswith("_")}
    assert frontend_ids == {e.id for e in discover_extensions()}
