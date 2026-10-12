"""The host's setup: a PC at 1280x800, mouse + keyboard, no touch, and one
16:9 webcam that doesn't say which way it points (conftest WEBCAM shows a test
card). `VB_E2E_BROWSER=firefox` is exactly what the host used.

    VB_SCREENSHOT_DIR=dir VB_E2E_BROWSER=firefox uv run pytest -m e2e tests/e2e/test_desktop_e2e.py
also saves desktop and phone screenshots of every page.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import BrowserContext, Page, expect

from virtubooth.extension import discover_extensions
from virtubooth.extensions.booth import FILTERS
from virtubooth.repo import PhotoQuery

from ..conftest import ADMIN_PASSWORD
from .conftest import DESKTOP, accept_consent_in_browser, new_context, track_errors

pytestmark = pytest.mark.e2e

READY = 15000
VIEW_W, VIEW_H = DESKTOP["viewport"]["width"], DESKTOP["viewport"]["height"]


@pytest.fixture
def e2e_extensions():
    return discover_extensions(["beer", "booth"])


@pytest.fixture
def desktop(browser, live) -> Iterator[BrowserContext]:
    ctx = new_context(browser, "desktop")
    yield ctx
    ctx.close()


@pytest.fixture
def pc(desktop: BrowserContext, live) -> Page:
    """A guest at the PC who scanned the QR code and accepted the banner."""
    page = track_errors(desktop.new_page())
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    return page


# ------------------------------------------------------------------ helpers


def no_horizontal_scroll(page: Page) -> bool:
    return page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")


def on_screen(page: Page, testid: str) -> dict:
    box = page.get_by_test_id(testid).bounding_box()
    assert box, testid
    assert box["x"] >= 0 and box["y"] >= 0, (testid, box)
    assert box["x"] + box["width"] <= VIEW_W and box["y"] + box["height"] <= VIEW_H, (testid, box)
    return box


def stored(live, ext: str) -> list[tuple[dict, Image.Image]]:
    photos = live.core.repo.list_photos(PhotoQuery(extension=ext, order="asc"))
    return [(p.meta, Image.open(live.core.repo.photo_path(ext, p.filename)).convert("RGB")) for p in photos]


def is_yellow(px) -> bool:
    r, g, b = px
    return r > 180 and g > 150 and b < 110


def is_blue(px) -> bool:
    r, g, b = px
    return b > 150 and r < 100


def assert_portrait_crop(img: Image.Image, *, mirrored: bool) -> None:
    """The 3:4 photo is the centre of the 16:9 test card: no red from the sides,
    not stretched (the yellow square stays square), mirrored like the preview."""
    img = img.resize((1080, 1440))
    w, h = img.size
    for x in (6, w - 7):  # left and right edge, top to bottom (minus the preview's rounded corners)
        for y in range(120, h - 100, 120):
            assert is_blue(img.getpixel((x, y))), (x, y, img.getpixel((x, y)))
    # the square: x 60..340, y 80..360 of an unmirrored photo
    cx = w - 200 if mirrored else 200
    assert is_yellow(img.getpixel((cx, 220))), img.getpixel((cx, 220))
    assert is_blue(img.getpixel((w - cx, 220))), img.getpixel((w - cx, 220))
    across = [x for x in range(0, w, 4) if is_yellow(img.getpixel((x, 220)))]
    down = [y for y in range(0, h // 2, 4) if is_yellow(img.getpixel((cx, y)))]
    width, height = across[-1] - across[0], down[-1] - down[0]
    assert abs(width - 280) < 16 and abs(height - 280) < 16, (width, height)


def screenshot_of(page: Page, testid: str) -> Image.Image:
    before = len(page.js_errors)
    png = page.get_by_test_id(testid).screenshot()
    # WebKit logs the CSP refusing the <style> Playwright injects for screenshots: not the page's fault
    page.js_errors[before:] = [e for e in page.js_errors[before:] if "Refused to apply a stylesheet" not in e]
    return Image.open(io.BytesIO(png)).convert("RGB")


def camera_requests(page: Page) -> list[dict]:
    return page.evaluate("() => window.__cameraRequests")


# -------------------------------------------------------------------- home


def test_home_on_desktop(pc, live):
    tiles = pc.get_by_test_id("tile-beer"), pc.get_by_test_id("tile-booth")
    for tile in tiles:
        expect(tile).to_be_visible()
    a, b = (t.bounding_box() for t in tiles)
    assert a and b and a["width"] <= 560 and abs(a["x"] + a["width"] / 2 - VIEW_W / 2) < 2  # one centred column
    assert no_horizontal_scroll(pc)
    pc.get_by_test_id("tile-booth").focus()
    pc.keyboard.press("Enter")
    pc.wait_for_url(live.url("/x/booth/"))
    assert pc.js_errors == []


# ---------------------------------------------------------------- Beer Cam


def test_beer_cam_on_desktop(pc, live):
    page = pc
    page.goto(live.url("/x/beer/"))
    expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=READY)

    # the rear camera is only a wish: the one webcam is used, and it faces the guest
    [request] = camera_requests(page)
    assert request["video"]["facingMode"] == {"ideal": "environment"}
    expect(page.get_by_test_id("switch-camera")).to_be_hidden()  # nothing to switch to
    expect(page.locator("#video")).to_have_class("is-mirrored")

    # a big 3:4 box in the middle, every control on screen, nothing scrolls sideways
    frame = on_screen(page, "frame")
    assert frame["width"] / frame["height"] == pytest.approx(0.75, abs=0.01)
    assert frame["height"] > 0.6 * VIEW_H
    assert abs(frame["x"] + frame["width"] / 2 - VIEW_W / 2) < 2
    for testid in ("shutter", "vessel-bottle", "vessel-cup", "back", "counter"):
        on_screen(page, testid)
    for testid in ("vessel-bottle", "shutter"):  # the controls sit under the box, not in far corners
        box = page.get_by_test_id(testid).bounding_box()
        assert box and abs(box["x"] + box["width"] / 2 - VIEW_W / 2) < 300, (testid, box)
    assert no_horizontal_scroll(page)

    # the preview shows what the photo will keep: the centre of the landscape picture, mirrored
    page.get_by_test_id("overlay").evaluate("el => { el.style.display = 'none'; }")
    assert_portrait_crop(screenshot_of(page, "frame"), mirrored=True)
    page.get_by_test_id("overlay").evaluate("el => { el.style.display = ''; }")

    # keyboard only: space shoots, enter on "Noch eins!", space again, escape closes
    page.keyboard.press("Space")
    expect(page.get_by_test_id("success")).to_be_visible(timeout=READY)
    expect(page.get_by_test_id("again")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("success")).to_be_hidden()
    expect(page.get_by_test_id("shutter")).to_be_focused()
    page.keyboard.press("Space")
    expect(page.get_by_test_id("success-title")).to_have_text("Bier #2 geloggt 🍺", timeout=READY)
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("success")).to_be_hidden()
    expect(page.get_by_test_id("shutter")).to_be_enabled()

    photos = stored(live, "beer")
    assert [meta for meta, _ in photos] == [{"vessel": "bottle", "facing": "user"}] * 2
    for _meta, img in photos:
        assert img.size == (1080, 1440)
        assert_portrait_crop(img, mirrored=True)
    assert page.js_errors == []


# ----------------------------------------------------------------- Fotobox


def test_fotobox_on_desktop(pc, live):
    page = pc
    page.goto(live.url("/x/booth/"))
    booth = page.get_by_test_id("booth")
    expect(booth).to_have_attribute("data-ready", "1", timeout=READY)
    expect(booth).to_have_attribute("data-renderer", "webgl")
    expect(booth).to_have_attribute("data-facing", "user")
    expect(booth).to_have_attribute("data-mirror", "1")
    expect(page.get_by_test_id("switch-camera")).to_be_hidden()

    preview = on_screen(page, "preview")
    assert preview["width"] / preview["height"] == pytest.approx(0.75, abs=0.01)
    assert preview["height"] > 0.6 * VIEW_H
    assert abs(preview["x"] + preview["width"] / 2 - VIEW_W / 2) < 2
    for testid in ("shutter", "countdown-toggle", "filter-normal", "back"):
        on_screen(page, testid)
    assert no_horizontal_scroll(page)
    assert_portrait_crop(screenshot_of(page, "preview-canvas"), mirrored=True)

    # a double click (= double tap) has no second camera to flip to
    page.get_by_test_id("preview").dblclick()
    page.wait_for_timeout(300)
    expect(booth).to_have_attribute("data-ready", "1")
    assert len(camera_requests(page)) == 1

    # keyboard only: arrows pick filters, space shoots, escape goes back, enter on the shutter
    ids = list(FILTERS)
    page.keyboard.press("ArrowRight")
    expect(booth).to_have_attribute("data-filter", ids[1])
    page.keyboard.press("ArrowLeft")
    expect(booth).to_have_attribute("data-filter", "normal")
    page.keyboard.press("Space")
    expect(page.get_by_test_id("upload-status")).to_have_attribute("data-state", "done", timeout=READY)
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("result")).to_be_hidden()
    expect(page.get_by_test_id("shutter")).to_be_focused()
    page.keyboard.press("ArrowRight")  # also while the shutter has focus
    expect(booth).to_have_attribute("data-filter", ids[1])
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("result")).to_be_visible(timeout=READY)
    expect(page.get_by_test_id("upload-status")).to_have_attribute("data-state", "done", timeout=READY)
    for testid in ("save", "again"):
        on_screen(page, testid)

    photos = stored(live, "booth")
    assert [meta for meta, _ in photos] == [{"filter": "normal", "facing": "user"}] * 2
    for _meta, img in photos:
        assert img.size == (1080, 1440)
        assert_portrait_crop(img, mirrored=True)
    assert page.js_errors == []


# ------------------------------------------------------------------- admin


UPLOAD_JS = """async (n) => {
  for (let i = 0; i < n; i++) {
    const c = document.createElement('canvas');
    c.width = 1080;
    c.height = 1440;
    const ctx = c.getContext('2d');
    ctx.fillStyle = `hsl(${i * 70}, 70%, 50%)`;
    ctx.fillRect(0, 0, c.width, c.height);
    const blob = await new Promise((resolve) => c.toBlob(resolve, 'image/jpeg', 0.8));
    const res = await fetch('/api/x/beer/upload', { method: 'POST', body: blob, headers: {
      'Content-Type': 'image/jpeg', 'X-VB-Meta': encodeURIComponent(JSON.stringify({ vessel: 'bottle' })) } });
    if (res.status !== 201) throw new Error(await res.text());
  }
}"""


def test_admin_on_desktop(pc, desktop, live):
    pc.evaluate(UPLOAD_JS, 3)
    user = live.core.repo.list_users()[0]
    # the guest's own context holds no admin session: log in with the keyboard in a fresh one
    ctx = desktop.browser.new_context(**DESKTOP)
    try:
        page = track_errors(ctx.new_page())
        page.goto(live.url("/admin/live"))
        page.wait_for_url("**/admin/login?next=/admin/live")
        page.locator("#password").fill(ADMIN_PASSWORD)
        page.keyboard.press("Enter")
        page.wait_for_url(live.url("/admin/live"))
        screens = {
            "/admin/live": "[data-testid=photo-card]",
            "/admin/manage": "[data-testid=photo-tile]",
            "/admin/manage?tab=gaeste": "[data-testid=guest-row]",
            "/admin/manage?tab=sperren": "#panel-sperren",
            "/admin/manage?tab=protokoll": "[data-testid=audit]",
            f"/admin/user?id={user.id}": "[data-testid=photo-tile]",
        }
        for path, selector in screens.items():
            page.goto(live.url(path))
            expect(page.locator(selector).first).to_be_visible()
            expect(page.get_by_test_id("conn")).to_have_attribute("data-state", "live")
            assert no_horizontal_scroll(page), path
        # three photos side by side on a PC screen, not one long phone column
        page.goto(live.url("/admin/manage"))
        tiles = page.locator("[data-testid=photo-tile]")
        expect(tiles).to_have_count(3)
        tops = {round(box["y"]) for box in (tiles.nth(i).bounding_box() for i in range(3)) if box}
        assert len(tops) == 1, tops
        assert page.js_errors == []
    finally:
        ctx.close()


# ------------------------------------------------------------- screenshots


@pytest.mark.skipif(not os.environ.get("VB_SCREENSHOT_DIR"), reason="set VB_SCREENSHOT_DIR=dir")
@pytest.mark.parametrize("device", ["desktop", "phone"])
def test_screenshots(browser, live, device):
    out = Path(os.environ["VB_SCREENSHOT_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    ctx = new_context(browser, device)
    try:
        page = ctx.new_page()

        def snap(name: str, settle_ms: int = 600) -> None:
            page.wait_for_timeout(settle_ms)  # animations, confetti
            page.screenshot(path=out / f"{device}-{name}.png")

        page.goto(live.entry("/"))
        page.get_by_test_id("consent").wait_for()
        snap("consent")
        accept_consent_in_browser(page)
        page.get_by_test_id("tile-beer").wait_for()
        snap("home", 2400)

        page.goto(live.url("/x/beer/"))
        expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=READY)
        snap("beer")
        page.get_by_test_id("shutter").click()
        expect(page.get_by_test_id("success")).to_be_visible(timeout=READY)
        snap("beer-success", 2600)

        page.goto(live.url("/x/booth/"))
        expect(page.get_by_test_id("booth")).to_have_attribute("data-ready", "1", timeout=READY)
        snap("booth")
        page.get_by_test_id("filter-party").click()
        snap("booth-party", 1700)
        page.get_by_test_id("shutter").click()
        expect(page.get_by_test_id("upload-status")).to_have_attribute("data-state", "done", timeout=READY)
        snap("booth-result", 2600)

        page.goto(live.url("/admin/login"))
        expect(page.locator("#password")).to_be_visible()
        snap("admin-login")
        page.locator("#password").fill(ADMIN_PASSWORD)
        page.keyboard.press("Enter")
        page.wait_for_url(live.url("/admin/live"))
        user = live.core.repo.list_users()[-1]
        for path, name in (("/admin/live", "admin-live"), ("/admin/manage", "admin-manage"),
                           ("/admin/manage?tab=gaeste", "admin-guests"), (f"/admin/user?id={user.id}", "admin-user")):
            page.goto(live.url(path))
            expect(page.get_by_test_id("conn")).to_have_attribute("data-state", "live")
            snap(name, 800)

        page.add_init_script("""Object.defineProperty(MediaDevices.prototype, 'getUserMedia', {
            configurable: true,
            value: () => Promise.reject(new DOMException('denied', 'NotAllowedError')),
        });""")
        page.goto(live.url("/x/beer/"))
        expect(page.locator(".vb-notice")).to_contain_text("Kamera-Zugriff wurde verweigert", timeout=READY)
        snap("beer-camera-denied")
    finally:
        ctx.close()
