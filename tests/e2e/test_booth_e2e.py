"""Fotobox in a real browser: WebGL preview, filter switching (tap + swipe),
capture → upload, countdown, save, camera switch, Canvas2D fallback.

Screenshots for eyeballing the filters (optional):
    VB_BOOTH_SCREENSHOTS=/some/dir [VB_FAKE_VIDEO=clip.y4m] uv run pytest -m e2e tests/e2e/test_booth_e2e.py -k screenshots
"""

from __future__ import annotations

import io
import json
import os
import re
import time
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import Page, expect

from virtubooth.extension import discover_extensions
from virtubooth.extensions.booth import FILTERS
from virtubooth.repo import PhotoQuery

from .conftest import BROWSER_NAME, accept_consent_in_browser, new_context, track_errors

pytestmark = pytest.mark.e2e

READY = 15000


def snap(page: Page, name: str, settle_ms: int = 700) -> None:
    """Screenshot into VB_SCREENSHOT_DIR, if set."""
    out = os.environ.get("VB_SCREENSHOT_DIR")
    if not out:
        return
    page.wait_for_timeout(settle_ms)
    Path(out).mkdir(parents=True, exist_ok=True)
    before = len(page.js_errors)
    page.screenshot(path=str(Path(out) / f"{name}.png"))
    # WebKit logs the CSP refusing the <style> Playwright injects for screenshots: not the page's fault
    page.js_errors[before:] = [e for e in page.js_errors[before:] if "Refused to apply a stylesheet" not in e]


@pytest.fixture
def e2e_extensions():
    return discover_extensions(["booth"])


def open_booth(page: Page, live, query: str = "") -> None:
    page.goto(live.url(f"/x/booth/{query}"))
    expect(page.get_by_test_id("booth")).to_have_attribute("data-ready", "1", timeout=READY)


def select(page: Page, filter_id: str) -> None:
    page.get_by_test_id(f"filter-{filter_id}").click()
    expect(page.get_by_test_id("booth")).to_have_attribute("data-filter", filter_id)


def shoot(page: Page) -> None:
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("result")).to_be_visible(timeout=READY)
    expect(page.get_by_test_id("upload-status")).to_have_attribute("data-state", "done", timeout=READY)


def again(page: Page) -> None:
    page.get_by_test_id("again").click()
    expect(page.get_by_test_id("result")).to_be_hidden()
    expect(page.get_by_test_id("booth")).to_have_attribute("data-screen", "camera")


def stored_images(live) -> list[tuple[dict, Image.Image]]:
    photos = live.core.repo.list_photos(PhotoQuery(extension="booth", order="asc"))
    out = []
    for p in photos:
        img = Image.open(live.core.repo.photo_path("booth", p.filename)).convert("RGB")
        out.append((p.meta, img))
    return out


def swipe(page: Page, dx: int) -> None:
    box = page.get_by_test_id("preview").bounding_box()
    assert box
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x - dx / 2, y)
    page.mouse.down()
    page.mouse.move(x, y + 4, steps=4)
    page.mouse.move(x + dx / 2, y + 6, steps=4)
    page.mouse.up()


def touch_swipe(page: Page, dx: int) -> None:
    """A real touch gesture through the DevTools protocol."""
    box = page.get_by_test_id("preview").bounding_box()
    assert box
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    cdp = page.context.new_cdp_session(page)
    steps = 6
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x - dx / 2, "y": y}]})
    for i in range(1, steps + 1):
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchMove", "touchPoints": [{"x": x - dx / 2 + dx * i / steps, "y": y + i}],
        })
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    cdp.detach()


