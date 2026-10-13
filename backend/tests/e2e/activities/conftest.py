"""Fixtures and helpers for the camera activities (Beer Cam, Fotobox).

Guests join through the API (`join_via_api`): the join sheet belongs to the guest
platform's tests. Moderation states (paused, stopped, banned) are set through the
admin API, like the host would.
"""

from __future__ import annotations

import io
import os
import secrets
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from playwright.sync_api import APIRequestContext, FloatRect, Locator, Page, Playwright, expect

from virtubooth.domain.models import Photo, PhotoQuery

from ...conftest import ADMIN_PASSWORD
from ..conftest import (
    BROWSER_NAME,
    LOADED,
    LiveServer,
    join_via_api,
    new_context,
    track_errors,
)

READY = 20_000  # ms: software WebGL in CI is slow
# read at import: tests/conftest.py's autouse clean_env removes every VB_* variable
# before a test runs (so the shared conftest's shot() never sees it)
SCREENSHOT_DIR = os.environ.get("VB_SCREENSHOT_DIR")

# ---------------------------------------------------------------- guests


def fonts_ready(page: Page) -> None:
    """Wait for the web fonts and Start's requests in flight: Firefox logs a font download
    that a navigation aborts as a console error (NS_BINDING_ABORTED), WebKit an aborted
    fetch ("… due to access control checks"); neither is the page's fault. And a ban that
    lands while "Deine Bilder" is still loading answers it with a 403."""
    if page.get_by_test_id("start").count():  # Start: the beer counter brings the Doto font
        page.get_by_test_id("beer-count").wait_for()
        expect(page.get_by_test_id("my-photos")).not_to_have_attribute("data-state", "loading")
    page.evaluate("() => document.fonts.ready.then(() => null)")


@pytest.fixture
def guest(page: Page, live: LiveServer) -> Page:
    """A joined guest on "/" (fonts loaded, so the next navigation aborts nothing)."""
    join_via_api(page, live)
    fonts_ready(page)
    return page


@pytest.fixture
def pc(browser, live: LiveServer) -> Iterator[Page]:
    """A joined guest at a PC: 1280×800, mouse, one 16:9 webcam with a test card."""
    ctx = new_context(browser, "desktop")
    page = track_errors(ctx.new_page())
    join_via_api(page, live)
    fonts_ready(page)
    yield page
    ctx.close()


def open_beer(page: Page, live: LiveServer, query: str = "") -> None:
    fonts_ready(page)
    page.goto(live.url(f"/x/beer/{query}"), wait_until=LOADED)
    expect(page.get_by_test_id("beer-app")).to_have_attribute("data-ready", "1", timeout=READY)
    expect(page.get_by_test_id("shutter")).to_be_enabled()
    fonts_ready(page)


def open_booth(page: Page, live: LiveServer, query: str = "") -> None:
    fonts_ready(page)
    page.goto(live.url(f"/x/booth/{query}"), wait_until=LOADED)
    expect(page.get_by_test_id("booth")).to_have_attribute("data-ready", "1", timeout=READY)
    expect(page.get_by_test_id("filter-strip")).to_be_visible()
    fonts_ready(page)


def settled_box(locator: Locator) -> FloatRect | None:
    """The element's bounding box once it stands still. ActivityShell re-measures its
    layout a frame after the content changes (a ResizeObserver sets --vb-reserve in the
    next animation frame), so a box read right after a change (the print appears, the
    status text grows) can be one frame early; on a busy machine that frame comes late.
    Waits until the box is the same for 3 frames (at most ~2 s). Not right before a
    screenshot of a WebGL canvas: WebKit then sometimes captures it black."""
    locator.evaluate(
        """async (el) => {
            const frame = () => new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
            const where = () => { const r = el.getBoundingClientRect(); return [r.x, r.y, r.width, r.height].join(); };
            const still = async () => {
                let last = where();
                for (let i = 0, same = 0; i < 120 && same < 3; i++) {
                    await frame();
                    const now = where();
                    same = now === last ? same + 1 : 0;
                    last = now;
                }
            };
            // page.evaluate has no timeout of its own
            await Promise.race([still(), new Promise((resolve) => setTimeout(resolve, 3000))]);
        }"""
    )
    return locator.bounding_box()


