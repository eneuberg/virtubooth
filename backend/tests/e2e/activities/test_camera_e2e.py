"""The camera itself, on the host's PC and in Firefox's real permission flow.

Desktop (from the pre-overhaul test_desktop_e2e.py): 1280×800, mouse and keyboard, one 16:9
webcam that doesn't say which way it points (conftest WEBCAM: a test card with a
yellow square in the top-left of the region a portrait photo keeps). The photo and
the preview must both be that centred 3:4 region, mirrored like a video call.

Firefox (from the pre-overhaul test_firefox_e2e.py): permissions.default.camera stands in
for the guest's answer to the prompt: 0 = ask (the prompt stays open), 1 = allow,
2 = block.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Iterator

import pytest
from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import Browser, Page, Playwright, expect

from virtubooth.extensions.booth import FILTERS

from ..conftest import (
    DESKTOP,
    FIREFOX,
    FIREFOX_PREFS,
    LiveServer,
    firefox_only,
    join_via_api,
    track_errors,
)
from .conftest import READY, open_beer, open_booth, select_filter, shot, stored_images

pytestmark = pytest.mark.e2e

VIEW_W, VIEW_H = DESKTOP["viewport"]["width"], DESKTOP["viewport"]["height"]


# ------------------------------------------------------------------ helpers


def is_yellow(px: tuple[int, int, int]) -> bool:
    r, g, b = px
    return r > 180 and g > 150 and b < 110


def is_blue(px: tuple[int, int, int]) -> bool:
    r, _g, b = px
    return b > 150 and r < 100


def assert_portrait_crop(img: Image.Image, *, mirrored: bool) -> None:
    """The 3:4 photo is the centre of the 16:9 test card: no red from the sides, not
    stretched (the yellow square stays square), mirrored like the preview."""
    img = img.convert("RGB").resize((1080, 1440))
    w, h = img.size
    for x in (6, w - 7):  # left and right edge, top to bottom
        for y in range(60, h - 60, 120):
            assert is_blue(img.getpixel((x, y))), (x, y, img.getpixel((x, y)))  # type: ignore[arg-type]
    # the square: x 60..340, y 80..360 of an unmirrored photo
    cx = w - 200 if mirrored else 200
    assert is_yellow(img.getpixel((cx, 220))), img.getpixel((cx, 220))  # type: ignore[arg-type]
    assert is_blue(img.getpixel((w - cx, 220))), img.getpixel((w - cx, 220))  # type: ignore[arg-type]
    across = [x for x in range(0, w, 4) if is_yellow(img.getpixel((x, 220)))]  # type: ignore[arg-type]
    down = [y for y in range(0, h // 2, 4) if is_yellow(img.getpixel((cx, y)))]  # type: ignore[arg-type]
    width, height = across[-1] - across[0], down[-1] - down[0]
    assert abs(width - 280) < 16 and abs(height - 280) < 16, (width, height)


def screenshot_of(page: Page, testid: str) -> Image.Image:
    before = len(page.js_errors)  # type: ignore[attr-defined]
    png = page.get_by_test_id(testid).screenshot()
    page.js_errors[before:] = [  # type: ignore[attr-defined]
        e
        for e in page.js_errors[before:]  # type: ignore[attr-defined]
        if "Refused to apply a stylesheet" not in e
    ]
    return Image.open(io.BytesIO(png)).convert("RGB")


def on_screen(page: Page, testid: str) -> dict:
    box = page.get_by_test_id(testid).first.bounding_box()
    assert box, testid
    assert box["x"] >= 0 and box["y"] >= 0, (testid, box)
    assert box["x"] + box["width"] <= VIEW_W and box["y"] + box["height"] <= VIEW_H, (testid, box)
    return box


def no_horizontal_scroll(page: Page) -> bool:
    return bool(
        page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")
    )


def camera_requests(page: Page) -> list[dict]:
    return page.evaluate("() => window.__cameraRequests")


def mean_diff(a: Image.Image, b: Image.Image) -> float:
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


# ------------------------------------------------------------------ desktop


def test_beer_cam_on_the_pc(pc: Page, live: LiveServer):
    page = pc
    open_beer(page, live)
    app = page.get_by_test_id("beer-app")

    # the back camera is only a wish: the one webcam is used, and it faces the guest
    [request] = camera_requests(page)
    assert request["video"]["facingMode"] == {"ideal": "environment"}
    assert request["video"]["width"] == {"ideal": 1920} and request["video"]["height"] == {
        "ideal": 1440
    }
    expect(page.get_by_test_id("switch-camera")).to_have_count(0)  # nothing to switch to
    expect(app).to_have_attribute("data-facing", "user")
    expect(app).to_have_attribute("data-mirror", "1")

    # a big 3:4 box in the middle, every control on screen, nothing scrolls sideways
    frame = on_screen(page, "frame")
    assert frame["width"] / frame["height"] == pytest.approx(0.75, abs=0.01)
    assert frame["height"] > 0.6 * VIEW_H
    assert abs(frame["x"] + frame["width"] / 2 - VIEW_W / 2) < 2
    for testid in ("shutter", "vessel", "back", "counter"):
        box = on_screen(page, testid)
        if testid in ("shutter", "vessel"):  # under the box, not in far corners
            assert abs(box["x"] + box["width"] / 2 - VIEW_W / 2) < 300, (testid, box)
    expect(page.get_by_text("Leertaste")).to_be_visible()  # the key hint on a PC
    assert no_horizontal_scroll(page)
    shot(page, "beer-desktop", 300)

    # the preview shows what the photo keeps: the centre of the landscape picture, mirrored
    page.get_by_test_id("overlay").evaluate("el => { el.style.display = 'none'; }")
    assert_portrait_crop(screenshot_of(page, "preview-canvas"), mirrored=True)
    page.get_by_test_id("overlay").evaluate("el => { el.style.display = ''; }")

    # keyboard only: Space shoots, Enter on "Noch ein Bier", Space again, Escape
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("Space")
    expect(page.get_by_test_id("success-title")).to_be_visible(timeout=READY)
    expect(page.get_by_test_id("again")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("result-photo")).to_have_count(0)
    expect(page.get_by_test_id("shutter")).to_be_focused()
    page.keyboard.press("Space")
    expect(page.get_by_test_id("success-title")).to_have_text("Bier Nr. 2 gezählt", timeout=READY)
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("result-photo")).to_have_count(0)

    stored = stored_images(live, "beer")
    assert [meta for meta, _ in stored] == [{"vessel": "bottle", "facing": "user"}] * 2
    for _meta, img in stored:
        assert img.size == (1080, 1440)
        assert_portrait_crop(img, mirrored=True)
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_fotobox_on_the_pc(pc: Page, live: LiveServer):
    page = pc
    open_booth(page, live)
    b = page.get_by_test_id("booth")
    expect(b).to_have_attribute("data-renderer", "webgl")
    expect(b).to_have_attribute("data-facing", "user")
    expect(b).to_have_attribute("data-mirror", "1")
    expect(page.get_by_test_id("switch-camera")).to_have_count(0)
    [request] = camera_requests(page)
    assert request["video"]["facingMode"] == {"ideal": "user"}

    preview = on_screen(page, "preview")
    assert preview["width"] / preview["height"] == pytest.approx(0.75, abs=0.01)
    assert preview["height"] > 0.5 * VIEW_H
    assert abs(preview["x"] + preview["width"] / 2 - VIEW_W / 2) < 2
    for testid in ("shutter", "countdown-toggle", "filter-strip", "back"):
        on_screen(page, testid)
    assert no_horizontal_scroll(page)
    assert_portrait_crop(screenshot_of(page, "preview-canvas"), mirrored=True)
    expect(page.get_by_test_id("filter-bw").locator("img")).to_be_visible(timeout=READY)
    shot(page, "booth-desktop", 300)

    # a double click (= double tap) has no second camera to flip to
    page.get_by_test_id("preview").dblclick()
    page.wait_for_timeout(300)
    expect(b).to_have_attribute("data-ready", "1")
    assert len(camera_requests(page)) == 1

    # keyboard only
    ids = list(FILTERS)
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("ArrowRight")
    expect(b).to_have_attribute("data-filter", ids[1])
    page.keyboard.press("ArrowLeft")
    expect(b).to_have_attribute("data-filter", "normal")
    page.keyboard.press("Space")
    expect(page.get_by_test_id("upload-status")).to_have_attribute(
        "data-state", "done", timeout=READY
    )
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("result-photo")).to_have_count(0)
    expect(page.get_by_test_id("shutter")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("upload-status")).to_have_attribute(
        "data-state", "done", timeout=READY
    )
    for testid in ("save", "again"):
        on_screen(page, testid)

    stored = stored_images(live, "booth")
    assert [meta for meta, _ in stored] == [{"filter": "normal", "facing": "user"}] * 2
    for _meta, img in stored:
        assert img.size == (1080, 1440)
        assert_portrait_crop(img, mirrored=True)
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_every_filter_changes_the_picture(pc: Page, live: LiveServer):
    """On the still test card: each filter's preview differs from "Normal", and
    "Normal" is stable, so the difference is the filter's."""
    page = pc
    open_booth(page, live)
    page.wait_for_timeout(300)
    normal = screenshot_of(page, "preview-canvas")
    page.wait_for_timeout(200)
    assert mean_diff(normal, screenshot_of(page, "preview-canvas")) < 1.5
    for fid in list(FILTERS)[1:]:
        select_filter(page, fid)
        page.wait_for_timeout(250)
        changed = mean_diff(normal, screenshot_of(page, "preview-canvas"))
        assert changed > 4, (fid, changed)
    assert page.js_errors == []  # type: ignore[attr-defined]


