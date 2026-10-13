"""Screenshots of the camera pages for the design review (not a test of behaviour).

    VB_SCREENSHOT_DIR=dir uv run pytest tests/e2e/activities/test_screenshots_e2e.py -m e2e

Chromium only (CDP slows the upload down to show the progress). The fake camera
shows the design's synthetic scenes (docs/overhaul/design/mockups/img) instead of
the browser's test pattern, centred in a 4:3 frame like a phone sensor.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Route, expect

from virtubooth.settings import REPO_ROOT

from ..conftest import BROWSER_NAME, MOBILE, LiveServer, join_via_api, track_errors
from .conftest import (
    READY,
    SCREENSHOT_DIR,
    Admin,
    Network,
    fonts_ready,
    open_beer,
    open_booth,
    select_filter,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not SCREENSHOT_DIR, reason="set VB_SCREENSHOT_DIR=dir"),
    pytest.mark.skipif(BROWSER_NAME != "chromium", reason="CDP network throttling"),
]

IMG = REPO_ROOT / "docs" / "overhaul" / "design" / "mockups" / "img"

VIEWPORTS = {
    "phone": {"width": 390, "height": 844},
    "small": {"width": 360, "height": 640},
    "landscape": {"width": 844, "height": 390},
    "desktop": {"width": 1440, "height": 900},
}

# A camera that films a still scene: the picture fills the centred 3:4 region of a
# 1280×960 (4:3) frame, the sides are its blurred edges. Facing as asked.
SCENE = """((src) => {
  const md = window.MediaDevices && MediaDevices.prototype;
  if (!md || !md.getUserMedia) return;
  const gum = md.getUserMedia, enumerate = md.enumerateDevices;
  const img = new Image();
  img.src = src;
  const define = (obj, name, value) => Object.defineProperty(obj, name, { configurable: true, writable: true, value });
  function scene(facing) {
    const c = document.createElement('canvas');
    c.width = 1280; c.height = 960;
    const ctx = c.getContext('2d');
    let n = 0;
    const paint = () => {
      if (img.complete && img.naturalWidth) {
        ctx.filter = 'blur(24px) brightness(0.6)';
        ctx.drawImage(img, -40, -40, 1360, 1040);
        ctx.filter = 'none';
        ctx.drawImage(img, 280, 0, 720, 960);
      }
      ctx.fillStyle = (n++ % 2) ? '#000' : '#010101';
      ctx.fillRect(0, 959, 1, 1);
    };
    paint();
    setInterval(paint, 66);
    const stream = c.captureStream(15);
    for (const t of stream.getVideoTracks()) {
      const settings = t.getSettings.bind(t);
      define(t, 'getSettings', () => ({ ...settings(), facingMode: facing }));
    }
    return stream;
  }
  define(md, 'getUserMedia', async function (c) {
    let f = c && typeof c.video === 'object' ? c.video.facingMode : undefined;
    if (f && typeof f === 'object') f = f.exact || f.ideal;
    const real = await gum.call(this, c);
    real.getTracks().forEach((t) => t.stop());
    return scene(f === 'environment' ? 'environment' : 'user');
  });
  define(md, 'enumerateDevices', async function () {
    const list = await enumerate.call(this);
    const cam = list.find((d) => d.kind === 'videoinput');
    const back = { kind: 'videoinput', deviceId: 'back', groupId: 'back', label: 'Back Camera' };
    return cam ? [...list, { ...back, toJSON: () => back }] : list;
  });
})(__SRC__);"""


def scene_script(image: str) -> str:
    data = base64.b64encode((IMG / image).read_bytes()).decode()
    return SCENE.replace("__SRC__", json.dumps(f"data:image/jpeg;base64,{data}"))


def snap(page: Page, name: str, settle_ms: int = 600) -> None:
    page.wait_for_timeout(settle_ms)
    out = Path(str(SCREENSHOT_DIR)) / "wave2-ac"
    out.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out / f"{name}.png"))


@pytest.fixture
def device(browser: Browser, live: LiveServer) -> Iterator:  # type: ignore[type-arg]
    contexts: list[BrowserContext] = []

    def open_device(view: str, image: str) -> Page:
        opts: dict = {
            "viewport": VIEWPORTS[view],
            "permissions": ["camera"],
            "device_scale_factor": 2,
        }
        if view != "desktop":
            opts.update({"is_mobile": True, "has_touch": True, "user_agent": MOBILE["user_agent"]})
        ctx = browser.new_context(**opts)
        ctx.add_init_script(scene_script(image))
        contexts.append(ctx)
        page = track_errors(ctx.new_page())
        join_via_api(page, live)
        fonts_ready(page)
        return page

    yield open_device
    for ctx in contexts:
        ctx.close()


def hold_uploads(page: Page) -> list[Route]:
    """Uploads wait until the test lets them go (route.continue_())."""
    held: list[Route] = []
    page.route("**/api/x/*/upload", lambda route: held.append(route))
    return held


# how far the swatch's middle is from the strip's, read in one go (a locator's
# bounding_box waits up to 30 s for its element, twice per poll)
OFF_CENTRE = """(id) => {
  const strip = document.querySelector('[data-testid=filter-strip]');
  const chip = document.querySelector(`[data-testid=filter-${id}]`);
  if (!strip || !chip) return null;
  const s = strip.getBoundingClientRect(), c = chip.getBoundingClientRect();
  return Math.abs(c.x + c.width / 2 - (s.x + s.width / 2));
}"""


def centred(page: Page, filter_id: str, timeout: float = 10) -> None:
    """Wait until the strip has scrolled the selected swatch to the middle (smooth
    scrolling takes a while on a busy machine; the strip re-centres after a resize)."""
    deadline = time.monotonic() + timeout
    while (off := page.evaluate(OFF_CENTRE, filter_id)) is None or off >= 3:
        assert time.monotonic() < deadline, f"filter {filter_id} {off} px off the middle"
        page.wait_for_timeout(100)


@pytest.mark.parametrize("view", ["phone", "small", "landscape", "desktop"])
def test_beer_cam(device, live: LiveServer, view: str):  # type: ignore[no-untyped-def]
    page = device(view, "beer-1.jpg")
    open_beer(page, live)
    snap(page, f"beer-live-{view}", 900)
    if view == "phone":
        held = hold_uploads(page)
        page.get_by_test_id("shutter").click()
        expect(page.get_by_test_id("upload-status")).to_have_attribute("data-state", "uploading")
        snap(page, "beer-uploading-phone", 900)
        page.wait_for_timeout(100)
        for route in held:
            route.continue_()
        page.unroute("**/api/x/*/upload")
    else:
        page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("success-title")).to_be_visible(timeout=READY)
    if view in ("phone", "landscape"):
        snap(page, f"beer-result-{view}", 1000)
    assert page.js_errors == []


@pytest.mark.parametrize("view", ["phone", "small", "landscape", "desktop"])
def test_fotobox(device, live: LiveServer, view: str):  # type: ignore[no-untyped-def]
    page = device(view, "booth-1.jpg")
    open_booth(page, live)
    expect(page.get_by_test_id("filter-comic").locator("img")).to_be_visible(timeout=READY)
    chosen = "party" if view in ("phone", "desktop") else "neon"
    select_filter(page, chosen)
    centred(page, chosen)
    snap(page, f"booth-live-{view}", 900)
    if view == "phone":
        page.get_by_test_id("countdown-toggle").click()
        page.get_by_test_id("shutter").click()
        expect(page.get_by_test_id("countdown")).to_be_visible()
        snap(page, "booth-countdown-phone", 1300)
    else:
        page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("upload-status")).to_have_attribute(
        "data-state", "done", timeout=READY
    )
    if view in ("phone", "desktop"):
        snap(page, f"booth-result-{view}", 1000)
    assert page.js_errors == []


def test_blocked_and_waiting(device, live: LiveServer, admin: Admin):  # type: ignore[no-untyped-def]
    page = device("phone", "beer-2.jpg")
    admin.pause(admin.user_id())
    open_beer(page, live)
    snap(page, "beer-blocked-phone", 900)
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("status-info")).to_be_visible()
    snap(page, "beer-blocked-why-phone", 700)
    page.keyboard.press("Escape")
    admin.pause(admin.user_id(), paused=False)

    page = device("phone", "booth-3.jpg")
    open_booth(page, live)
    Network(page, "booth")
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("upload-status")).to_have_attribute(
        "data-state", "waiting", timeout=READY
    )
    snap(page, "booth-waiting-phone", 1000)


def test_camera_error(device, live: LiveServer):  # type: ignore[no-untyped-def]
    page = device("phone", "beer-1.jpg")
    page.add_init_script(
        """Object.defineProperty(MediaDevices.prototype, 'getUserMedia', { configurable: true,
        value: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) });"""
    )
    page.goto(live.url("/x/beer/"))
    expect(page.get_by_test_id("camera-error")).to_be_visible(timeout=READY)
    snap(page, "camera-error-phone", 500)