def gray_error(img: Image.Image) -> float:
    """Mean |R-G| + |G-B| over a grid of sample pixels."""
    w, h = img.size
    total = n = 0
    for y in range(10, h, h // 24):
        for x in range(10, w, w // 18):
            r, g, b = img.getpixel((x, y))
            total += abs(r - g) + abs(g - b)
            n += 1
    return total / n


def border_diff(a: Image.Image, b: Image.Image, width: int = 40) -> float:
    w, h = a.size
    diff = ImageChops.difference(a, b)
    strips = [(0, 0, w, width), (0, h - width, w, h), (0, 0, width, h), (w - width, 0, w, h)]
    return sum(sum(ImageStat.Stat(diff.crop(box)).mean) / 3 for box in strips) / len(strips)


# ----------------------------------------------------------------- tests


def test_preview_runs_on_webgl(guest_page, live):
    open_booth(guest_page, live)
    booth = guest_page.get_by_test_id("booth")
    expect(booth).to_have_attribute("data-renderer", "webgl")
    expect(booth).to_have_attribute("data-filter", "normal")
    expect(booth).to_have_attribute("data-facing", "user")
    expect(booth).to_have_attribute("data-mirror", "1")
    chips = guest_page.get_by_test_id("filter-strip").locator("[data-filter]")
    assert chips.evaluate_all("els => els.map(e => e.dataset.filter)") == list(FILTERS)
    assert guest_page.get_by_test_id("user-chip").is_visible()
    assert guest_page.get_by_test_id("back").get_attribute("href") == "/"
    assert guest_page.js_errors == []


def test_new_guest_sees_consent_before_the_camera(page, live):
    page.goto(live.entry("/x/booth/"))  # straight from the QR code
    page.get_by_test_id("join").wait_for()
    assert page.get_by_test_id("booth").get_attribute("data-ready") is None
    assert page.locator("#video").evaluate("v => v.srcObject") is None  # camera not opened yet
    accept_consent_in_browser(page)
    expect(page.get_by_test_id("booth")).to_have_attribute("data-ready", "1", timeout=READY)
    assert len(live.core.repo.list_users()) == 1
    assert page.js_errors == []


def test_every_filter_compiles_and_renders(guest_page, live):
    open_booth(guest_page, live)
    for fid in FILTERS:
        select(guest_page, fid)
        guest_page.wait_for_timeout(120)
    assert guest_page.js_errors == []


def test_switch_filters_by_tap_and_swipe(guest_page, live):
    open_booth(guest_page, live)
    booth = guest_page.get_by_test_id("booth")
    ids = list(FILTERS)
    select(guest_page, "bw")
    expect(guest_page.get_by_test_id("filter-name")).to_contain_text("Schwarz-Weiß")
    expect(guest_page.get_by_test_id("filter-bw")).to_have_attribute("aria-selected", "true")

    swipe(guest_page, -160)  # finger moves left → next filter
    nxt = ids[ids.index("bw") + 1]
    expect(booth).to_have_attribute("data-filter", nxt)
    expect(guest_page.get_by_test_id("filter-name")).to_contain_text(FILTERS[nxt])
    swipe(guest_page, 160)
    expect(booth).to_have_attribute("data-filter", "bw")
    if BROWSER_NAME == "chromium":  # real touch events need the DevTools protocol
        touch_swipe(guest_page, -160)
    else:
        swipe(guest_page, -160)
    expect(booth).to_have_attribute("data-filter", nxt)
    swipe(guest_page, 20)  # too short: no change
    guest_page.wait_for_timeout(100)
    expect(booth).to_have_attribute("data-filter", nxt)

    select(guest_page, "normal")
    swipe(guest_page, 160)  # wraps around to the last filter
    expect(booth).to_have_attribute("data-filter", ids[-1])
    assert guest_page.js_errors == []


def test_keyboard_on_desktop(guest_page, live):
    open_booth(guest_page, live)
    booth = guest_page.get_by_test_id("booth")
    ids = list(FILTERS)
    guest_page.keyboard.press("ArrowRight")
    expect(booth).to_have_attribute("data-filter", ids[1])
    guest_page.get_by_test_id(f"filter-{ids[1]}").focus()
    guest_page.keyboard.press("ArrowRight")  # works while a chip has focus
    expect(booth).to_have_attribute("data-filter", ids[2])
    guest_page.get_by_test_id(f"filter-{ids[2]}").evaluate("el => el.blur()")
    guest_page.keyboard.press("Space")
    expect(guest_page.get_by_test_id("upload-status")).to_have_attribute("data-state", "done", timeout=READY)
    [(meta, _img)] = stored_images(live)
    assert meta["filter"] == ids[2]
    assert guest_page.js_errors == []


def chip_offset(page: Page, filter_id: str) -> float:
    """Horizontal distance between the chip's centre and the strip's centre."""
    strip = page.get_by_test_id("filter-strip").bounding_box()
    chip = page.get_by_test_id(f"filter-{filter_id}").bounding_box()
    assert strip and chip
    return abs((chip["x"] + chip["width"] / 2) - (strip["x"] + strip["width"] / 2))


@pytest.mark.parametrize("viewport", [(390, 844), (844, 390)], ids=["portrait", "landscape"])
def test_strip_centres_the_selected_filter(guest_page, live, viewport):
    guest_page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    open_booth(guest_page, live)
    for fid in ("vhs", "colorpop"):
        select(guest_page, fid)
        guest_page.wait_for_timeout(700)  # smooth scrolling
        assert chip_offset(guest_page, fid) < 4, fid
    # the preview keeps its 3:4 shape and uses the space
    box = guest_page.get_by_test_id("preview").bounding_box()
    assert box and abs(box["width"] / box["height"] - 0.75) < 0.01
    assert box["width"] > min(viewport) * 0.7, box
    assert guest_page.js_errors == []


def test_capture_bw_is_grayscale_and_uploaded(guest_page, live):
    open_booth(guest_page, live)
    select(guest_page, "bw")
    shoot(guest_page)
    expect(guest_page.get_by_test_id("upload-status")).to_contain_text("Hochgeladen ✓")
    expect(guest_page.get_by_test_id("save")).to_be_visible()
    expect(guest_page.get_by_test_id("result-photo")).to_have_attribute("src", re.compile(r"^blob:"))

    [(meta, img)] = stored_images(live)
    assert meta == {"filter": "bw", "facing": "user"}
    assert img.size == (1080, 1440)
    assert gray_error(img) < 4, gray_error(img)
    assert ImageStat.Stat(img.convert("L")).stddev[0] > 8  # real picture, not a blank canvas
    assert guest_page.js_errors == []


def test_party_frame_differs_at_the_border(guest_page, live):
    open_booth(guest_page, live)
    shoot(guest_page)
    again(guest_page)
    select(guest_page, "party")
    shoot(guest_page)
    (meta_plain, plain), (meta_party, party) = stored_images(live)
    assert meta_plain["filter"] == "normal" and meta_party["filter"] == "party"
    assert border_diff(plain, party) > 40
    # the bottom band is the pink→orange→yellow frame: warm and bright
    r, g, b = ImageStat.Stat(party.crop((0, 1420, 1080, 1440))).mean
    assert r > 200 and r > b + 60, (r, g, b)
    assert guest_page.js_errors == []


@pytest.mark.skipif(BROWSER_NAME == "webkit", reason="WebKit discards a paused WebGL canvas")
def test_photo_is_exactly_the_preview(guest_page, live):
    """WebKit discards a paused WebGL canvas after compositing, so the screenshot
    side of this comparison only works in Chromium; WebKit runs check the stored photo.

    The capture re-renders the frame on screen at 1080×1440: same video frame,
    same mirroring, same overlay. Compare the frozen preview with the stored photo."""
    open_booth(guest_page, live)
    select(guest_page, "party")
    guest_page.wait_for_timeout(1700)  # filter name label faded out
    shoot(guest_page)
    guest_page.evaluate("""() => {
        document.querySelector('[data-testid=result]').classList.add('vb-hidden');
        document.querySelectorAll('.vb-confetti, .vb-flash, .vb-toast-host').forEach((el) => el.remove());
    }""")
    preview = Image.open(io.BytesIO(guest_page.get_by_test_id("preview-canvas").screenshot())).convert("RGB")
    [(_meta, photo)] = stored_images(live)
    photo = photo.resize(preview.size, Image.Resampling.LANCZOS)
    w, h = preview.size
    inner = (int(w * 0.06), int(h * 0.06), int(w * 0.94), int(h * 0.94))  # skip the rounded corners

    def diff(a: Image.Image, b: Image.Image) -> float:
        return sum(ImageStat.Stat(ImageChops.difference(a.crop(inner), b.crop(inner))).mean) / 3

    same = diff(preview, photo)
    mirrored = diff(preview, photo.transpose(Image.Transpose.FLIP_LEFT_RIGHT))
    assert same < 8, same
    assert mirrored > same * 2, (same, mirrored)
    assert guest_page.js_errors == []


LONG_NAME = "Ömers & Jürgens legendäre Sommer-Gartenparty mit Überraschungsgästen 🎉🪩"


def test_long_party_name_in_overlays(guest_page, live):
    live.core.settings = replace(live.core.settings, party_name=LONG_NAME)
    open_booth(guest_page, live)
    assert LONG_NAME in guest_page.title()
    for fid in ("party", "retro"):
        select(guest_page, fid)
        shoot(guest_page)
        if os.environ.get("VB_BOOTH_SCREENSHOTS"):
            guest_page.wait_for_timeout(2500)
            guest_page.screenshot(path=Path(os.environ["VB_BOOTH_SCREENSHOTS"]) / f"long-name-{fid}.png")
        again(guest_page)
    assert len(stored_images(live)) == 2
    assert guest_page.js_errors == []


def test_countdown_delays_the_capture(guest_page, live):
    open_booth(guest_page, live)
    toggle = guest_page.get_by_test_id("countdown-toggle")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    # the choice is remembered
    guest_page.reload()
    expect(guest_page.get_by_test_id("booth")).to_have_attribute("data-ready", "1", timeout=READY)
    expect(guest_page.get_by_test_id("countdown-toggle")).to_have_attribute("aria-pressed", "true")

    start = time.monotonic()
    guest_page.get_by_test_id("shutter").click()
    expect(guest_page.get_by_test_id("countdown")).to_have_text("3")
    assert guest_page.get_by_test_id("result").is_hidden()
    expect(guest_page.get_by_test_id("countdown")).to_have_text("1", timeout=4000)
    expect(guest_page.get_by_test_id("result")).to_be_visible(timeout=8000)
    elapsed = time.monotonic() - start
    assert 2.7 < elapsed < 6, elapsed
    expect(guest_page.get_by_test_id("upload-status")).to_have_attribute("data-state", "done", timeout=READY)
    assert guest_page.js_errors == []


def test_save_downloads_the_photo(guest_page, live):
    open_booth(guest_page, live)
    shoot(guest_page)
    with guest_page.expect_download() as info:
        guest_page.get_by_test_id("save").click()
    download = info.value
    assert download.suggested_filename == "fotobox-1.jpg"
    data = Path(download.path()).read_bytes()
    assert Image.open(io.BytesIO(data)).size == (1080, 1440)
    expect(guest_page.get_by_test_id("save")).to_contain_text("Gespeichert ✓")
    again(guest_page)
    guest_page.get_by_test_id("shutter").click()
    expect(guest_page.get_by_test_id("save")).to_contain_text("Speichern")
    assert guest_page.js_errors == []


def test_switch_camera_and_back_to_camera(guest_page, live):
    open_booth(guest_page, live)
    booth = guest_page.get_by_test_id("booth")
    guest_page.get_by_test_id("switch-camera").click()
    expect(booth).to_have_attribute("data-facing", "environment")
    expect(booth).to_have_attribute("data-mirror", "0")
    expect(booth).to_have_attribute("data-ready", "1", timeout=READY)
    select(guest_page, "sepia")
    shoot(guest_page)
    again(guest_page)
    expect(booth).to_have_attribute("data-filter", "sepia")
    [(meta, _img)] = stored_images(live)
    assert meta == {"filter": "sepia", "facing": "environment"}
    assert guest_page.js_errors == []


def test_double_tap_flips_the_camera(guest_page, live):
    open_booth(guest_page, live)
    booth = guest_page.get_by_test_id("booth")
    guest_page.get_by_test_id("preview").dblclick()
    expect(booth).to_have_attribute("data-facing", "environment")
    expect(booth).to_have_attribute("data-ready", "1", timeout=READY)
    expect(booth).to_have_attribute("data-filter", "normal")  # taps never change the filter
    assert guest_page.js_errors == []


# defined on the prototype: plain assignment doesn't stick in WebKit
DENY_CAMERA = """Object.defineProperty(MediaDevices.prototype, 'getUserMedia', {
    configurable: true,
    value: () => Promise.reject(new DOMException('Permission denied', 'NotAllowedError')),
});"""


def test_camera_denied_shows_a_german_notice(guest_page, live):
    guest_page.add_init_script(DENY_CAMERA)
    guest_page.goto(live.url("/x/booth/"))
    notice = guest_page.get_by_role("alert")
    expect(notice).to_contain_text("Die Kamera geht nicht")
    expect(notice).to_contain_text("Kamera-Zugriff wurde verweigert")
    expect(notice.get_by_role("button", name="Nochmal versuchen")).to_be_visible()
    expect(guest_page.get_by_test_id("shutter")).to_be_disabled()


def rate_limited(route, seconds: int | None = None) -> None:
    """A 429 like the server's. Retry-After is a header there; the SDK may pass it on as
    err.retryAfter, the body field stands in for it until then."""
    body = {"error": "rate_limited", "message": "Langsam! Zu viele Anfragen. Warte kurz und versuch es nochmal."}
    headers = {}
    if seconds is not None:
        body["retry_after"] = seconds
        headers["Retry-After"] = str(seconds)
    route.fulfill(status=429, content_type="application/json", headers=headers, body=json.dumps(body))


def test_upload_error_can_be_retried(guest_page, live):
    open_booth(guest_page, live)
    calls = {"n": 0}

    def fail_once(route):
        calls["n"] += 1
        if calls["n"] == 1:
            rate_limited(route, 2)
        else:
            route.continue_()

    guest_page.route("**/api/x/booth/upload", fail_once)
    guest_page.get_by_test_id("shutter").click()
    status = guest_page.get_by_test_id("upload-status")
    expect(status).to_have_attribute("data-state", "error", timeout=READY)
    expect(status).to_contain_text("Langsam! Zu viele Fotos auf einmal. In 2 s nochmal.")
    retry = guest_page.get_by_test_id("upload-retry")
    expect(retry).to_be_disabled()
    expect(retry).to_contain_text("Nochmal in")
    snap(guest_page, "result-rate-limited", 300)
    expect(retry).to_be_enabled(timeout=4000)
    expect(retry).to_have_text("↻ Nochmal hochladen")
    retry.click()
    expect(status).to_have_attribute("data-state", "done", timeout=READY)
    assert len(stored_images(live)) == 1
    # the failed attempt logs a console error for the 429 response; nothing else
    assert all("429" in e for e in guest_page.js_errors), guest_page.js_errors


def test_failed_upload_left_behind_goes_to_the_outbox(guest_page, live):
    open_booth(guest_page, live)
    offline = {"on": True}

    def maybe_fail(route):
        if offline["on"]:
            route.abort("internetdisconnected")
        else:
            route.continue_()

    guest_page.route("**/api/x/booth/upload", maybe_fail)
    guest_page.get_by_test_id("shutter").click()
    expect(guest_page.get_by_test_id("upload-status")).to_have_attribute("data-state", "error", timeout=READY)
    expect(guest_page.get_by_test_id("upload-status")).to_contain_text("Keine Verbindung")
    again(guest_page)  # move on without retrying
    outbox = guest_page.get_by_test_id("outbox")
    expect(outbox).to_be_visible()
    expect(outbox).to_contain_text("1 nicht hochgeladen")
    offline["on"] = False
    outbox.click()
    expect(outbox).to_be_hidden()
    expect(guest_page.get_by_text("Foto #1 ist hochgeladen ✓")).to_be_visible(timeout=READY)
    assert len(stored_images(live)) == 1
    assert all("ERR_INTERNET_DISCONNECTED" in e for e in guest_page.js_errors), guest_page.js_errors


def test_survives_webgl_context_loss(guest_page, live):
    open_booth(guest_page, live)
    select(guest_page, "party")
    was_lost = guest_page.get_by_test_id("preview-canvas").evaluate("""async (canvas) => {
        const gl = canvas.getContext('webgl');
        const ext = gl.getExtension('WEBGL_lose_context');
        ext.loseContext();
        await new Promise((resolve) => setTimeout(resolve, 250));
        const lost = gl.isContextLost();
        ext.restoreContext();
        return lost;
    }""")
    assert was_lost
    guest_page.wait_for_timeout(300)
    shoot(guest_page)
    [(meta, img)] = stored_images(live)
    assert meta["filter"] == "party"
    r, g, b = ImageStat.Stat(img.crop((0, 1420, 1080, 1440))).mean
    assert r > 200 and r > b + 60, (r, g, b)  # the frame overlay came back too
    assert guest_page.js_errors == []


def test_canvas2d_fallback(guest_page, live):
    open_booth(guest_page, live, "?renderer=canvas2d")
    booth = guest_page.get_by_test_id("booth")
    expect(booth).to_have_attribute("data-renderer", "canvas2d")
    ids = guest_page.get_by_test_id("filter-strip").locator("[data-filter]").evaluate_all(
        "els => els.map(e => e.dataset.filter)")
    assert {"normal", "bw", "sepia", "party", "emoji"} <= set(ids)
    select(guest_page, "bw")
    shoot(guest_page)
    again(guest_page)
    select(guest_page, "party")
    shoot(guest_page)
    (meta_bw, bw), (meta_party, party) = stored_images(live)
    assert meta_bw["filter"] == "bw" and gray_error(bw) < 4
    assert bw.size == party.size == (1080, 1440)
    r, g, b = ImageStat.Stat(party.crop((0, 1420, 1080, 1440))).mean
    assert r > 200 and r > b + 60, (r, g, b)
    assert guest_page.js_errors == []


@pytest.mark.skipif(not os.environ.get("VB_BOOTH_SCREENSHOTS"), reason="set VB_BOOTH_SCREENSHOTS=dir")
def test_screenshots(guest_page, live):
    out = Path(os.environ["VB_BOOTH_SCREENSHOTS"])
    out.mkdir(parents=True, exist_ok=True)
    page = guest_page
    open_booth(page, live)
    page.wait_for_timeout(400)
    page.screenshot(path=out / "camera-normal.png")
    for fid in FILTERS:
        if fid == "normal":
            continue
        select(page, fid)
        page.wait_for_timeout(1700)  # let the name label fade
        page.screenshot(path=out / f"camera-{fid}.png")
    select(page, "party")
    page.wait_for_timeout(300)
    page.screenshot(path=out / "camera-name-label.png")
    shoot(page)
    page.wait_for_timeout(2600)  # confetti gone
    page.screenshot(path=out / "result.png")
    again(page)
    for fid in FILTERS:
        if fid == "party":
            continue
        select(page, fid)
        page.wait_for_timeout(300)
        page.get_by_test_id("shutter").click()
        expect(page.get_by_test_id("result")).to_be_visible(timeout=READY)
        again(page)
    page.wait_for_timeout(1500)
    for meta, img in stored_images(live):
        img.save(out / f"photo-{meta['filter']}.jpg")

    # countdown in progress
    page.reload()
    expect(page.get_by_test_id("booth")).to_have_attribute("data-ready", "1", timeout=READY)
    select(page, "neon")
    page.get_by_test_id("countdown-toggle").click()
    page.wait_for_timeout(1500)
    page.get_by_test_id("shutter").click()
    page.wait_for_timeout(350)
    page.screenshot(path=out / "countdown.png")
    expect(page.get_by_test_id("result")).to_be_visible(timeout=READY)

    # other phone sizes
    for name, size in (("small", (375, 667)), ("landscape", (844, 390)), ("tablet", (820, 1180))):
        page.set_viewport_size({"width": size[0], "height": size[1]})
        open_booth(page, live)
        select(page, "party")
        page.wait_for_timeout(1700)
        page.screenshot(path=out / f"layout-{name}.png")
    page.set_viewport_size({"width": 390, "height": 844})

    # Canvas2D fallback
    open_booth(page, live, "?renderer=canvas2d")
    select(page, "sepia")
    page.wait_for_timeout(1700)
    page.screenshot(path=out / "fallback-sepia.png")

    # camera error
    page.add_init_script(DENY_CAMERA)
    page.goto(live.url("/x/booth/"))
    expect(page.get_by_role("alert")).to_contain_text("Die Kamera geht nicht")
    page.screenshot(path=out / "camera-denied.png")


# ------------------------------------------------- failures and leaving


def leaving_is_blocked(page: Page) -> bool:
    """Whether the page asks before it goes (beforeunload cancelled)."""
    return page.evaluate("""() => {
        const e = new Event('beforeunload', { cancelable: true });
        window.dispatchEvent(e);
        return e.defaultPrevented;
    }""")


def kept_on_phone(page: Page) -> int:
    """Photos in the page's IndexedDB outbox."""
    return page.evaluate("""() => new Promise((resolve, reject) => {
        const req = indexedDB.open('vb-booth', 1);
        req.onupgradeneeded = () => req.result.createObjectStore('outbox', { keyPath: 'id' });
        req.onerror = () => reject(req.error);
        req.onsuccess = () => {
            const db = req.result;
            const count = db.transaction('outbox').objectStore('outbox').count();
            count.onsuccess = () => { db.close(); resolve(count.result); };
            count.onerror = () => reject(count.error);
        };
    })""")


class Network:
    """Upload requests fail while `offline` is set."""

    def __init__(self, page: Page) -> None:
        self.offline = True
        page.route("**/api/x/booth/upload", self.handle)

    def handle(self, route) -> None:
        if self.offline:
            route.abort("internetdisconnected")
        else:
            route.continue_()


def shoot_offline(page: Page) -> None:
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("upload-status")).to_have_attribute("data-state", "error", timeout=READY)
    expect(page.get_by_test_id("upload-status")).to_contain_text("Keine Verbindung")


def network_errors_only(page: Page) -> list[str]:
    return [e for e in page.js_errors if "ERR_INTERNET_DISCONNECTED" not in e and "NetworkError" not in e
            and "Load failed" not in e and "network connection was lost" not in e]


def wait_kept(page: Page, n: int) -> None:
    deadline = time.monotonic() + 10
    while (count := kept_on_phone(page)) != n:
        assert time.monotonic() < deadline, f"{count} photos kept on the phone, expected {n}"
        page.wait_for_timeout(100)


def test_unsent_photo_survives_a_reload(guest_page, live):
    page = guest_page
    open_booth(page, live)
    net = Network(page)
    shoot_offline(page)
    wait_kept(page, 1)
    assert not leaving_is_blocked(page)  # it is safe on the phone: no browser prompt needed
    again(page)
    expect(page.get_by_test_id("outbox")).to_contain_text("1 nicht hochgeladen")

    # reload while still offline: the photo is back in the outbox
    page.reload()
    expect(page.get_by_test_id("booth")).to_have_attribute("data-ready", "1", timeout=READY)
    expect(page.get_by_test_id("outbox")).to_contain_text("1 nicht hochgeladen", timeout=READY)
    assert stored_images(live) == []

    # online again: the next visit sends it on its own
    net.offline = False
    page.reload()
    expect(page.get_by_text("von vorhin ist jetzt hochgeladen")).to_be_visible(timeout=READY)
    expect(page.get_by_test_id("outbox")).to_be_hidden()
    [(meta, img)] = stored_images(live)
    assert meta == {"filter": "normal", "facing": "user"} and img.size == (1080, 1440)
    wait_kept(page, 0)
    assert network_errors_only(page) == []


def test_back_button_asks_before_leaving_unsent_photos(guest_page, live):
    page = guest_page
    open_booth(page, live)
    net = Network(page)
    shoot_offline(page)
    again(page)
    select(page, "bw")
    shoot_offline(page)
    again(page)
    outbox = page.get_by_test_id("outbox")
    expect(outbox).to_contain_text("2 nicht hochgeladen")
    wait_kept(page, 2)

    page.get_by_test_id("back").click()
    sheet = page.get_by_test_id("leave")
    expect(sheet).to_contain_text("2 Fotos sind noch nicht hochgeladen")
    expect(sheet).to_contain_text("sobald du die Fotobox wieder öffnest")
    assert page.url == live.url("/x/booth/")
    snap(page, "leave-sheet", 400)
    # the page's shortcuts wait while the sheet is open
    page.evaluate("() => document.activeElement.blur()")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Space")
    page.wait_for_timeout(300)
    expect(page.get_by_test_id("booth")).to_have_attribute("data-filter", "bw")
    expect(page.get_by_test_id("result")).to_be_hidden()

    # stay: tries again (still offline), the photos stay in the outbox
    sheet.get_by_test_id("leave-stay").click()
    expect(sheet).to_have_count(0)
    expect(outbox).to_contain_text("2 nicht hochgeladen", timeout=READY)
    page.get_by_test_id("back").click()
    page.keyboard.press("Escape")  # closes the sheet too
    expect(sheet).to_have_count(0)
    assert page.url == live.url("/x/booth/")

    # leave anyway: home, no browser prompt on the way
    page.get_by_test_id("back").click()
    sheet.get_by_test_id("leave-go").click()
    page.wait_for_url(live.url("/"))
    expect(page.get_by_test_id("tile-booth")).to_be_visible()  # home has booted: nothing left in flight

    # back online, back in the Fotobox: both are sent
    net.offline = False
    open_booth(page, live)
    expect(outbox).to_be_hidden()
    deadline = time.monotonic() + 10
    while len(stored_images(live)) < 2 and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    assert sorted(meta["filter"] for meta, _ in stored_images(live)) == ["bw", "normal"]
    wait_kept(page, 0)
    page.get_by_test_id("back").click()  # nothing unsent: straight home
    page.wait_for_url(live.url("/"))
    expect(page.get_by_test_id("tile-booth")).to_be_visible()
    assert network_errors_only(page) == []


NO_INDEXEDDB = "Object.defineProperty(window, 'indexedDB', { configurable: true, get: () => undefined });"


def test_without_storage_leaving_warns_that_photos_are_lost(guest_page, live):
    page = guest_page
    page.add_init_script(NO_INDEXEDDB)
    open_booth(page, live)
    net = Network(page)
    assert not leaving_is_blocked(page)
    shoot_offline(page)
    assert leaving_is_blocked(page)  # on the result screen already
    again(page)
    assert leaving_is_blocked(page)
    page.get_by_test_id("back").click()
    expect(page.get_by_test_id("leave")).to_contain_text("Wenn du jetzt gehst, ist es weg.")
    net.offline = False
    page.get_by_test_id("leave-stay").click()  # stays and tries again
    expect(page.get_by_text("Foto #1 ist hochgeladen ✓")).to_be_visible(timeout=READY)
    expect(page.get_by_test_id("outbox")).to_be_hidden()
    assert not leaving_is_blocked(page)
    assert len(stored_images(live)) == 1
    assert network_errors_only(page) == []


def test_leaving_mid_upload_warns(guest_page, live):
    page = guest_page
    open_booth(page, live)
    page.route("**/api/x/booth/upload", lambda route: None)  # never answers
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("upload-status")).to_have_attribute("data-state", "uploading")
    assert leaving_is_blocked(page)