# ------------------------------------------------------------------ Firefox

ASK, ALLOW, BLOCK = 0, 1, 2

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
def firefox(playwright: Playwright) -> Iterator[Callable[[int], Browser]]:
    """firefox(ASK | ALLOW | BLOCK): a Firefox whose camera permission is real (one at a time)."""
    current: list[Browser] = []

    def launch(camera: int) -> Browser:
        prefs = FIREFOX_PREFS | {
            "media.navigator.permission.disabled": False,
            "permissions.default.camera": camera,
        }
        b = playwright.firefox.launch(firefox_user_prefs=prefs)
        current.append(b)
        return b

    yield launch
    for b in current:
        b.close()


def firefox_guest(browser: Browser, live: LiveServer, path: str, device: dict = DESKTOP) -> Page:
    page = track_errors(browser.new_context(**device).new_page())
    page.add_init_script(SPY)
    join_via_api(page, live)
    assert page.evaluate("() => window.__cameraRequests.length") == 0  # none on "/"
    page.goto(live.url(path))
    return page


def camera_state(page: Page) -> str:
    return str(
        page.evaluate("async () => (await navigator.permissions.query({ name: 'camera' })).state")
    )


@firefox_only
@pytest.mark.parametrize("path", ["/x/beer/", "/x/booth/"])
def test_firefox_asks_and_the_page_waits(firefox, live: LiveServer, path: str):  # type: ignore[no-untyped-def]
    page = firefox_guest(firefox(ASK), live, path)
    expect(page.get_by_text("Kamera startet…")).to_be_visible()
    page.wait_for_timeout(2000)  # the prompt stays open
    [request] = page.evaluate("() => window.__cameraRequests")
    assert request["audio"] is False and request["video"]["facingMode"]["ideal"] in (
        "user",
        "environment",
    )
    assert camera_state(page) == "prompt"
    expect(page.get_by_text("Kamera startet…")).to_be_visible()
    expect(page.get_by_test_id("shutter")).to_be_disabled()
    expect(page.get_by_role("alert")).to_have_count(0)  # no error while the prompt is open
    assert page.js_errors == []  # type: ignore[attr-defined]
    page.context.close()


