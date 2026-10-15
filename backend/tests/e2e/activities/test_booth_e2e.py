"""Fotobox in a real browser: WebGL preview, filter carousel (tap, swipe, keys),
countdown, capture → print → upload, save, camera switch, Canvas2D fallback.

Ported from the pre-overhaul test_booth_e2e.py to the new UI (same behaviours, new
selectors). The filter catalogue now comes from GET /api/x/booth/filters.
"""

from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import Page, Route, expect

from virtubooth.extensions.booth import FILTERS

from ..conftest import (
    BROWSER_NAME,
    QUICK_TAP_MS,
    LiveServer,
    accept_consent_in_browser,
    covered_by_toast,
)
from .conftest import (
    READY,
    Admin,
    Network,
    add_photos,
    again,
    errors_except,
    expect_uploaded,
    leaving_is_blocked,
    media_size,
    network_errors_only,
    open_beer,
    open_booth,
    photos,
    reload,
    select_filter,
    settled_box,
    shoot,
    shot,
    stored_images,
    wait_for_photos,
    wait_kept,
)

pytestmark = pytest.mark.e2e

IDS = list(FILTERS)


def gray_error(img: Image.Image) -> float:
    """Mean |R-G| + |G-B| over a grid of sample pixels."""
    w, h = img.size
    total = n = 0
    for y in range(10, h, h // 24):
        for x in range(10, w, w // 18):
            r, g, b = img.getpixel((x, y))  # type: ignore[misc]
            total += abs(r - g) + abs(g - b)
            n += 1
    return total / n


def colourful_share(img: Image.Image) -> float:
    """Share of strongly coloured pixels (HSV saturation and value above half). Every
    fake camera shows some: Chromium's pattern, WebKit's blue and red patches (the rest of
    WebKit's mock picture is black, white and gray, so a sampled gray check depends on
    when its cyan text blinks)."""
    _h, sat, val = img.convert("HSV").split()
    mask = ImageChops.multiply(sat.point(lambda v: 255 if v > 128 else 0),
                               val.point(lambda v: 255 if v > 128 else 0))  # fmt: skip
    return ImageStat.Stat(mask).mean[0] / 255


def border_diff(a: Image.Image, b: Image.Image, width: int = 40) -> float:
    w, h = a.size
    diff = ImageChops.difference(a, b)
    strips = [(0, 0, w, width), (0, h - width, w, h), (0, 0, width, h), (w - width, 0, w, h)]
    return sum(sum(ImageStat.Stat(diff.crop(box)).mean) / 3 for box in strips) / len(strips)


def warm_bottom(img: Image.Image) -> bool:
    """The party frame's bottom band: pink → orange → yellow."""
    r, _g, b = ImageStat.Stat(img.crop((0, 1420, 1080, 1440))).mean
    return r > 200 and r > b + 60


def booth(page: Page):  # type: ignore[no-untyped-def]
    return page.get_by_test_id("booth")


def strip_ids(page: Page) -> list[str]:
    return (
        page.get_by_test_id("filter-strip")
        .locator("[data-filter]")
        .evaluate_all("els => els.map(e => e.dataset.filter)")
    )


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
    cdp.send(
        "Input.dispatchTouchEvent",
        {"type": "touchStart", "touchPoints": [{"x": x - dx / 2, "y": y}]},
    )
    for i in range(1, 7):
        cdp.send(
            "Input.dispatchTouchEvent",
            {"type": "touchMove", "touchPoints": [{"x": x - dx / 2 + dx * i / 6, "y": y + i}]},
        )
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    cdp.detach()


# ----------------------------------------------------------------- basics


def test_preview_runs_on_webgl_with_the_catalogue(guest: Page, live: LiveServer):
    open_booth(guest, live)
    b = booth(guest)
    expect(b).to_have_attribute("data-renderer", "webgl")
    expect(b).to_have_attribute("data-filter", "normal")
    expect(b).to_have_attribute("data-facing", "user")
    expect(b).to_have_attribute("data-mirror", "1")
    assert strip_ids(guest) == IDS  # GET /api/x/booth/filters, in strip order
    expect(guest.get_by_test_id("filter-normal")).to_have_attribute("aria-selected", "true")
    expect(guest.get_by_test_id("filter-name")).to_have_text("Normal")
    assert guest.get_by_test_id("back").get_attribute("href") == "/"
    expect(guest.get_by_test_id("guest-pass")).to_be_visible()
    # swatches of the guest's own picture appear
    expect(guest.get_by_test_id("filter-bw").locator("img")).to_be_visible(timeout=READY)
    shot(guest, "booth-camera", 300)
    assert guest.js_errors == []


def test_new_guest_joins_before_the_camera(page: Page, live: LiveServer):
    """Straight from the QR code: the join sheet first, and no camera prompt behind it."""
    page.add_init_script(
        "window.__gum = 0; const g = MediaDevices.prototype.getUserMedia;"
        "MediaDevices.prototype.getUserMedia = function (c) { window.__gum++; return g.call(this, c); };"
    )
    page.goto(live.entry("/x/booth/"))
    page.get_by_test_id("join").wait_for()
    assert page.evaluate("() => window.__gum") == 0
    expect(page.get_by_test_id("booth")).to_have_count(0)
    accept_consent_in_browser(page)
    expect(booth(page)).to_have_attribute("data-ready", "1", timeout=READY)
    assert page.evaluate("() => window.__gum") == 1
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_every_filter_compiles_and_renders(guest: Page, live: LiveServer):
    open_booth(guest, live)
    for fid in IDS:
        select_filter(guest, fid)
        guest.wait_for_timeout(150)
    assert guest.js_errors == []


def test_switch_filters_by_tap_swipe_and_wrap(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    b = booth(page)
    select_filter(page, "bw")
    expect(page.get_by_test_id("filter-name")).to_have_text("Schwarz-Weiß")
    expect(page.get_by_test_id("filter-bw")).to_have_attribute("aria-selected", "true")

    nxt = IDS[IDS.index("bw") + 1]
    swipe(page, -160)  # finger moves left → next filter
    expect(b).to_have_attribute("data-filter", nxt)
    expect(page.get_by_test_id("filter-name")).to_have_text(FILTERS[nxt])
    swipe(page, 160)
    expect(b).to_have_attribute("data-filter", "bw")
    if BROWSER_NAME == "chromium":  # real touch events need the DevTools protocol
        touch_swipe(page, -160)
    else:
        swipe(page, -160)
    expect(b).to_have_attribute("data-filter", nxt)
    swipe(page, 20)  # too short: no change
    page.wait_for_timeout(150)
    expect(b).to_have_attribute("data-filter", nxt)

    select_filter(page, "normal")
    swipe(page, 160)  # wraps around to the last filter
    expect(b).to_have_attribute("data-filter", IDS[-1])
    assert page.js_errors == []


def test_keyboard(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    b = booth(page)
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("ArrowRight")
    expect(b).to_have_attribute("data-filter", IDS[1])
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")  # wraps
    expect(b).to_have_attribute("data-filter", IDS[-1])
    page.get_by_test_id(f"filter-{IDS[-1]}").focus()
    page.keyboard.press("ArrowRight")  # in the strip: moves and selects, wrapping
    expect(b).to_have_attribute("data-filter", IDS[0])
    page.keyboard.press("ArrowRight")
    expect(b).to_have_attribute("data-filter", IDS[1])
    expect(page.get_by_test_id(f"filter-{IDS[1]}")).to_be_focused()
    page.evaluate("() => document.activeElement.blur()")
    page.keyboard.press("Space")
    expect(page.get_by_test_id("result-photo")).to_be_visible(timeout=READY)
    expect_uploaded(page)
    # the main action takes the focus; „Herunterladen“ is optional
    expect(page.get_by_test_id("again")).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("result-photo")).to_have_count(0)
    expect(page.get_by_test_id("shutter")).to_be_focused()
    page.keyboard.press("ArrowRight")  # also while the shutter has focus
    expect(b).to_have_attribute("data-filter", IDS[2])
    [(meta, _img)] = stored_images(live, "booth")
    assert meta["filter"] == IDS[1]
    assert page.js_errors == []


@pytest.mark.parametrize("viewport", [(390, 844), (844, 390)], ids=["portrait", "landscape"])
def test_strip_centres_the_selected_filter(
    guest: Page, live: LiveServer, viewport: tuple[int, int]
):
    guest.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    open_booth(guest, live)
    strip = guest.get_by_test_id("filter-strip")

    def offset(fid: str) -> float:
        s = strip.bounding_box()
        c = guest.get_by_test_id(f"filter-{fid}").bounding_box()
        assert s and c
        return abs((c["x"] + c["width"] / 2) - (s["x"] + s["width"] / 2))

    for fid in ("vhs", "colorpop", "normal", "comic"):
        select_filter(guest, fid)
        # smooth scrolling is slow on a busy machine; a strip that changes size while
        # it scrolls re-centres itself (FilterStrip)
        deadline = time.monotonic() + 10
        while offset(fid) >= 4 and time.monotonic() < deadline:
            guest.wait_for_timeout(100)
        assert offset(fid) < 4, (fid, offset(fid))
    box = guest.get_by_test_id("preview").bounding_box()
    assert box and abs(box["width"] / box["height"] - 0.75) < 0.01
    assert box["width"] > min(viewport) * 0.7, box
    assert guest.js_errors == []


# ----------------------------------------------------------------- the number


def test_film_edge_shows_the_next_number_before_the_first_photo(guest: Page, live: LiveServer):
    """GET /api/x/booth/stats: the film edge knows the next number before this visit's
    first upload (other guests took 1 and 2), the print gets it, the edge moves on."""
    page = guest
    add_photos(live, "booth", 2)
    open_booth(page, live)
    edge = page.get_by_test_id("next-number")
    expect(edge).to_have_attribute("data-next", "3")
    expect(edge).to_contain_text("0003")
    shoot(page)
    expect(page.get_by_test_id("upload-status")).to_contain_text("0003")
    again(page)
    expect(page.get_by_test_id("next-number")).to_have_attribute("data-next", "4")
    assert page.js_errors == []


# ----------------------------------------------------------------- the photo


def test_capture_bw_is_grayscale_exact_size_and_uploaded(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    select_filter(page, "bw")
    shoot(page)
    status = page.get_by_test_id("upload-status")
    expect(status).to_contain_text("Hochgeladen")
    expect(status).to_contain_text("0001")
    # the headline is the upload state, as a live region
    result = page.get_by_role("status").filter(has=page.get_by_test_id("upload-title"))
    expect(result).to_have_attribute("data-state", "done")
    expect(page.get_by_test_id("upload-title")).to_have_text("Hochgeladen")
    expect(result).to_contain_text("mehr musst du nicht tun")
    expect(page.get_by_test_id("save")).to_have_text("Herunterladen")
    expect(page.get_by_test_id("result-photo")).to_have_attribute("src", re.compile(r"^blob:"))
    shot(page, "booth-result", 900)

    [photo] = photos(live, "booth")
    [(meta, img)] = stored_images(live, "booth")
    assert meta == {"filter": "bw", "facing": "user"}
    assert img.size == (1080, 1440)
    assert media_size(page, photo.url) == (1080, 1440)
    assert gray_error(img) < 4, gray_error(img)
    assert ImageStat.Stat(img.convert("L")).stddev[0] > 8  # a real picture, not a blank canvas
    mine = page.evaluate(
        "async () => (await (await fetch('/api/me/photos')).json()).photos.map((p) => p.id)"
    )
    assert mine == [photo.public_id]
    assert page.js_errors == []


def test_party_frame_differs_at_the_border(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    shoot(page)
    again(page)
    select_filter(page, "party")
    shoot(page)
    (meta_plain, plain), (meta_party, party) = stored_images(live, "booth")
    assert meta_plain["filter"] == "normal" and meta_party["filter"] == "party"
    # "Normal" keeps the colours (a gray photo has none; the patches alone are ~0.7 %)
    assert colourful_share(plain) > 0.002, colourful_share(plain)
    assert border_diff(plain, party) > 40
    assert warm_bottom(party)
    assert page.js_errors == []


@pytest.mark.skipif(BROWSER_NAME == "webkit", reason="WebKit discards a paused WebGL canvas")
@pytest.mark.parametrize("filter_id", ["party", "thermal", "disco", "kaleido", "glow"])
def test_photo_is_exactly_the_preview(guest: Page, live: LiveServer, filter_id: str):
    """The capture renders the frozen frame again at 1080×1440: same video frame, same
    mirroring, same overlay, same time (animated filters). Compare the frozen preview
    with the stored photo."""
    page = guest
    open_booth(page, live)
    select_filter(page, filter_id)
    page.wait_for_timeout(500)
    shoot(page)
    # the capture flash (a white layer over everything, gone after ~180 ms) is not part
    # of the preview: an upload that answers quickly leaves it on the screenshot
    expect(page.locator(".vb-flash")).to_have_count(0)
    page.get_by_test_id("result-photo").evaluate("el => { el.style.visibility = 'hidden'; }")
    preview = Image.open(io.BytesIO(page.get_by_test_id("preview-canvas").screenshot())).convert(
        "RGB"
    )
    [(_meta, photo)] = stored_images(live, "booth")
    photo = photo.resize(preview.size, Image.Resampling.LANCZOS)

    def diff(a: Image.Image, b: Image.Image) -> float:
        return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3

    same = diff(preview, photo)
    mirrored = diff(preview, photo.transpose(Image.Transpose.FLIP_LEFT_RIGHT))
    assert same < 8, same
    # the mirroring is the renderer's: not where the picture is (nearly) symmetric, the
    # kaleidoscope's ring of mirrored copies, or flat, the fake camera's green test card
    # in the heat palette, and in Firefox the neon lines too: its flat green camera has
    # no edges to draw them on (the picture is a dark room; on CI's software GL the
    # rendering noise outweighs the few lit pixels of the overlay)
    flat = ("kaleido", "thermal", "glow") if BROWSER_NAME == "firefox" else ("kaleido", "thermal")
    if filter_id not in flat:
        assert mirrored > same * 2, (same, mirrored)
    assert page.js_errors == []


LONG_NAME = "Ömers & Jürgens legendäre Sommer-Gartenparty mit Überraschungsgästen 🎉🪩"


@pytest.mark.parametrize("e2e_settings", [{"party_name": LONG_NAME}])
def test_long_party_name_in_overlays(guest: Page, live: LiveServer, e2e_settings: dict[str, Any]):
    page = guest
    open_booth(page, live)
    expect(page).to_have_title(re.compile(re.escape(LONG_NAME)))
    for fid in ("party", "retro"):
        select_filter(page, fid)
        shoot(page)
        again(page)
    assert len(stored_images(live, "booth")) == 2
    assert page.js_errors == []


def test_countdown(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    toggle = page.get_by_test_id("countdown-toggle")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    expect(toggle).to_contain_text("aus")
    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    expect(toggle).to_contain_text(re.compile(r"3\s+s"))
    reload(page)  # remembered
    expect(booth(page)).to_have_attribute("data-ready", "1", timeout=READY)
    expect(page.get_by_test_id("countdown-toggle")).to_have_attribute("aria-pressed", "true")

    start = time.monotonic()
    page.get_by_test_id("shutter").click()
    countdown = page.get_by_test_id("countdown")
    expect(countdown).to_have_attribute("data-value", "3")
    expect(booth(page)).to_have_attribute("data-counting", "1")
    shot(page, "booth-countdown", 200)
    expect(page.get_by_test_id("result-photo")).to_have_count(0)
    expect(countdown).to_have_attribute("data-value", "1", timeout=4000)
    expect(page.get_by_test_id("result-photo")).to_be_visible(timeout=8000)
    elapsed = time.monotonic() - start
    assert 2.7 < elapsed < 7, elapsed
    expect_uploaded(page)
    assert page.js_errors == []


def test_countdown_can_be_cancelled(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    page.get_by_test_id("countdown-toggle").click()
    page.get_by_test_id("shutter").click()
    countdown = page.get_by_test_id("countdown")
    expect(countdown).to_be_visible()
    countdown.get_by_role("button", name="Abbrechen").click()
    expect(countdown).to_have_count(0)
    page.wait_for_timeout(3500)
    expect(page.get_by_test_id("result-photo")).to_have_count(0)
    assert photos(live, "booth") == []
    # Escape cancels too
    page.get_by_test_id("shutter").click()
    expect(countdown).to_be_visible()
    page.keyboard.press("Escape")
    expect(countdown).to_have_count(0)
    assert page.js_errors == []


def test_save_downloads_the_photo(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    shoot(page)
    with page.expect_download() as info:
        page.get_by_test_id("save").click()
    download = info.value
    assert download.suggested_filename == "fotobox-1.jpg"
    data = Path(download.path()).read_bytes()
    assert Image.open(io.BytesIO(data)).size == (1080, 1440)
    expect(page.get_by_test_id("save")).to_have_text("Heruntergeladen")
    again(page)
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("save")).to_have_text("Herunterladen", timeout=READY)
    assert page.js_errors == []


def test_switch_camera_and_back_to_camera(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    b = booth(page)
    page.get_by_test_id("switch-camera").click()
    expect(b).to_have_attribute("data-facing", "environment")
    expect(b).to_have_attribute("data-mirror", "0")
    expect(b).to_have_attribute("data-ready", "1", timeout=READY)
    select_filter(page, "sepia")
    shoot(page)
    again(page)
    expect(b).to_have_attribute("data-filter", "sepia")
    [(meta, _img)] = stored_images(live, "booth")
    assert meta == {"filter": "sepia", "facing": "environment"}
    assert page.js_errors == []


def test_double_tap_flips_the_camera(guest: Page, live: LiveServer):
    open_booth(guest, live)
    b = booth(guest)
    guest.get_by_test_id("preview").dblclick()
    expect(b).to_have_attribute("data-facing", "environment")
    expect(b).to_have_attribute("data-ready", "1", timeout=READY)
    expect(b).to_have_attribute("data-filter", "normal")  # taps never change the filter
    assert guest.js_errors == []


# ----------------------------------------------------------------- failures


def test_camera_denied(guest: Page, live: LiveServer):
    guest.add_init_script(
        """Object.defineProperty(MediaDevices.prototype, 'getUserMedia', { configurable: true,
        value: () => Promise.reject(new DOMException('Permission denied', 'NotAllowedError')) });"""
    )
    guest.goto(live.url("/x/booth/"))
    screen = guest.get_by_test_id("camera-error")
    expect(screen).to_contain_text("Die Kamera geht nicht", timeout=READY)
    expect(screen).to_contain_text("Kamera-Zugriff wurde verweigert")
    expect(screen).to_contain_text("Probier einen anderen Browser, z.\u00a0B. Safari oder Chrome")
    expect(screen.get_by_role("button", name="Seite neu laden")).to_be_visible()
    expect(guest.get_by_test_id("shutter")).to_be_disabled()
    assert guest.js_errors == []


def rate_limited(route: Route, seconds: int) -> None:
    route.fulfill(
        status=429,
        content_type="application/json",
        headers={"Retry-After": str(seconds)},
        body=json.dumps(
            {"error": "rate_limited", "message": "Langsam! Zu viele Anfragen. Warte kurz."}
        ),
    )


def test_rate_limited_upload_is_sent_after_the_wait(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    calls = {"n": 0}

    def fail_once(route: Route) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            rate_limited(route, 2)
        else:
            route.continue_()

    page.route("**/api/x/booth/upload", fail_once)
    page.get_by_test_id("shutter").click()
    status = page.get_by_test_id("upload-status")
    expect(status).to_have_attribute("data-state", "waiting", timeout=READY)
    expect(page.get_by_test_id("result-text")).to_contain_text("Zu viele Fotos auf einmal")
    expect(page.get_by_test_id("retry")).to_be_disabled()
    shot(page, "booth-rate-limited", 0)
    expect_uploaded(page)
    assert len(stored_images(live, "booth")) == 1
    assert errors_except(page, "429") == []


def test_offline_shot_waits_survives_a_reload_and_is_sent(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    net = Network(page, "booth")
    page.get_by_test_id("shutter").click()
    status = page.get_by_test_id("upload-status")
    expect(status).to_have_attribute("data-state", "waiting", timeout=READY)
    expect(page.get_by_test_id("upload-title")).to_have_text("Noch nicht hochgeladen")
    expect(page.get_by_test_id("result-text")).to_contain_text("Keine Verbindung")
    expect(page.get_by_test_id("result-text")).to_contain_text("sobald es geht")
    expect(page.get_by_test_id("save")).to_be_visible()  # the photo is still theirs to keep
    [kept] = wait_kept(page, 1)
    assert kept["ext"] == "booth" and kept["meta"] == {"filter": "normal", "facing": "user"}
    assert not leaving_is_blocked(page)  # safe on the phone: no browser prompt needed
    shot(page, "booth-result-offline", 300)
    again(page)
    outbox = page.get_by_test_id("outbox")
    expect(outbox).to_have_text("Erneut senden")
    status = page.get_by_test_id("status-slot")
    expect(status).to_have_attribute("data-kind", "waiting")
    expect(status).to_contain_text(re.compile(r"1\s+Foto wartet"))
    shot(page, "booth-outbox", 300)

    # reload while still offline: the photo is still waiting
    reload(page)
    expect(booth(page)).to_have_attribute("data-ready", "1", timeout=READY)
    expect(status).to_contain_text(re.compile(r"1\s+Foto wartet"), timeout=READY)
    expect(outbox).to_be_visible()
    assert stored_images(live, "booth") == []

    # back online: the browser says so, the outbox sends it on its own
    net.offline = False
    page.evaluate("() => window.dispatchEvent(new Event('online'))")
    expect(
        page.get_by_role("region").get_by_text(re.compile("von vorhin ist jetzt hochgeladen"))
    ).to_be_visible(timeout=READY)
    # the toast stands above the filter strip and the controls: the next shot needs no wait
    shutter = page.get_by_test_id("shutter")
    assert covered_by_toast(page, page.get_by_test_id("filter-strip"), shutter) == []
    shutter.tap(trial=True, timeout=QUICK_TAP_MS)
    expect(outbox).to_have_count(0)
    expect(status).to_have_count(0)
    [(meta, img)] = stored_images(live, "booth")
    assert meta == {"filter": "normal", "facing": "user"} and img.size == (1080, 1440)
    wait_kept(page, 0)
    assert network_errors_only(page) == []


def test_erneut_senden_from_the_outbox_line(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    net = Network(page, "booth")
    for fid in ("normal", "bw"):
        select_filter(page, fid)
        page.get_by_test_id("shutter").click()
        expect(page.get_by_test_id("upload-status")).to_have_attribute(
            "data-state", "waiting", timeout=READY
        )
        again(page)
    outbox = page.get_by_test_id("outbox")
    expect(page.get_by_test_id("status-slot")).to_contain_text(re.compile(r"2\s+Fotos warten"))
    wait_kept(page, 2)
    net.offline = False
    outbox.click()
    expect(outbox).to_have_count(0, timeout=READY)
    wait_for_photos(live, "booth", 2)
    assert sorted(meta["filter"] for meta, _ in stored_images(live, "booth")) == ["bw", "normal"]
    wait_kept(page, 0)
    # nothing unsent: straight home
    page.get_by_test_id("back").click()
    page.wait_for_url(live.url("/"))
    assert network_errors_only(page) == []


NO_INDEXEDDB = (
    "Object.defineProperty(window, 'indexedDB', { configurable: true, get: () => undefined });"
)


def test_without_storage_leaving_warns(guest: Page, live: LiveServer):
    page = guest
    page.add_init_script(NO_INDEXEDDB)
    open_booth(page, live)
    net = Network(page, "booth")
    assert not leaving_is_blocked(page)
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("upload-status")).to_have_attribute(
        "data-state", "waiting", timeout=READY
    )
    assert leaving_is_blocked(page)  # only in memory: a closed tab would lose it
    expect(page.get_by_test_id("result-text")).to_contain_text("Lass die Seite offen")
    again(page)
    assert leaving_is_blocked(page)
    net.offline = False
    page.get_by_test_id("outbox").click()
    expect(page.get_by_test_id("outbox")).to_have_count(0, timeout=READY)
    assert not leaving_is_blocked(page)
    assert len(stored_images(live, "booth")) == 1
    assert network_errors_only(page) == []


def test_reload_mid_upload_loses_nothing(guest: Page, live: LiveServer):
    """Stored before the first upload: a reload during the upload keeps the photo."""
    page = guest
    open_booth(page, live)
    page.route("**/api/x/booth/upload", lambda route: None)  # never answers
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("upload-status")).to_have_attribute("data-state", "uploading")
    expect(page.get_by_test_id("upload-title")).to_have_text("Wird hochgeladen…")
    wait_kept(page, 1)
    assert not leaving_is_blocked(page)
    page.unroute("**/api/x/booth/upload")
    reload(page)
    wait_for_photos(live, "booth", 1)
    wait_kept(page, 0)


def test_boot_failure_offers_a_reload(guest: Page, live: LiveServer):
    page = guest
    page.route("**/api/identify", lambda route: route.abort())
    page.goto(live.url("/x/booth/"))
    screen = page.get_by_test_id("fatal")
    expect(screen).to_contain_text(re.compile("Keine (Antwort|Verbindung)"), timeout=READY)
    expect(page.get_by_text("Kamera startet")).to_have_count(0)
    page.unroute("**/api/identify")
    screen.get_by_role("button", name="Seite neu laden").click()
    expect(booth(page)).to_have_attribute("data-ready", "1", timeout=READY)


def test_filter_catalogue_failure_offers_a_reload(guest: Page, live: LiveServer):
    page = guest
    page.route("**/api/x/booth/filters", lambda route: route.abort())
    page.goto(live.url("/x/booth/"))
    screen = page.get_by_test_id("fatal")
    expect(screen.get_by_role("button", name="Seite neu laden")).to_be_visible(timeout=READY)


def test_banned_guest_sees_no_camera(guest: Page, live: LiveServer, admin: Admin):
    page = guest
    admin.ban(admin.user_id())
    page.goto(live.url("/x/booth/"))
    screen = page.get_by_test_id("banned")
    expect(screen).to_contain_text("Gesperrt")
    expect(page.get_by_test_id("shutter")).to_have_count(0)
    expect(screen.get_by_role("button", name="Seite neu laden")).to_be_visible()  # GP's gate
    assert page.js_errors == []


def test_paused_and_stopped_lock_the_shutter(guest: Page, live: LiveServer, admin: Admin):
    page = guest
    uploads: list[str] = []
    page.on("request", lambda r: uploads.append(r.url) if r.url.endswith("/upload") else None)
    for lock, kind in (
        (lambda on: admin.pause(admin.user_id(), on), "paused"),
        (admin.stop, "stopped"),
    ):
        lock(True)
        open_booth(page, live)
        shutter = page.get_by_test_id("shutter")
        expect(shutter).to_have_attribute("data-state", "blocked")
        expect(page.get_by_test_id("status-slot")).to_have_attribute("data-kind", kind)
        if kind == "paused":
            shot(page, "booth-blocked", 0)
        shutter.click()  # the reason, not a photo
        expect(page.get_by_test_id("status-info")).to_be_visible()
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        assert uploads == []
        lock(False)
    open_booth(page, live)
    expect(page.get_by_test_id("shutter")).to_have_attribute("data-state", "ready")
    assert page.js_errors == []


def test_survives_webgl_context_loss(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live)
    select_filter(page, "party")
    was_lost = page.get_by_test_id("preview-canvas").evaluate(
        """async (canvas) => {
        const gl = canvas.getContext('webgl');
        const ext = gl.getExtension('WEBGL_lose_context');
        ext.loseContext();
        await new Promise((resolve) => setTimeout(resolve, 250));
        const lost = gl.isContextLost();
        ext.restoreContext();
        return lost;
    }"""
    )
    assert was_lost
    page.wait_for_timeout(400)
    shoot(page)
    [(meta, img)] = stored_images(live, "booth")
    assert meta["filter"] == "party"
    assert warm_bottom(img)  # the frame overlay came back too
    assert page.js_errors == []


def test_canvas2d_fallback(guest: Page, live: LiveServer):
    page = guest
    open_booth(page, live, "?renderer=canvas2d")
    expect(booth(page)).to_have_attribute("data-renderer", "canvas2d")
    ids = strip_ids(page)
    assert ids == [
        "normal",
        "bw",
        "sepia",
        "colorpop",
        "party",
        "emoji",
        "neon",
        "thermal",
    ]  # no GPU-only filters
    select_filter(page, "bw")
    shoot(page)
    again(page)
    select_filter(page, "party")
    shoot(page)
    (meta_bw, bw), (meta_party, party) = stored_images(live, "booth")
    assert meta_bw["filter"] == "bw" and gray_error(bw) < 4
    assert meta_party["filter"] == "party"
    assert bw.size == party.size == (1080, 1440)
    assert warm_bottom(party)
    assert page.js_errors == []


# ----------------------------------------------------------------- layouts


def inside(page: Page, testid: str) -> dict:
    box = settled_box(page.get_by_test_id(testid).first)
    size = page.viewport_size
    assert box and size, testid
    assert box["x"] >= -1 and box["y"] >= -1, (testid, box)
    assert box["x"] + box["width"] <= size["width"] + 1, (testid, box, size)
    assert box["y"] + box["height"] <= size["height"] + 1, (testid, box, size)
    return box


SIZES = {(390, 844): "phone", (360, 640): "small", (320, 640): "tiny", (844, 390): "landscape"}


@pytest.mark.parametrize("size", list(SIZES), ids=list(SIZES.values()))
def test_everything_fits(guest: Page, live: LiveServer, size: tuple[int, int]):
    page = guest
    page.set_viewport_size({"width": size[0], "height": size[1]})
    open_booth(page, live)
    name = SIZES[size]
    # the default look: the party style (googly-eyed shutter with its ring of lights)
    expect(page.locator("html")).to_have_attribute("data-vb-style", "party")
    for testid in (
        "shutter",
        "countdown-toggle",
        "switch-camera",
        "back",
        "guest-pass",
        "preview",
        "filter-strip",
        "filter-name",
    ):
        inside(page, testid)
    if size == (390, 844):
        assert page.get_by_test_id("preview").bounding_box()["width"] >= 389  # type: ignore[index]
    sizes = page.evaluate(
        "() => [document.documentElement.scrollWidth, innerWidth, document.documentElement.scrollHeight, innerHeight]"
    )
    assert sizes[0] <= sizes[1] + 1 and sizes[2] <= sizes[3] + 1, sizes
    expect(page.get_by_test_id("filter-bw").locator("img")).to_be_visible(timeout=READY)
    shot(page, f"booth-camera-{name}", 200)
    shoot(page)
    for testid in ("save", "again", "upload-status", "result-photo"):
        inside(page, testid)
    photo = page.get_by_test_id("result-photo").bounding_box()
    assert photo and photo["height"] > 250, photo
    shot(page, f"booth-result-{name}", 900)
    assert page.js_errors == []


# Chrome on Android offers the share sheet for files (the headless browser does not)
WEB_SHARE = """(() => {
  Object.defineProperty(Navigator.prototype, 'canShare', {configurable: true, value: () => true});
  Object.defineProperty(Navigator.prototype, 'share', {configurable: true, value: async () => undefined});
})();"""


@pytest.mark.parametrize("width", [320, 360, 390])
@pytest.mark.parametrize("activity", ["booth", "beer"])
def test_result_buttons_stay_on_screen_with_share(
    guest: Page, live: LiveServer, activity: str, width: int
):
    """The Fotobox result's „Herunterladen“, Teilen and „Neues Foto“ on a narrow Android
    phone: they wrap onto a second line instead of running off the right edge (they did
    at 390 px with the share button, at 320 px without it). The Beer Cam's one button
    („Noch ein Bier“) shares the layout."""
    page = guest
    page.context.add_init_script(WEB_SHARE)
    page.set_viewport_size({"width": width, "height": 780})
    (open_booth if activity == "booth" else open_beer)(page, live)
    shoot(page)
    for testid in ("save", "share", "again") if activity == "booth" else ("again",):
        inside(page, testid)
    sizes = page.evaluate("() => [document.documentElement.scrollWidth, innerWidth]")
    assert sizes[0] <= sizes[1] + 1, sizes
    shot(page, f"{activity}-result-share-{width}", 600)
    assert page.js_errors == []