def test_boot_failure_offers_a_reload(page, live):
    """/api/identify fails (flaky WiFi, a blocker): no endless "Kamera startet …"."""
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    page.route("**/api/identify", lambda route: route.abort())
    page.goto(live.url("/x/booth/"))
    notice = page.get_by_role("alert").filter(has_text="Ups")
    expect(notice).to_contain_text("Keine Verbindung")
    expect(notice.get_by_role("link", name="Zur Startseite")).to_be_visible()
    expect(page.get_by_text("Kamera startet")).to_be_hidden()
    snap(page, "boot-failed")
    page.unroute("**/api/identify")
    notice.get_by_role("button", name="Neu laden").click()
    expect(page.get_by_test_id("booth")).to_have_attribute("data-ready", "1", timeout=READY)
    expect(page.locator(".vb-notice")).to_have_count(0)


def test_filter_catalogue_failure_offers_a_reload(guest_page, live):
    page = guest_page
    page.route("**/x/booth/filters.json", lambda route: route.abort())
    page.goto(live.url("/x/booth/"))
    notice = page.get_by_role("alert").filter(has_text="Ups")
    expect(notice.get_by_role("button", name="Neu laden")).to_be_visible()
    expect(page.get_by_text("Kamera startet")).to_be_hidden()


def test_shortcuts_wait_while_a_dialog_is_open(guest_page, live):
    page = guest_page
    open_booth(page, live)
    booth = page.get_by_test_id("booth")
    page.evaluate("""() => {
        document.querySelector('[data-testid=user-chip]').click();
        if (!document.querySelector('.vb-scrim')) throw new Error('no dialog');
        document.activeElement.blur();
    }""")
    assert page.evaluate("() => document.activeElement === document.body")
    for key in ("ArrowRight", "ArrowLeft", "ArrowRight", "Space", "Enter"):
        page.keyboard.press(key)
    page.locator(".vb-scrim input").first.focus()
    page.keyboard.type("a b ")
    page.keyboard.press("ArrowLeft")  # moves the cursor in the field, not the filter
    page.wait_for_timeout(400)
    expect(booth).to_have_attribute("data-filter", "normal")
    expect(page.get_by_test_id("result")).to_be_hidden()
    assert stored_images(live) == []

    page.evaluate("() => { document.querySelector('.vb-scrim').remove(); document.activeElement.blur(); }")
    page.keyboard.press("ArrowRight")
    expect(booth).to_have_attribute("data-filter", list(FILTERS)[1])
    page.keyboard.press("Space")
    expect(page.get_by_test_id("upload-status")).to_have_attribute("data-state", "done", timeout=READY)
    assert guest_page.js_errors == []


