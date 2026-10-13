"""The built frontend (`VB_WEB_DIR`, Vite's `dist`): HTML entries, assets, gate.

Contract with the frontend build (docs/overhaul/contracts/web-serving.md):

- `index.html` (guest app), `admin.html` (admin app), `gate.html` (static page
  for "no access" and "not found", both HTTP 404) in the root;
- hashed files in `assets/`, optionally with precompressed `.br` / `.gz` siblings;
- of the other root files only PUBLIC_ROOT_FILES are served (`boot-check.js`,
  `gate-hint.js`, the icons, `robots.txt`), without any cookie; everything
  else in the root (the HTML entries' `.br`/`.gz` siblings, files a future
  build step drops there) is not found;
- `gate.html` contains `data-vb-mode="gate"` exactly once (on `<html>`); the
  not-found variant is the same file with it rewritten to `data-vb-mode="notfound"`.
  The response also says `X-VB-Page: gate|notfound`. No script is needed.

Without a web dir the app refuses to start, unless VB_DEV=1: then built-in
placeholder pages keep the API usable (e.g. for `vite dev` on :5173).
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from starlette.responses import FileResponse, HTMLResponse, Response

from ..settings import ConfigError, Settings

log = logging.getLogger("virtubooth.web")

ENTRIES = ("index.html", "admin.html", "gate.html")
GATE_PLACEHOLDER = 'data-vb-mode="gate"'
NOT_FOUND_MARK = 'data-vb-mode="notfound"'
PageMode = Literal["gate", "notfound"]

# the HTML differs with the cookies (app, gate, login redirect): never in a shared cache
HTML_CACHE = "private, no-cache"
ASSET_CACHE = "public, max-age=31536000, immutable"
PUBLIC_FILE_CACHE = "public, max-age=300"
# root files of the build served to anyone (Vite copies frontend/public/ there)
PUBLIC_ROOT_FILES = frozenset(
    {
        "boot-check.js",
        "gate-hint.js",
        "icon.svg",
        "favicon.ico",
        "apple-touch-icon.png",
        "robots.txt",
    }
)
# precompressed siblings, in order of preference
ENCODINGS = (("br", ".br"), ("gzip", ".gz"))

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("font/woff2", ".woff2")


def safe_path(base: Path, rel: str) -> Path | None:
    """`rel` inside `base` as a file: no traversal, no dotfiles, no directories."""
    if not rel or "\x00" in rel or "\\" in rel:
        return None
    if any(part.startswith(".") for part in rel.split("/") if part):
        return None
    root = base.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def safe_route(rest: str) -> bool:
    """A client-side route (the part after /x/<id>/ or /admin/): no dot segments,
    no NUL or backslash. The HTML is the same for every route; this only keeps
    probes like `/x/beer/.env` on the 404 page."""
    if "\x00" in rest or "\\" in rest:
        return False
    return not any(part.startswith(".") for part in rest.split("/") if part)


def _media_type(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(path.name)
    return media_type or "application/octet-stream"


@dataclass(frozen=True)
class _Html:
    mtime_ns: int
    size: int
    text: str
    etag: str


# Built-in pages for VB_DEV=1 without a web dir: plain HTML, CSP-clean (no
# inline script or style), same contract as the real ones.
_PLACEHOLDERS = {
    "index.html": (
        "<!doctype html>\n"
        '<html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>virtubooth (dev)</title></head><body>"
        '<main data-testid="dev-placeholder"><h1>virtubooth</h1>'
        "<p>Das Frontend ist nicht gebaut (VB_DEV=1). Nutze <code>pnpm dev</code> "
        "auf :5173 oder setze VB_WEB_DIR.</p></main></body></html>\n"
    ),
    "admin.html": (
        "<!doctype html>\n"
        '<html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>virtubooth Admin (dev)</title></head><body>"
        '<main data-testid="dev-placeholder"><h1>virtubooth Admin</h1>'
        "<p>Das Frontend ist nicht gebaut (VB_DEV=1).</p></main></body></html>\n"
    ),
    "gate.html": (
        "<!doctype html>\n"
        f'<html lang="de" {GATE_PLACEHOLDER}><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>virtubooth</title></head><body>"
        '<main data-testid="gate"><h1 class="when-gate">Scan den QR-Code</h1>'
        '<h1 class="when-notfound">Hier ist nichts</h1></main></body></html>\n'
    ),
}


class WebFrontend:
    """Serves one web dir (or the dev placeholders when `root` is None)."""

    def __init__(self, root: Path | None) -> None:
        self.root = root
        self._html: dict[str, _Html] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> WebFrontend:
        root = settings.web_dir
        if root is None or not root.is_dir():
            if settings.dev:
                if root is not None:
                    log.warning("VB_WEB_DIR %s does not exist: serving placeholder pages", root)
                return cls(None)
            where = f"VB_WEB_DIR={root}" if root is not None else "VB_WEB_DIR is not set and"
            raise ConfigError(
                f"{where} no built frontend was found (expected frontend/dist with "
                "index.html, admin.html and gate.html). Build it (`pnpm build` in "
                "frontend/), point VB_WEB_DIR at it, or set VB_DEV=1 for placeholder pages."
            )
        missing = [name for name in ENTRIES if not (root / name).is_file()]
        if missing:
            raise ConfigError(f"VB_WEB_DIR={root} lacks {', '.join(missing)}")
        return cls(root)

    # ----------------------------------------------------------------- html

    def _read(self, name: str) -> _Html:
        if self.root is None:
            text = _PLACEHOLDERS[name]
            return _Html(0, len(text), text, _etag(text))
        path = self.root / name
        stat = path.stat()
        cached = self._html.get(name)
        if cached and (cached.mtime_ns, cached.size) == (stat.st_mtime_ns, stat.st_size):
            return cached
        text = path.read_text(encoding="utf-8")
        entry = _Html(stat.st_mtime_ns, stat.st_size, text, _etag(text))
        self._html[name] = entry
        return entry

    def _html_response(
        self, text: str, etag: str, status: int, page: str | None = None
    ) -> HTMLResponse:
        headers = {"Cache-Control": HTML_CACHE, "ETag": etag}
        if page is not None:
            headers["X-VB-Page"] = page
        return HTMLResponse(text, status_code=status, headers=headers)

    def guest_app(self) -> HTMLResponse:
        page = self._read("index.html")
        return self._html_response(page.text, page.etag, 200)

    def admin_app(self) -> HTMLResponse:
        page = self._read("admin.html")
        return self._html_response(page.text, page.etag, 200)

    def page_404(self, mode: PageMode) -> HTMLResponse:
        """gate.html as a 404: "scan the QR code" (gate) or "nothing here" (notfound)."""
        page = self._read("gate.html")
        text = page.text
        if mode == "notfound":
            if GATE_PLACEHOLDER in text:
                text = text.replace(GATE_PLACEHOLDER, NOT_FOUND_MARK, 1)
            else:
                log.warning(
                    "gate.html has no %s: the 404 page shows the gate text", GATE_PLACEHOLDER
                )
        return self._html_response(text, _etag(text), 404, mode)

    def gate(self) -> HTMLResponse:
        return self.page_404("gate")

    def not_found(self) -> HTMLResponse:
        return self.page_404("notfound")

    # --------------------------------------------------------------- files

    def asset(self, rel: str, accept_encoding: str) -> Response | None:
        """A hashed build file: cached for a year, precompressed when possible."""
        if self.root is None or rel.endswith((".br", ".gz")):
            return None
        path = safe_path(self.root / "assets", rel)
        if path is None:
            return None
        headers = {"Cache-Control": ASSET_CACHE, "Vary": "Accept-Encoding"}
        accepted = _accepted_encodings(accept_encoding)
        for encoding, suffix in ENCODINGS:
            sibling = path.with_name(path.name + suffix)
            if encoding in accepted and sibling.is_file():
                headers["Content-Encoding"] = encoding
                return FileResponse(sibling, media_type=_media_type(path), headers=headers)
        return FileResponse(path, media_type=_media_type(path), headers=headers)

    def public_file(self, name: str) -> Response | None:
        """A root file of the build on the allow-list (boot-check.js, icon.svg, ...)."""
        if self.root is None or name not in PUBLIC_ROOT_FILES:
            return None
        path = safe_path(self.root, name)
        if path is None:
            return None
        return FileResponse(
            path, media_type=_media_type(path), headers={"Cache-Control": PUBLIC_FILE_CACHE}
        )


def _etag(text: str) -> str:
    return '"' + hashlib.sha256(text.encode()).hexdigest()[:20] + '"'


def _accepted_encodings(header: str) -> set[str]:
    """Content codings the client accepts (q=0 excluded)."""
    accepted: set[str] = set()
    for item in header.split(","):
        token, _, params = item.strip().partition(";")
        coding = token.strip().lower()
        if not coding:
            continue
        q = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    q = float(value)
                except ValueError:
                    q = 0.0
        if q > 0:
            accepted.add(coding)
    return accepted