def select_filter(page: Page, filter_id: str) -> None:
    page.get_by_test_id(f"filter-{filter_id}").click()
    expect(page.get_by_test_id("booth")).to_have_attribute("data-filter", filter_id)


def expect_uploaded(page: Page) -> None:
    expect(page.get_by_test_id("upload-status")).to_have_attribute(
        "data-state", "done", timeout=READY
    )


def shoot(page: Page) -> None:
    """Shutter, then wait until the server has the photo."""
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("result-photo")).to_be_visible(timeout=READY)
    expect_uploaded(page)


def again(page: Page) -> None:
    """Back from the print to the live camera ("Noch ein Bier" / "Neues Foto")."""
    page.get_by_test_id("again").click()
    expect(page.get_by_test_id("result-photo")).to_have_count(0)
    expect(page.get_by_test_id("shutter")).to_be_enabled()


def reload(page: Page) -> None:
    """page.reload() once the fonts are in: Firefox logs a font download that the
    navigation aborts as an error (NS_BINDING_ABORTED), not the page's fault (GP's
    helper in tests/e2e/guest/conftest.py does the same)."""
    fonts_ready(page)
    page.reload()


# ---------------------------------------------------------------- stored photos


def photos(live: LiveServer, ext: str) -> list[Photo]:
    return live.core.repos.photos.list(PhotoQuery(extension=ext, order="asc", limit=500))


def stored_images(live: LiveServer, ext: str) -> list[tuple[dict[str, Any], Image.Image]]:
    out = []
    for p in photos(live, ext):
        img = Image.open(live.core.repos.photos.path(ext, p.filename)).convert("RGB")
        out.append((p.meta, img))
    return out


def wait_for_photos(live: LiveServer, ext: str, n: int, timeout: float = 15) -> list[Photo]:
    deadline = time.monotonic() + timeout
    while len(found := photos(live, ext)) < n:
        assert time.monotonic() < deadline, f"{len(found)} {ext} photos, expected {n}"
        time.sleep(0.1)
    return found


def media_size(page: Page, url: str) -> tuple[int, int]:
    """Size of a stored JPEG as the guest's browser downloads it (GET /media/<id>)."""
    data = page.evaluate(
        """async (url) => { const r = await fetch(url); return Array.from(new Uint8Array(await r.arrayBuffer())); }""",
        url,
    )
    return Image.open(io.BytesIO(bytes(data))).size


def add_photos(live: LiveServer, ext: str, n: int) -> None:
    """Photos from other guests, straight into the DB (rows only, no files)."""
    user = live.core.repos.users.list(limit=1)[0]
    meta = {"vessel": "bottle"} if ext == "beer" else {"filter": "normal", "facing": "user"}
    for _ in range(n):
        name = secrets.token_hex(4)
        live.core.repos.photos.insert(
            public_id=secrets.token_urlsafe(12).replace("-", "a"),
            extension=ext,
            user_id=user.id,
            filename=f"{name}.jpg",
            thumb_filename=f"thumbs/{name}.jpg",
            width=1080,
            height=1440,
            size=1,
            meta=meta,
            created_at="2026-10-13T20:00:00.000+00:00",
        )


def add_beers(live: LiveServer, n: int) -> None:
    """Beers from other guests, straight into the DB."""
    add_photos(live, "beer", n)


# ---------------------------------------------------------------- the host


class Admin:
    """The host's moderation calls through the admin API (CSRF origin + session)."""

    def __init__(self, request: APIRequestContext) -> None:
        self.request = request

    def _ok(self, method: str, path: str, data: Any = None) -> Any:
        res = self.request.fetch(path, method=method, data=data)
        assert res.ok, (path, res.status, res.text())
        return res.json()

    def user_id(self, index: int = -1) -> int:
        users = self._ok("GET", "/api/admin/users")["users"]
        return int(sorted(users, key=lambda u: u["id"])[index]["id"])

    def pause(self, user_id: int, paused: bool = True) -> None:
        self._ok("POST", f"/api/admin/users/{user_id}/uploads", {"paused": paused})

    def stop(self, enabled: bool = True) -> None:
        self._ok("POST", "/api/admin/upload-stop", {"enabled": enabled})

    def ban(self, user_id: int) -> None:
        self._ok("POST", f"/api/admin/users/{user_id}/ban", {"reason": "e2e"})

    def unban(self, user_id: int) -> None:
        self._ok("POST", f"/api/admin/users/{user_id}/unban", {})

    def hide(self, public_id: str) -> None:
        self._ok("POST", f"/api/admin/photos/{public_id}/hide")