def test_banned_guest_gets_a_way_home(guest_page, live):
    page = guest_page
    user = live.core.repo.list_users()[0]
    live.core.repo.ban_user(user.id, "test", "admin:test")
    page.goto(live.url("/x/booth/"))
    notice = page.get_by_test_id("banned")
    expect(notice).to_contain_text("Gesperrt")
    expect(page.locator(".vb-notice")).to_have_count(1)
    expect(page.get_by_text("Kamera startet")).to_be_hidden()
    assert page.locator("#video").evaluate("v => v.srcObject") is None
    snap(page, "banned")
    notice.get_by_role("link", name="Zur Startseite").click()
    page.wait_for_url(live.url("/"))


def test_banned_mid_party(guest_page, live):
    page = guest_page
    open_booth(page, live)
    user = live.core.repo.list_users()[0]
    live.core.repo.ban_user(user.id, "test", "admin:test")
    page.get_by_test_id("shutter").click()
    status = page.get_by_test_id("upload-status")
    expect(status).to_have_attribute("data-state", "error", timeout=READY)
    expect(status).to_contain_text("gesperrt")
    expect(page.get_by_test_id("upload-retry")).to_be_hidden()  # retrying can't help
    expect(page.get_by_test_id("again")).to_be_hidden()  # neither can more photos
    expect(page.get_by_test_id("upload-home")).to_be_visible()
    expect(page.get_by_test_id("save")).to_be_visible()  # the photo is still theirs to keep
    snap(page, "result-banned", 300)
    assert not leaving_is_blocked(page)
    page.keyboard.press("Escape")  # leaving the result: the notice, not the camera
    expect(page.get_by_test_id("banned")).to_be_visible()
    expect(page.get_by_test_id("outbox")).to_be_hidden()
    page.get_by_test_id("banned").get_by_role("link", name="Zur Startseite").click()
    page.wait_for_url(live.url("/"))
    assert stored_images(live) == []


