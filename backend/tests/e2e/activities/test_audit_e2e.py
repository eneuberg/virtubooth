"""The camera activities through tests/e2e/audit.py (axe, blockers, leaked React Aria
classes) on a phone and on a PC: Beer Cam live and its result, Fotobox live, its
countdown and its print, the blocked camera (paused, with the reason sheet), and the
camera errors (denied, no camera). Serious and critical axe findings fail;
`VB_AXE_REPORT=<file>` lists everything."""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from playwright.sync_api import Browser, Page, expect

from ..audit import Audit
from ..conftest import LiveServer, join_via_api, new_context, settle_dialogs, track_errors
from .conftest import READY, Admin, again, fonts_ready, open_beer, open_booth, shoot

pytestmark = pytest.mark.e2e

DENIED = """Object.defineProperty(MediaDevices.prototype, 'getUserMedia', { configurable: true,
    value: () => Promise.reject(new DOMException('denied', '%s')) });"""


@pytest.fixture
def device(browser: Browser, live: LiveServer) -> Iterator[Callable[..., Page]]:
    """device("phone" | "desktop", init_script=None) → a joined guest on Start."""
    contexts = []

    def make(kind: str, init_script: str | None = None) -> Page:
        ctx = new_context(browser, kind)
        contexts.append(ctx)
        if init_script:
            ctx.add_init_script(init_script)
        page = track_errors(ctx.new_page())
        join_via_api(page, live)
        fonts_ready(page)
        return page

    yield make
    for ctx in contexts:
        ctx.close()


@pytest.mark.parametrize("kind", ["phone", "desktop"])
def test_activity_screens(device, live: LiveServer, admin: Admin, kind: str):  # type: ignore[no-untyped-def]
    audit = Audit(f"activities {kind}")
    page: Page = device(kind)

    open_beer(page, live)
    audit.check(page, "beer cam")
    shoot(page)
    expect(page.get_by_test_id("success-title")).to_be_visible()
    audit.check(page, "beer cam result")
    again(page)

    open_booth(page, live)
    expect(page.get_by_test_id("filter-bw").locator("img")).to_be_visible(timeout=READY)
    audit.check(page, "fotobox")
    page.get_by_test_id("countdown-toggle").click()
    page.get_by_test_id("shutter").click()
    countdown = page.get_by_test_id("countdown")
    expect(countdown).to_be_visible()
    # three seconds: axe looks at the countdown only
    audit.check(page, "fotobox countdown", only="[data-testid=countdown]")
    expect(page.get_by_test_id("result-photo")).to_be_visible(timeout=READY)
    expect(page.get_by_test_id("upload-status")).to_have_attribute(
        "data-state", "done", timeout=READY
    )
    audit.check(page, "fotobox print")
    again(page)
    page.get_by_test_id("countdown-toggle").click()  # back off for the next guest

    admin.pause(admin.user_id())
    open_beer(page, live)
    expect(page.get_by_test_id("shutter")).to_have_attribute("data-state", "blocked")
    audit.check(page, "beer cam paused")
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("status-info").get_by_role("dialog")).to_be_visible()
    settle_dialogs(page)
    audit.check(page, "beer cam paused, why")
    page.keyboard.press("Escape")
    admin.pause(admin.user_id(), paused=False)
    audit.assert_clean()
    assert page.js_errors == []  # type: ignore[attr-defined]

    for name in ("NotAllowedError", "NotFoundError"):
        broken: Page = device(kind, DENIED % name)
        broken.goto(live.url("/x/beer/"))
        expect(broken.get_by_test_id("camera-error")).to_be_visible(timeout=READY)
        audit.check(broken, f"camera error {name}")
        assert broken.js_errors == []  # type: ignore[attr-defined]
    audit.assert_clean()
