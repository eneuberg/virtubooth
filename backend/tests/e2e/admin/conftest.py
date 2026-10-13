"""Fixtures of the admin e2e tests (wave 2, AD): guests that talk HTTP only (cheap: no
browser per guest), an admin on a desktop (1440x900) next to the phone `admin_page`,
and small helpers for the new admin markup.

Selectors: the pre-overhaul test ids where the concept still exists (conn, photo-card,
photo-tile, toggle, lightbox, confirm, bulkbar, bulk-*, guest-search, uploads-chip,
pause-end-*, user-name, user-status, ban, unban-fp, unban-user, fingerprints, …), React
Aria roles for the rest (switch, checkbox, grid, row, dialog).
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import Callable, Iterator
from functools import cache
from typing import Any
from urllib.parse import quote

import httpx2 as httpx
import pytest
from PIL import Image
from playwright.sync_api import Browser, BrowserContext, Locator, Page

from virtubooth.core.ratelimit import RateLimiter

from ...conftest import ADMIN_PASSWORD
from ..conftest import BROWSER_NAME, LiveServer, track_errors, wait_until_ready

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
)

DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
PHONE_VIEWPORT = {"width": 390, "height": 844}
LANDSCAPE_VIEWPORT = {"width": 844, "height": 390}


@cache
def beer_jpeg(shade: int = 0) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1080, 1440), (40 + shade % 200, 120, 200)).save(buf, "JPEG", quality=70)
    return buf.getvalue()


def fp_hash(n: int) -> str:
    return f"{n:064x}"


class Guest:
    """A party guest over plain HTTP (its own cookie jar): joins, uploads, can be asked
    whether an upload goes through."""

    def __init__(
        self, live: LiveServer, *, instagram: str | None = None, fp: int | None = None
    ) -> None:
        self.live = live
        self.client = httpx.Client(
            base_url=live.base_url, headers={"User-Agent": IPHONE_UA, "Origin": live.base_url}
        )
        assert self.client.get(live.entry("/")).status_code == 303
        fingerprint = {
            "hash": fp_hash(fp) if fp is not None else os.urandom(16).hex(),
            "components": {
                "screen": "390x844@3",
                "languages": "de-DE",
                "timezone": "Europe/Berlin",
            },
        }
        ident = self.client.post("/api/identify", json={"fp": fingerprint}).json()
        version = ident["consent"]["version"] if "consent" in ident else "1"
        r = self.client.post(
            "/api/join",
            json={"accept": True, "version": version, "instagram": instagram, "fp": fingerprint},
        )
        assert r.status_code in (200, 201), r.text
        self.state: str = r.json()["state"]
        self.paused: bool = r.json()["user"]["uploads_paused"]

    @property
    def id(self) -> int:
        public_id = self.live.core.signer.unsign("uid", self.client.cookies.get("vb_uid"))
        user = self.live.core.repos.users.get_by_public_id(public_id)
        assert user is not None
        return user.id

    @property
    def name(self) -> str:
        user = self.live.core.repos.users.get(self.id)
        assert user is not None
        return user.name

    def upload_response(self, vessel: str = "bottle") -> httpx.Response:
        return self.client.post(
            "/api/x/beer/upload",
            content=beer_jpeg(),
            headers={
                "Content-Type": "image/jpeg",
                "X-VB-Meta": quote(
                    json.dumps({"vessel": vessel, "facing": "environment"}), safe=""
                ),
            },
        )

    def upload(self) -> str:
        r = self.upload_response()
        assert r.status_code == 201, r.text
        return str(r.json()["photo"]["id"])


@pytest.fixture(autouse=True)
def relaxed_upload_limits(live: LiveServer) -> None:
    """Tests upload dozens of photos from one guest in seconds."""
    live.core.limits.upload_user = RateLimiter(10_000, 60)
    live.core.limits.upload_ip = RateLimiter(10_000, 60)
    live.core.limits.upload_global = RateLimiter(10_000, 60)
    live.core.limits.new_user_ip = RateLimiter(10_000, 600)


@pytest.fixture
def guests(live: LiveServer) -> Iterator[Callable[..., Guest]]:
    made: list[Guest] = []

    def make(**kwargs: Any) -> Guest:
        g = Guest(live, **kwargs)
        made.append(g)
        return g

    yield make
    for g in made:
        g.client.close()


def login_api(page: Page, live: LiveServer) -> None:
    page.goto(live.url("/admin/login"))
    status = page.evaluate(
        """async (pw) => (await fetch('/api/admin/login', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: pw})})).status""",
        ADMIN_PASSWORD,
    )
    assert status == 200


def admin_context(browser: Browser, viewport: dict[str, int], **options: Any) -> BrowserContext:
    opts: dict[str, Any] = {"viewport": viewport, **options}
    if BROWSER_NAME == "firefox":
        opts.pop("is_mobile", None)
    return browser.new_context(**opts)


@pytest.fixture
def desktop_page(browser: Browser, live: LiveServer) -> Iterator[Page]:
    """An admin on the host's laptop (1440x900), logged in through the API."""
    ctx = admin_context(browser, DESKTOP_VIEWPORT)
    page = track_errors(ctx.new_page())
    login_api(page, live)
    yield page
    ctx.close()