PAUSED_MESSAGE = "Deine Uploads sind gerade pausiert. Sprich die Gastgeber an."


def uploads_paused(route) -> None:
    """The server's answer while the hosts paused this guest's uploads."""
    route.fulfill(status=403, content_type="application/json",
                  body=json.dumps({"error": "uploads_paused", "message": PAUSED_MESSAGE}))


def test_paused_uploads_offer_no_retry(guest_page, live):
    page = guest_page
    open_booth(page, live)
    page.route("**/api/x/booth/upload", uploads_paused)
    page.get_by_test_id("shutter").click()
    status = page.get_by_test_id("upload-status")
    expect(status).to_have_attribute("data-state", "error", timeout=READY)
    expect(status).to_contain_text(PAUSED_MESSAGE)
    expect(page.get_by_test_id("upload-retry")).to_be_hidden()
    expect(page.get_by_test_id("upload-home")).to_be_visible()
    expect(page.get_by_test_id("save")).to_be_visible()
    assert not leaving_is_blocked(page)
    snap(page, "result-paused", 300)
    again(page)  # the camera still works, nothing piles up in the outbox
    expect(page.get_by_test_id("outbox")).to_be_hidden()
    expect(page.get_by_test_id("banned")).to_have_count(0)
    page.get_by_test_id("back").click()  # nothing unsent: no question
    page.wait_for_url(live.url("/"))
    assert stored_images(live) == []


