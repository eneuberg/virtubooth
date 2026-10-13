"""Firefox's real camera permission flow (the rest of the suite turns it off
with media.navigator.permission.disabled). Headless Firefox can't show its
prompt, so the pref permissions.default.camera stands in for the guest's
answer: 0 = ask (the prompt stays open), 1 = allow, 2 = block.

    VB_E2E_BROWSER=firefox uv run pytest -m e2e tests/e2e/test_firefox_e2e.py
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from playwright.sync_api import Browser, Page, Playwright, expect

from virtubooth.extension import discover_extensions

from .conftest import DESKTOP, FIREFOX, FIREFOX_PREFS, accept_consent_in_browser, firefox_only, track_errors

pytestmark = [pytest.mark.e2e, firefox_only]

ASK, ALLOW, BLOCK = 0, 1, 2
READY = 15000

# records every getUserMedia call, then lets Firefox handle it as usual
SPY = """(() => {
  const gum = MediaDevices.prototype.getUserMedia;
  window.__cameraRequests = [];
  Object.defineProperty(MediaDevices.prototype, 'getUserMedia', {
    configurable: true,
    value: function (c) {
      window.__cameraRequests.push(JSON.parse(JSON.stringify(c)));
      return gum.call(this, c);
    },
  });
})();"""


@pytest.fixture
def e2e_extensions():
    return discover_extensions(["beer", "booth"])


@pytest.fixture(scope="module")
def firefox(playwright: Playwright) -> Iterator[Callable[[int], Browser]]:
    """firefox(ASK | ALLOW | BLOCK): a Firefox whose camera permission is real."""
    browsers: dict[int, Browser] = {}

    def launch(camera: int) -> Browser:
        if camera not in browsers:
            prefs = FIREFOX_PREFS | {"media.navigator.permission.disabled": False, "permissions.default.camera": camera}
            browsers[camera] = playwright.firefox.launch(firefox_user_prefs=prefs)
        return browsers[camera]

    yield launch
    for b in browsers.values():
        b.close()


def guest(browser: Browser, live, path: str, device: dict = DESKTOP) -> Page:
    """A new guest at `path`; consent accepted."""
    page = track_errors(browser.new_context(**device).new_page())
    page.add_init_script(SPY)
    page.goto(live.entry(path))
    page.get_by_test_id("join").wait_for()
    # the camera (and with it Firefox's prompt) only comes after the banner
    assert page.evaluate("() => window.__cameraRequests.length") == 0
    accept_consent_in_browser(page)
    return page


def camera_state(page: Page) -> str:
    return page.evaluate("async () => (await navigator.permissions.query({ name: 'camera' })).state")


@pytest.mark.parametrize("path", ["/x/beer/", "/x/booth/"])
def test_asks_firefox_for_the_camera(firefox, live, path):
    """Firefox shows its prompt now; until the guest answers the page waits."""
    page = guest(firefox(ASK), live, path)
    expect(page.get_by_text("Kamera startet")).to_be_visible()
    page.wait_for_timeout(2000)  # boot() is done well before; the prompt stays open
    [request] = page.evaluate("() => window.__cameraRequests")
    assert request["audio"] is False and request["video"]["facingMode"]["ideal"] in ("user", "environment")
    assert camera_state(page) == "prompt"
    expect(page.get_by_text("Kamera startet")).to_be_visible()
    expect(page.get_by_test_id("shutter")).to_be_disabled()
    expect(page.get_by_role("alert")).to_have_count(0)  # no error while the prompt is open
    assert page.js_errors == []
    page.context.close()


@pytest.mark.parametrize("path", ["/x/beer/", "/x/booth/"])
def test_allowed_camera_starts(firefox, live, path):
    page = guest(firefox(ALLOW), live, path)
    expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=READY)
    assert camera_state(page) == "granted"
    assert page.js_errors == []
    page.context.close()


@pytest.mark.parametrize(
    ("path", "title"),
    [("/x/beer/", "Kamera geht nicht"), ("/x/booth/", "Die Kamera geht nicht")],
)
@pytest.mark.parametrize(
    ("device", "how"),
    [(DESKTOP, "Klick in der Adressleiste auf das Kamera-Symbol"), (FIREFOX, "Tippe auf das Schloss")],
    ids=["desktop", "touch"],
)
def test_blocked_camera_shows_the_german_notice(firefox, live, path, title, device, how):
    """A real NotAllowedError from Firefox, not a mocked one."""
    page = guest(firefox(BLOCK), live, path, device)
    notice = page.locator(".vb-notice")
    expect(notice).to_be_visible(timeout=READY)
    expect(notice).to_contain_text(title)
    expect(notice).to_contain_text(f"Kamera-Zugriff wurde verweigert. {how}")
    expect(notice.get_by_role("button")).to_be_visible()  # reload
    expect(page.get_by_test_id("shutter")).to_be_disabled()
    assert camera_state(page) == "denied"
    assert len(page.evaluate("() => window.__cameraRequests")) == 1
    page.context.close()
