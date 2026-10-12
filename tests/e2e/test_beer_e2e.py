"""Beer Cam in a real browser: fake camera → outline → shutter → upload.

Set VB_SCREENSHOT_DIR=/some/dir to also save phone-size screenshots.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import Page, expect

from virtubooth.extension import discover_extensions
from virtubooth.repo import PhotoQuery

from .conftest import BROWSER_NAME, MOBILE, accept_consent_in_browser

pytestmark = pytest.mark.e2e

CAMERA_TIMEOUT = 15000


def shot(page: Page, name: str, settle_ms: int = 700) -> None:
    out = os.environ.get("VB_SCREENSHOT_DIR")
    if not out:
        return
    page.wait_for_timeout(settle_ms)  # let transitions/confetti settle for the picture
    Path(out).mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(Path(out) / f"{name}.png"))


@pytest.fixture
def e2e_extensions():
    return discover_extensions(["beer"])


def open_beer(page: Page, live) -> None:
    page.goto(live.url("/x/beer/"))
    expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=CAMERA_TIMEOUT)


def expect_success(page: Page, number: int) -> None:
    expect(page.get_by_test_id("success")).to_be_visible(timeout=CAMERA_TIMEOUT)
    expect(page.get_by_test_id("success-title")).to_have_text(f"Bier #{number} geloggt 🍺")


def beer_photos(live):
    return live.core.repo.list_photos(PhotoQuery(extension="beer", order="asc"))


def stored_size(live, photo) -> tuple[int, int]:
    data = live.core.repo.photo_path("beer", photo.filename).read_bytes()
    return Image.open(io.BytesIO(data)).size


def test_bottle_then_cup_upload_flow(guest_page, live):
    page = guest_page
    open_beer(page, live)

    # default: bottle outline
    expect(page.get_by_test_id("overlay")).to_have_attribute("data-vessel", "bottle")
    expect(page.get_by_test_id("overlay-bottle")).to_be_visible()
    expect(page.get_by_test_id("overlay-cup")).to_be_hidden()
    expect(page.get_by_test_id("vessel-bottle")).to_have_attribute("aria-checked", "true")
    expect(page.get_by_test_id("hint")).to_have_text("Halte deine Flasche genau in den Umriss")
    expect(page.get_by_test_id("counter")).to_contain_text("0")
    expect(page.get_by_test_id("counter")).to_contain_text("1.000.000")
    expect(page.get_by_test_id("user-chip")).to_be_visible()
    shot(page, "camera-bottle")

    # toggle to the cup
    page.get_by_test_id("vessel-cup").click()
    expect(page.get_by_test_id("overlay")).to_have_attribute("data-vessel", "cup")
    expect(page.get_by_test_id("overlay-cup")).to_be_visible()
    expect(page.get_by_test_id("overlay-bottle")).to_be_hidden()
    expect(page.get_by_test_id("vessel-cup")).to_have_attribute("aria-checked", "true")
    expect(page.get_by_test_id("hint")).to_contain_text("Becher")
    shot(page, "camera-cup")

    # first beer
    page.get_by_test_id("shutter").click()
    expect_success(page, 1)
    expect(page.get_by_test_id("success-count")).to_contain_text("1")
    expect(page.get_by_test_id("counter")).to_contain_text("1")
    shot(page, "success", settle_ms=900)

    photos = beer_photos(live)
    assert len(photos) == 1
    assert (photos[0].width, photos[0].height) == (1080, 1440)
    assert stored_size(live, photos[0]) == (1080, 1440)
    assert photos[0].meta == {"vessel": "cup", "facing": "environment"}

    # second beer
    page.get_by_test_id("again").click()
    expect(page.get_by_test_id("success")).to_be_hidden()
    expect(page.get_by_test_id("shutter")).to_be_enabled()
    expect(page.get_by_test_id("still")).to_have_count(0)
    page.get_by_test_id("shutter").click()
    expect_success(page, 2)
    assert len(beer_photos(live)) == 2
    assert page.js_errors == []


def test_preview_box_is_the_capture_region(guest_page, live):
    """The video and the outline cover exactly the same 3:4 box, centred on screen."""
    page = guest_page
    open_beer(page, live)
    frame = page.get_by_test_id("frame").bounding_box()
    video = page.locator("#video").bounding_box()
    overlay = page.get_by_test_id("overlay").bounding_box()
    assert frame and video and overlay
    assert frame["width"] / frame["height"] == pytest.approx(3 / 4, abs=0.01)
    for box in (video, overlay):
        for key in ("x", "y", "width", "height"):
            assert box[key] == pytest.approx(frame[key], abs=1)
    viewport = MOBILE["viewport"]
    assert frame["x"] + frame["width"] / 2 == pytest.approx(viewport["width"] / 2, abs=1)
    assert frame["width"] >= viewport["width"] - 24  # uses (almost) the full width on a phone
    assert page.locator("#video").evaluate("v => getComputedStyle(v).objectFit") == "cover"
    # the outline fills most of the frame height
    bottle = page.locator(".beer-guide--bottle .beer-guide-line").bounding_box()
    assert bottle and bottle["height"] > 0.8 * frame["height"]
    page.get_by_test_id("vessel-cup").click()
    cup = page.locator(".beer-guide--cup .beer-guide-line").bounding_box()
    assert cup and cup["height"] > 0.7 * frame["height"]
    for shape in (bottle, cup):  # both centred
        assert shape["x"] + shape["width"] / 2 == pytest.approx(frame["x"] + frame["width"] / 2, abs=2)
    assert page.js_errors == []


def test_vessel_choice_is_remembered(guest_page, live):
    page = guest_page
    open_beer(page, live)
    page.get_by_test_id("vessel-cup").click()
    page.reload()
    expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=CAMERA_TIMEOUT)
    expect(page.get_by_test_id("overlay")).to_have_attribute("data-vessel", "cup")
    page.get_by_test_id("vessel-bottle").click()
    page.reload()
    expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=CAMERA_TIMEOUT)
    expect(page.get_by_test_id("overlay")).to_have_attribute("data-vessel", "bottle")
    assert page.js_errors == []


def test_switch_camera_mirrors_and_records_facing(guest_page, live):
    page = guest_page
    open_beer(page, live)
    video = page.locator("#video")
    expect(video).not_to_have_class("is-mirrored")
    page.get_by_test_id("switch-camera").click()
    expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=CAMERA_TIMEOUT)
    expect(video).to_have_class("is-mirrored")
    page.get_by_test_id("shutter").click()
    expect_success(page, 1)
    assert beer_photos(live)[0].meta == {"vessel": "bottle", "facing": "user"}
    assert page.js_errors == []


def test_upload_error_then_retry_same_blob(guest_page, live):
    page = guest_page
    open_beer(page, live)
    sizes: list[int] = []
    failed = {"done": False}

    def handler(route):
        sizes.append(len(route.request.post_data_buffer or b""))
        if not failed["done"]:
            failed["done"] = True
            route.fulfill(
                status=429,
                content_type="application/json",
                body=json.dumps({"error": "rate_limited", "message": "Langsam! Zu viele Anfragen."}),
            )
        else:
            route.continue_()

    page.route("**/api/x/beer/upload", handler)
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("upload")).to_contain_text("Langsam! Zu viele Anfragen.")
    expect(page.get_by_role("alert").filter(has_text="Langsam!")).to_be_visible()  # the toast
    expect(page.get_by_test_id("shutter")).to_be_disabled()
    expect(page.get_by_test_id("still")).to_have_count(1)
    shot(page, "upload-error")
    assert beer_photos(live) == []

    page.get_by_test_id("retry").click()
    expect_success(page, 1)
    assert len(sizes) == 2
    if BROWSER_NAME == "chromium":  # WebKit doesn't expose Blob request bodies to routes
        assert sizes[0] == sizes[1] > 10_000  # the very same JPEG again
    assert len(beer_photos(live)) == 1
    # the 429 shows up as a console error ("Failed to load resource"); nothing else may
    assert [e for e in page.js_errors if "429" not in e] == []


def test_discard_after_error_returns_to_camera(guest_page, live):
    page = guest_page
    open_beer(page, live)
    page.route("**/api/x/beer/upload", lambda route: route.abort())
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("upload")).to_contain_text("Keine Verbindung")
    page.get_by_test_id("discard").click()
    expect(page.get_by_test_id("upload")).to_be_hidden()
    expect(page.get_by_test_id("still")).to_have_count(0)
    expect(page.get_by_test_id("shutter")).to_be_enabled()


def test_camera_denied_shows_notice(guest_page, live):
    page = guest_page
    page.add_init_script(
        """Object.defineProperty(MediaDevices.prototype, 'getUserMedia', {
             configurable: true,
             value: () => Promise.reject(new DOMException('denied', 'NotAllowedError')),
           });"""
    )
    page.goto(live.url("/x/beer/"))
    notice = page.locator(".vb-notice")
    expect(notice).to_be_visible(timeout=CAMERA_TIMEOUT)
    expect(notice).to_contain_text("Kamera geht nicht")
    expect(notice).to_contain_text("Kamera-Zugriff wurde verweigert")
    expect(notice.get_by_role("button", name="Neu laden")).to_be_visible()
    expect(page.get_by_test_id("shutter")).to_be_disabled()
    shot(page, "camera-denied")


def test_banned_guest_sees_notice_and_no_camera(guest_page, live):
    page = guest_page
    user = live.core.repo.list_users()[0]
    live.core.repo.ban_user(user.id, "test", "admin:test")
    page.goto(live.url("/x/beer/"))
    expect(page.locator(".vb-notice")).to_contain_text("Gesperrt")
    expect(page.get_by_test_id("shutter")).to_be_disabled()
    assert page.locator("#video").evaluate("v => v.srcObject === null")


def test_in_app_browser_hint(browser, live):
    ctx = browser.new_context(
        **(MOBILE | {"user_agent": MOBILE["user_agent"] + " Instagram 300.0.0.0"}),
        permissions=["camera"],
    )
    try:
        page = ctx.new_page()
        page.goto(live.entry("/x/beer/"))
        accept_consent_in_browser(page)
        hint = page.get_by_test_id("inapp-hint")
        expect(hint).to_be_visible()
        expect(hint).to_contain_text("Safari oder Chrome")
        hint.get_by_role("button").click()
        expect(hint).to_be_hidden()
        page.reload()
        expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=CAMERA_TIMEOUT)
        expect(hint).to_be_hidden()  # dismissed for good
    finally:
        ctx.close()


def add_beers(live, n: int) -> None:
    """Beers from other guests, straight into the DB."""
    user = live.core.repo.list_users()[0]
    for _ in range(n):
        name = os.urandom(4).hex()
        live.core.repo.insert_photo(
            extension="beer", user_id=user.id, filename=f"{name}.jpg", thumb_filename=f"thumbs/{name}.jpg",
            width=1080, height=1440, size=1, meta={"vessel": "bottle"},
        )


def test_counter_shows_running_total(guest_page, live):
    add_beers(live, 3)
    page = guest_page
    open_beer(page, live)
    counter = page.locator("#count")
    expect(counter).to_have_text("3")
    page.get_by_test_id("shutter").click()
    expect_success(page, 4)
    expect(page.get_by_test_id("success-count")).to_contain_text("4")
    expect(page.get_by_test_id("success-togo")).to_have_text("Noch 999.996 bis zur Million – weiter so!")
    expect(counter).to_have_text("4")
    # meanwhile others keep drinking; "Noch eins!" fetches the fresh total
    add_beers(live, 1000)
    page.get_by_test_id("again").click()
    expect(counter).to_have_text("1.004")
    assert page.js_errors == []