def goto(page: Page, live: LiveServer, path: str) -> None:
    page.goto(live.url(path))
    wait_until_ready(page)


def card(page: Page, photo_id: str) -> Locator:
    return page.locator(f'[data-photo-id="{photo_id}"]')


def no_horizontal_scroll(page: Page) -> bool:
    return bool(
        page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")
    )


def errors(page: Page, *expected_status: int) -> list[str]:
    """Console errors besides failed requests we caused on purpose (e.g. 401, 404)."""
    allowed = tuple(f"status of {s}" for s in expected_status)
    out = []
    for e in page.js_errors:  # type: ignore[attr-defined]
        if allowed and "Failed to load resource" in e and any(a in e for a in allowed):
            continue
        out.append(e)
    return out


def toast(page: Page) -> Locator:
    """The single toast slot's current message."""
    return page.locator("[data-tone]").last


def wait_live(page: Page) -> None:
    from playwright.sync_api import expect

    expect(page.get_by_test_id("conn").first).to_have_attribute(
        "data-state", "live", timeout=10_000
    )


UPLOAD_FROM_PAGE = """async (shade) => {
  const c = document.createElement('canvas');
  c.width = 1080;
  c.height = 1440;
  const ctx = c.getContext('2d');
  ctx.fillStyle = `rgb(${shade % 255}, 160, 90)`;
  ctx.fillRect(0, 0, 1080, 1440);
  const blob = await new Promise((resolve) => c.toBlob(resolve, 'image/jpeg', 0.7));
  const res = await fetch('/api/x/beer/upload', {
    method: 'POST',
    headers: {'Content-Type': 'image/jpeg',
              'X-VB-Meta': encodeURIComponent(JSON.stringify({vessel: 'cup', facing: 'user'}))},
    body: blob,
  });
  const data = await res.json();
  return {status: res.status, id: data.photo ? data.photo.id : null, error: data.error || null};
}"""


def upload_from_page(page: Page, shade: int = 0) -> dict[str, Any]:
    """A guest's browser uploads a 1080x1440 JPEG (it joined with join_via_api)."""
    result: dict[str, Any] = page.evaluate(UPLOAD_FROM_PAGE, shade)
    return result


def settle(page: Page) -> None:
    """Wait until running animations (sheets sliding in, toasts) are done."""
    page.evaluate(
        "() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => null)))"
    )


def confirm_dialog(page: Page) -> Locator:
    """The open confirm question (not a toast: a toast with an action is an alertdialog too)."""
    return page.get_by_test_id("confirm").get_by_role("alertdialog")


def wait_until(check: Callable[[], bool], timeout: float = 5.0, what: str = "condition") -> None:
    """Poll a Python-side check (the CSP forbids wait_for_function's string eval)."""
    import time

    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.05)