def test_paused_uploads_keep_photos_from_before(guest_page, live):
    """A photo kept on the phone from an offline moment waits out the pause."""
    page = guest_page
    open_booth(page, live)
    Network(page)
    shoot_offline(page)
    wait_kept(page, 1)
    again(page)
    page.unroute("**/api/x/booth/upload")
    page.route("**/api/x/booth/upload", uploads_paused)
    page.reload()
    expect(page.get_by_role("status").or_(page.get_by_role("alert")).filter(has_text=PAUSED_MESSAGE)).to_be_visible(
        timeout=READY)
    expect(page.get_by_test_id("outbox")).to_be_hidden()
    assert kept_on_phone(page) == 1
    assert not leaving_is_blocked(page)
    page.unroute("**/api/x/booth/upload")
    page.reload()  # the pause is over
    expect(page.get_by_text("von vorhin ist jetzt hochgeladen")).to_be_visible(timeout=READY)
    wait_kept(page, 0)
    assert len(stored_images(live)) == 1


# ------------------------------------------------------------- layout


def animations_done(page: Page) -> None:
    """Wait for the drop-in/pop-in animations (not the endless pulses) before measuring."""
    page.evaluate("""() => Promise.all(document.getAnimations()
        .filter((a) => a.effect && a.effect.getComputedTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => null)))""")