@pytest.fixture
def admin(playwright: Playwright, live: LiveServer) -> Iterator[Admin]:
    request = playwright.request.new_context(
        base_url=live.base_url, extra_http_headers={"Origin": live.base_url}
    )
    res = request.post("/api/admin/login", data={"password": ADMIN_PASSWORD})
    assert res.ok, res.text()
    yield Admin(request)
    request.dispose()


# ---------------------------------------------------------------- browser state


def leaving_is_blocked(page: Page) -> bool:
    """Whether the page asks before it goes (beforeunload cancelled)."""
    return bool(
        page.evaluate(
            """() => {
        const e = new Event('beforeunload', { cancelable: true });
        window.dispatchEvent(e);
        return e.defaultPrevented;
    }"""
        )
    )


def kept_on_phone(page: Page) -> list[dict[str, Any]]:
    """Records in the page's IndexedDB outbox (id, ext, meta)."""
    return page.evaluate(
        """() => new Promise((resolve, reject) => {
        const req = indexedDB.open('vb-booth', 1);
        req.onupgradeneeded = () => req.result.createObjectStore('outbox', { keyPath: 'id' });
        req.onerror = () => reject(req.error);
        req.onsuccess = () => {
            const db = req.result;
            const all = db.transaction('outbox').objectStore('outbox').getAll();
            all.onsuccess = () => { db.close(); resolve(all.result.map((r) => ({ id: r.id, ext: r.ext ?? null, meta: r.meta }))); };
            all.onerror = () => reject(all.error);
        };
    })"""
    )


def wait_kept(page: Page, n: int, timeout: float = 10) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout
    while len(kept := kept_on_phone(page)) != n:
        assert time.monotonic() < deadline, f"{len(kept)} photos kept on the phone, expected {n}"
        page.wait_for_timeout(100)
    return kept


class Network:
    """Upload requests fail while `offline` is set (the rest of the API keeps working)."""

    def __init__(self, page: Page, ext: str = "*") -> None:
        self.offline = True
        self.calls = 0
        page.route(f"**/api/x/{ext}/upload", self.handle)

    def handle(self, route) -> None:  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.offline:
            route.abort("internetdisconnected")
        else:
            route.continue_()


def network_errors_only(page: Page) -> list[str]:
    """Console errors other than the failed uploads the test caused on purpose."""
    expected = (
        "ERR_INTERNET_DISCONNECTED",
        "NetworkError",
        "Load failed",
        "network connection was lost",
    )
    return [e for e in page.js_errors if not any(x in e for x in expected)]  # type: ignore[attr-defined]


def errors_except(page: Page, *needles: str) -> list[str]:
    """Console errors except the expected failed requests (e.g. a 429 on purpose)."""
    return [e for e in page.js_errors if not any(n in e for n in needles)]  # type: ignore[attr-defined]


def shot(page: Page, name: str, settle_ms: int = 500) -> None:
    """Screenshot into $VB_SCREENSHOT_DIR/<browser>_<name>.png (nothing when unset)."""
    out = SCREENSHOT_DIR
    if not out:
        return
    page.wait_for_timeout(settle_ms)
    Path(out).mkdir(parents=True, exist_ok=True)
    seen = len(getattr(page, "js_errors", []))
    page.screenshot(path=str(Path(out) / f"{BROWSER_NAME}_{name}.png"))
    errors = getattr(page, "js_errors", None)
    if errors is not None:
        errors[seen:] = [
            e for e in errors[seen:] if not e.startswith("Refused to apply a stylesheet")
        ]