@firefox_only
@pytest.mark.parametrize("path", ["/x/beer/", "/x/booth/"])
def test_firefox_allowed_camera_starts(firefox, live: LiveServer, path: str):  # type: ignore[no-untyped-def]
    page = firefox_guest(firefox(ALLOW), live, path)
    expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=READY)
    assert camera_state(page) == "granted"
    assert page.js_errors == []  # type: ignore[attr-defined]
    page.context.close()


@firefox_only
@pytest.mark.parametrize("path", ["/x/beer/", "/x/booth/"])
@pytest.mark.parametrize(
    ("device", "how"),
    [
        (DESKTOP, "Klick in der Adressleiste auf das Kamera-Symbol"),
        (FIREFOX, "Tippe auf das Schloss"),
    ],
    ids=["desktop", "touch"],
)
def test_firefox_blocked_camera_says_how_to_allow_it(firefox, live: LiveServer, path, device, how):  # type: ignore[no-untyped-def]
    """A real NotAllowedError from Firefox, not a mocked one."""
    page = firefox_guest(firefox(BLOCK), live, path, device)
    screen = page.get_by_test_id("camera-error")
    expect(screen).to_be_visible(timeout=READY)
    expect(screen).to_contain_text("Die Kamera geht nicht")
    expect(screen).to_contain_text(f"Kamera-Zugriff wurde verweigert. {how}")
    expect(screen.get_by_role("button", name="Seite neu laden")).to_be_visible()
    expect(page.get_by_test_id("shutter")).to_be_disabled()
    assert camera_state(page) == "denied"
    assert len(page.evaluate("() => window.__cameraRequests")) == 1
    assert page.js_errors == []  # type: ignore[attr-defined]
    page.context.close()