def inside(page: Page, testid: str) -> dict:
    """The element is fully on screen, without scrolling."""
    box = page.get_by_test_id(testid).bounding_box()
    size = page.viewport_size
    assert box and size, testid
    assert box["x"] >= -1 and box["y"] >= -1, (testid, box)
    assert box["x"] + box["width"] <= size["width"] + 1, (testid, box, size)
    assert box["y"] + box["height"] <= size["height"] + 1, (testid, box, size)
    return box


def test_phone_landscape_result_fits(guest_page, live):
    page = guest_page
    page.set_viewport_size({"width": 844, "height": 390})
    open_booth(page, live)
    for testid in ("shutter", "countdown-toggle", "back", "user-chip", "preview"):
        inside(page, testid)
    snap(page, "landscape-camera", 1700)
    shoot(page)
    animations_done(page)
    for testid in ("save", "again", "upload-status", "result-photo"):
        inside(page, testid)
    sizes = page.get_by_test_id("result").evaluate("el => [el.scrollHeight, el.clientHeight]")
    assert sizes[0] <= sizes[1] + 1, sizes  # nothing below the fold
    photo = page.get_by_test_id("result-photo").bounding_box()
    assert photo and photo["height"] > 250, photo
    snap(page, "landscape-result", 2600)


def test_phone_portrait_top_bar(guest_page, live):
    page = guest_page
    open_booth(page, live)
    chip = inside(page, "user-chip")
    assert chip["width"] >= 150, chip
    inside(page, "back")
    snap(page, "portrait-camera", 300)
    Network(page)
    shoot_offline(page)
    snap(page, "result-offline", 300)
    again(page)
    expect(page.get_by_test_id("outbox")).to_be_visible()
    for testid in ("outbox", "user-chip", "back"):
        inside(page, testid)
    assert page.get_by_test_id("user-chip").bounding_box()["width"] >= 100  # type: ignore[index]
    snap(page, "portrait-outbox", 300)
    assert network_errors_only(page) == []


def test_desktop_shows_every_filter(browser, live):
    ctx = new_context(browser, "desktop")
    try:
        page = track_errors(ctx.new_page())
        page.goto(live.entry("/x/booth/"))
        accept_consent_in_browser(page)
        expect(page.get_by_test_id("booth")).to_have_attribute("data-ready", "1", timeout=READY)
        strip = page.get_by_test_id("filter-strip")
        expect(strip).to_have_class(re.compile(r"\bis-fit\b"))
        box = strip.bounding_box()
        assert box
        lefts = []
        for fid in FILTERS:
            chip = page.get_by_test_id(f"filter-{fid}").bounding_box()
            assert chip and chip["x"] >= box["x"] and chip["x"] + chip["width"] <= box["x"] + box["width"], fid
            lefts.append(chip["x"])
        middle = (lefts[0] + lefts[-1] + 78) / 2
        assert abs(middle - (box["x"] + box["width"] / 2)) < 4  # one centred group
        assert strip.evaluate("el => el.scrollWidth <= el.clientWidth")
        page.keyboard.press("ArrowLeft")  # wraps to the last filter: nothing scrolls away
        expect(page.get_by_test_id("booth")).to_have_attribute("data-filter", list(FILTERS)[-1])
        page.wait_for_timeout(500)
        assert page.get_by_test_id("filter-normal").bounding_box()["x"] == pytest.approx(lefts[0], abs=1)  # type: ignore[index]
        snap(page, "desktop-camera", 1700)
        page.set_viewport_size({"width": 390, "height": 844})  # narrow window: back to a scrolling strip
        expect(strip).not_to_have_class(re.compile(r"\bis-fit\b"))
        assert page.js_errors == []
    finally:
        ctx.close()
