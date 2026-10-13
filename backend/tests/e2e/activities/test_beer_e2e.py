"""Beer Cam in a real browser: fake camera → outline → shutter → upload → print.

Ported from e2e_legacy/test_beer_e2e.py to the new UI (same behaviours, new
selectors). New in the overhaul: the shutter is locked up front while uploads are
paused or stopped, and a beer that can't be sent waits in the outbox.
"""

from __future__ import annotations

import json
import re

import pytest
from playwright.sync_api import Page, Route, expect

from ..conftest import BROWSER_NAME, MOBILE, LiveServer
from .conftest import (
    READY,
    Admin,
    add_beers,
    again,
    errors_except,
    expect_uploaded,
    leaving_is_blocked,
    media_size,
    network_errors_only,
    open_beer,
    photos,
    reload,
    shot,
    stored_images,
    wait_kept,
)

pytestmark = pytest.mark.e2e


def vessel(page: Page, which: str):  # type: ignore[no-untyped-def]
    return page.get_by_test_id("vessel").locator(f"[data-value={which}]")


def expect_counted(page: Page, number: int) -> None:
    expect(page.get_by_test_id("success-title")).to_have_text(
        f"Bier Nr. {number} gezählt", timeout=READY
    )


def test_bottle_then_cup_upload_flow(guest: Page, live: LiveServer):
    page = guest
    open_beer(page, live)

    # default: the bottle outline
    expect(page.get_by_test_id("overlay")).to_have_attribute("data-vessel", "bottle")
    expect(page.get_by_test_id("overlay-bottle")).to_be_visible()
    expect(page.get_by_test_id("overlay-cup")).to_have_count(0)
    expect(vessel(page, "bottle").locator("input")).to_be_checked()
    expect(page.get_by_test_id("hint")).to_have_text("Halte die Flasche in den Umriss.")
    counter = page.get_by_test_id("counter")
    expect(counter).to_have_attribute("data-total", "0")
    expect(counter).to_contain_text("0001")  # the next beer
    expect(counter).to_contain_text(re.compile(r"Ziel 1\s+Mio\."))
    expect(page.get_by_test_id("guest-pass")).to_be_visible()
    shot(page, "beer-camera-bottle")

    # the cup
    vessel(page, "cup").click()
    expect(page.get_by_test_id("overlay")).to_have_attribute("data-vessel", "cup")
    expect(page.get_by_test_id("overlay-cup")).to_be_visible()
    expect(page.get_by_test_id("overlay-bottle")).to_have_count(0)
    expect(vessel(page, "cup").locator("input")).to_be_checked()
    expect(page.get_by_test_id("hint")).to_have_text("Halte den Becher in den Umriss.")

    # first beer: the print, the board number, the counter
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("result-photo")).to_be_visible(timeout=READY)
    expect_uploaded(page)
    expect_counted(page, 1)
    expect(page.get_by_test_id("result-text")).to_contain_text(
        re.compile(r"Noch 999\.999 bis zur Million\.")
    )
    expect(page.get_by_test_id("upload-status")).to_contain_text("0001")
    expect(page.get_by_test_id("upload-status")).to_contain_text("Gezählt")
    shot(page, "beer-result", 900)

    [photo] = photos(live, "beer")
    assert (photo.width, photo.height) == (1080, 1440)
    [(meta, img)] = stored_images(live, "beer")
    assert img.size == (1080, 1440)
    assert meta == {"vessel": "cup", "facing": "environment"}
    assert media_size(page, photo.url) == (1080, 1440)

    # "Deine Bilder" (GP's screen) gets it from GET /api/me/photos
    mine = page.evaluate(
        "async () => (await (await fetch('/api/me/photos')).json()).photos.map((p) => p.id)"
    )
    assert mine == [photo.public_id]

    # "Noch ein Bier"
    again(page)
    expect(page.get_by_test_id("overlay")).to_have_attribute("data-vessel", "cup")
    expect(counter).to_have_attribute("data-total", "1")
    page.get_by_test_id("shutter").click()
    expect_counted(page, 2)
    assert len(photos(live, "beer")) == 2
    assert page.js_errors == []


def test_preview_box_is_the_capture_region(guest: Page, live: LiveServer):
    """The preview canvas and the outline cover exactly the same 3:4 box, centred."""
    page = guest
    open_beer(page, live)
    frame = page.get_by_test_id("frame").bounding_box()
    canvas = page.get_by_test_id("preview-canvas").bounding_box()
    overlay = page.get_by_test_id("overlay").bounding_box()
    assert frame and canvas and overlay
    assert frame["width"] / frame["height"] == pytest.approx(3 / 4, abs=0.01)
    for box in (canvas, overlay):
        for key in ("x", "y", "width", "height"):
            assert box[key] == pytest.approx(frame[key], abs=1)
    viewport = MOBILE["viewport"]
    assert frame["x"] + frame["width"] / 2 == pytest.approx(viewport["width"] / 2, abs=1)
    assert frame["width"] >= viewport["width"] - 1  # edge to edge on a phone
    # the canvas draws the picture at the photo's 3:4: its backing store is 3:4 too
    w, h = page.get_by_test_id("preview-canvas").evaluate("c => [c.width, c.height]")
    assert w / h == pytest.approx(0.75, abs=0.005)
    # the outline fills most of the frame height
    bottle = page.get_by_test_id("outline-line").bounding_box()
    assert bottle and bottle["height"] > 0.8 * frame["height"]
    vessel(page, "cup").click()
    expect(page.get_by_test_id("overlay")).to_have_attribute("data-vessel", "cup")
    cup = page.get_by_test_id("outline-line").bounding_box()
    assert cup and cup["height"] > 0.7 * frame["height"]
    for shape in (bottle, cup):  # both centred
        assert shape["x"] + shape["width"] / 2 == pytest.approx(
            frame["x"] + frame["width"] / 2, abs=2
        )
    assert page.js_errors == []


def test_vessel_choice_is_remembered(guest: Page, live: LiveServer):
    page = guest
    open_beer(page, live)
    vessel(page, "cup").click()
    reload(page)
    expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=READY)
    expect(page.get_by_test_id("overlay")).to_have_attribute("data-vessel", "cup")
    vessel(page, "bottle").click()
    reload(page)
    expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=READY)
    expect(page.get_by_test_id("overlay")).to_have_attribute("data-vessel", "bottle")
    assert page.js_errors == []


def test_switch_camera_mirrors_and_records_facing(guest: Page, live: LiveServer):
    page = guest
    open_beer(page, live)
    app = page.get_by_test_id("beer-app")
    expect(app).to_have_attribute("data-facing", "environment")
    expect(app).to_have_attribute("data-mirror", "0")
    page.get_by_test_id("switch-camera").click()
    expect(app).to_have_attribute("data-facing", "user")
    expect(app).to_have_attribute("data-mirror", "1")
    expect(app).to_have_attribute("data-ready", "1", timeout=READY)
    page.get_by_test_id("shutter").click()
    expect_counted(page, 1)
    [(meta, _img)] = stored_images(live, "beer")
    assert meta == {"vessel": "bottle", "facing": "user"}
    assert page.js_errors == []


def rate_limited(route: Route, seconds: int | None = None) -> None:
    body = {"error": "rate_limited", "message": "Langsam! Zu viele Anfragen. Warte kurz."}
    headers = {"Retry-After": str(seconds)} if seconds is not None else {}
    route.fulfill(
        status=429, content_type="application/json", headers=headers, body=json.dumps(body)
    )


def test_rate_limit_waits_then_sends_by_itself(guest: Page, live: LiveServer):
    page = guest
    open_beer(page, live)
    sizes: list[int] = []

    def handler(route: Route) -> None:
        sizes.append(len(route.request.post_data_buffer or b""))
        if len(sizes) == 1:
            rate_limited(route, 2)
        else:
            route.continue_()

    page.route("**/api/x/beer/upload", handler)
    page.get_by_test_id("shutter").click()
    status = page.get_by_test_id("upload-status")
    expect(status).to_have_attribute("data-state", "waiting", timeout=READY)
    # how long to wait, from the server's Retry-After, in one place (no toast on top)
    expect(page.get_by_test_id("result-text")).to_contain_text(
        re.compile(r"Langsam! Zu viele Fotos auf einmal\. In [12]\s+s nochmal\.")
    )
    retry = page.get_by_test_id("retry")
    expect(retry).to_be_disabled()
    expect(retry).to_contain_text(re.compile(r"Erneut senden in [12]\s+s"))
    shot(page, "beer-rate-limited", 0)
    assert photos(live, "beer") == []
    # the outbox sends it as soon as the server allows: nobody has to tap
    expect_counted(page, 1)
    assert len(sizes) == 2
    if BROWSER_NAME == "chromium":  # other browsers don't expose Blob bodies to routes
        assert sizes[0] == sizes[1] > 10_000  # the very same JPEG again
    assert len(photos(live, "beer")) == 1
    assert errors_except(page, "429") == []


def test_failed_upload_retried_by_hand(guest: Page, live: LiveServer):
    page = guest
    open_beer(page, live)
    sizes: list[int] = []

    def handler(route: Route) -> None:
        sizes.append(len(route.request.post_data_buffer or b""))
        if len(sizes) == 1:
            route.abort("internetdisconnected")
        else:
            route.continue_()

    page.route("**/api/x/beer/upload", handler)
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("upload-status")).to_have_attribute(
        "data-state", "waiting", timeout=READY
    )
    expect(page.get_by_test_id("result-text")).to_contain_text("Keine Verbindung")
    retry = page.get_by_test_id("retry")
    expect(retry).to_have_text("Erneut senden")
    retry.click()
    expect_counted(page, 1)
    if BROWSER_NAME == "chromium":
        assert sizes[0] == sizes[1] > 10_000
    assert len(photos(live, "beer")) == 1
    assert network_errors_only(page) == []


def test_rate_limit_without_a_wait_time(guest: Page, live: LiveServer):
    page = guest
    open_beer(page, live)
    page.route("**/api/x/beer/upload", lambda route: rate_limited(route))
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("result-text")).to_contain_text(
        "Versuch es gleich nochmal", timeout=READY
    )
    expect(page.get_by_test_id("retry")).to_be_enabled()
    assert errors_except(page, "429") == []


def test_real_rate_limit_from_the_server(guest: Page, live: LiveServer):
    """The server's own upload budget (10 per minute per guest): the 11th waits."""
    page = guest
    open_beer(page, live)
    page.evaluate(
        """async () => {
        const c = document.createElement('canvas'); c.width = 1080; c.height = 1440;
        c.getContext('2d').fillRect(0, 0, 1080, 1440);
        const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.6));
        for (let i = 0; i < 10; i++) {
          await fetch('/api/x/beer/upload', { method: 'POST', body: blob, headers: {
            'Content-Type': 'image/jpeg', 'X-VB-Meta': encodeURIComponent(JSON.stringify({ vessel: 'bottle' })) } });
        }
    }"""
    )
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("upload-status")).to_have_attribute(
        "data-state", "waiting", timeout=READY
    )
    expect(page.get_by_test_id("result-text")).to_contain_text("Zu viele Fotos auf einmal")
    expect(page.get_by_test_id("retry")).to_be_disabled()
    assert len(wait_kept(page, 1)) == 1  # waits on the phone, nothing lost
    assert errors_except(page, "429") == []


def test_paused_guest_cannot_shoot_but_is_told_why(guest: Page, live: LiveServer, admin: Admin):
    page = guest
    admin.pause(admin.user_id())
    uploads: list[str] = []
    page.on("request", lambda r: uploads.append(r.url) if r.url.endswith("/upload") else None)
    page.goto(live.url("/x/beer/"))
    expect(page.get_by_test_id("beer-app")).to_have_attribute("data-ready", "1", timeout=READY)
    shutter = page.get_by_test_id("shutter")
    expect(shutter).to_have_attribute("data-state", "blocked")
    status = page.get_by_test_id("status-slot")
    expect(status).to_have_attribute("data-kind", "paused")
    expect(status).to_contain_text("Hochladen pausiert")
    expect(page.get_by_test_id("hint")).to_have_count(0)
    shot(page, "beer-blocked-paused")
    shutter.click()  # explains instead of shooting and throwing the beer away
    why = page.get_by_test_id("status-info")
    expect(why).to_be_visible()
    expect(why).to_contain_text("pausiert")
    shot(page, "beer-blocked-why", 400)
    why.get_by_role("button", name="Alles klar").click()
    expect(why).to_have_count(0)
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("Space")  # opens the explanation again, never a photo
    expect(why).to_be_visible()
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert uploads == []
    expect(page.get_by_test_id("result-photo")).to_have_count(0)

    admin.pause(admin.user_id(), paused=False)
    reload(page)
    expect(page.get_by_test_id("shutter")).to_have_attribute("data-state", "ready", timeout=READY)
    page.get_by_test_id("shutter").click()
    expect_counted(page, 1)
    assert page.js_errors == []


def test_stopped_uploads_lock_the_shutter(guest: Page, live: LiveServer, admin: Admin):
    page = guest
    admin.stop()
    page.goto(live.url("/x/beer/"))
    expect(page.get_by_test_id("beer-app")).to_have_attribute("data-ready", "1", timeout=READY)
    expect(page.get_by_test_id("shutter")).to_have_attribute("data-state", "blocked")
    expect(page.get_by_test_id("status-slot")).to_have_attribute("data-kind", "stopped")
    expect(page.get_by_test_id("status-slot")).to_contain_text("kurz angehalten")
    admin.stop(enabled=False)
    reload(page)
    expect(page.get_by_test_id("shutter")).to_have_attribute("data-state", "ready", timeout=READY)
    assert page.js_errors == []


def test_paused_between_check_and_upload_keeps_the_beer(
    guest: Page, live: LiveServer, admin: Admin
):
    """The pause arrives while the guest is already shooting: the beer waits."""
    page = guest
    open_beer(page, live)
    admin.pause(admin.user_id())  # the page doesn't know yet
    page.get_by_test_id("shutter").click()
    status = page.get_by_test_id("upload-status")
    expect(status).to_have_attribute("data-state", "held", timeout=READY)
    expect(page.get_by_test_id("result-text")).to_contain_text("Dein Bier wartet")
    expect(page.get_by_test_id("result-text")).to_contain_text("sobald du wieder hochladen kannst")
    expect(page.get_by_test_id("retry")).to_have_count(0)  # no retry that can't work
    assert [k["ext"] for k in wait_kept(page, 1)] == ["beer"]
    assert not leaving_is_blocked(page)  # it is safe on the phone
    shot(page, "beer-held", 300)
    page.get_by_test_id("again").click()
    expect(page.get_by_test_id("shutter")).to_have_attribute(
        "data-state", "blocked"
    )  # now it knows
    expect(page.get_by_test_id("status-slot")).to_have_attribute("data-kind", "paused")

    # the host frees the guest: the next visit sends the waiting beer
    admin.pause(admin.user_id(), paused=False)
    reload(page)
    expect(
        page.get_by_role("region").get_by_text("Dein Bier von vorhin ist jetzt gezählt.")
    ).to_be_visible(timeout=READY)
    wait_kept(page, 0)
    assert len(photos(live, "beer")) == 1
    assert errors_except(page, "403") == []


def test_banned_guest_sees_a_screen_and_no_camera(guest: Page, live: LiveServer, admin: Admin):
    page = guest
    admin.ban(admin.user_id())
    page.add_init_script(
        "window.__gum = 0; const g = MediaDevices.prototype.getUserMedia;"
        "MediaDevices.prototype.getUserMedia = function (c) { window.__gum++; return g.call(this, c); };"
    )
    page.goto(live.url("/x/beer/"))
    screen = page.get_by_test_id("banned")
    expect(screen).to_contain_text("Gesperrt")
    expect(page.get_by_test_id("shutter")).to_have_count(0)
    assert page.evaluate("() => window.__gum") == 0  # the camera never opened
    shot(page, "beer-banned")
    expect(screen.get_by_role("button", name="Seite neu laden")).to_be_visible()  # GP's gate
    # Start ("/", where the guest joined) asks for "Deine Bilder" only while not banned
    assert page.js_errors == []


def test_banned_while_on_the_page(guest: Page, live: LiveServer, admin: Admin):
    page = guest
    open_beer(page, live)
    admin.ban(admin.user_id())
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("banned")).to_contain_text("Gesperrt", timeout=READY)
    expect(page.get_by_test_id("shutter")).to_have_count(0)
    # the beer stays on the phone, in case the hosts lift the ban
    assert len(wait_kept(page, 1)) == 1
    assert not leaving_is_blocked(page)
    assert photos(live, "beer") == []
    assert errors_except(page, "403") == []


DENY = """Object.defineProperty(MediaDevices.prototype, 'getUserMedia', {
    configurable: true, value: () => Promise.reject(new DOMException('x', '%s')) });"""


@pytest.mark.parametrize(
    ("error", "text"),
    [
        ("NotAllowedError", "Kamera-Zugriff wurde verweigert"),
        ("NotFoundError", "Keine passende Kamera gefunden."),
        ("NotReadableError", "von einer anderen App benutzt"),
    ],
    ids=["denied", "no-camera", "in-use"],
)
def test_camera_errors_say_what_to_do(guest: Page, live: LiveServer, error: str, text: str):
    page = guest
    page.add_init_script(DENY % error)
    page.goto(live.url("/x/beer/"))
    screen = page.get_by_test_id("camera-error")
    expect(screen).to_be_visible(timeout=READY)
    expect(screen).to_contain_text("Die Kamera geht nicht")
    expect(screen).to_contain_text(text)
    expect(screen.get_by_role("button", name="Seite neu laden")).to_be_visible()
    expect(screen.get_by_role("link", name="Zum Start")).to_be_visible()
    expect(page.get_by_test_id("shutter")).to_be_disabled()
    if error == "NotAllowedError":
        shot(page, "beer-camera-denied")
    assert page.js_errors == []


def test_boot_failure_offers_a_reload(guest: Page, live: LiveServer):
    """/api/identify fails (flaky WiFi, a blocker): no endless spinner, a way forward."""
    page = guest
    page.route("**/api/identify", lambda route: route.abort())
    page.goto(live.url("/x/beer/"))
    screen = page.get_by_test_id("fatal")
    expect(screen).to_contain_text(re.compile("Keine (Antwort|Verbindung)"), timeout=READY)
    page.unroute("**/api/identify")
    screen.get_by_role("button", name="Seite neu laden").click()
    expect(page.get_by_test_id("shutter")).to_be_enabled(timeout=READY)
    expect(page.get_by_test_id("fatal")).to_have_count(0)


def test_keyboard_only(guest: Page, live: LiveServer):
    """Space shoots from the page, Enter on "Noch ein Bier", Escape leaves the print."""
    page = guest
    open_beer(page, live)
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("Space")
    expect_counted(page, 1)
    expect(page.get_by_test_id("again")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("result-photo")).to_have_count(0)
    expect(page.get_by_test_id("shutter")).to_be_focused()
    page.keyboard.press("Space")  # the focused shutter
    expect_counted(page, 2)
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("result-photo")).to_have_count(0)
    expect(page.get_by_test_id("shutter")).to_be_enabled()
    assert page.js_errors == []


def test_shortcuts_wait_while_a_dialog_is_open(guest: Page, live: LiveServer):
    page = guest
    open_beer(page, live)
    uploads: list[str] = []
    page.on("request", lambda r: uploads.append(r.url) if r.url.endswith("/upload") else None)
    page.evaluate(
        """() => {
        const d = document.createElement('div');
        d.setAttribute('role', 'dialog');
        d.id = 'e2e-dialog';
        const input = document.createElement('input');
        d.append(input);
        document.body.append(d);
        document.activeElement && document.activeElement.blur();
    }"""
    )
    for key in ("Space", "Enter"):
        page.keyboard.press(key)
    page.locator("#e2e-dialog input").focus()
    page.keyboard.type("a b ")
    page.wait_for_timeout(400)
    assert uploads == []
    expect(page.get_by_test_id("result-photo")).to_have_count(0)
    page.evaluate(
        "() => { document.getElementById('e2e-dialog').remove(); document.activeElement.blur(); }"
    )
    page.keyboard.press("Space")
    expect_counted(page, 1)
    assert len(uploads) == 1


def test_the_number_is_the_board_count(guest: Page, live: LiveServer, admin: Admin):
    """Hosts took a beer down: the photo's seq runs ahead of the board. The guest sees one number."""
    add_beers(live, 3)
    admin.hide(photos(live, "beer")[0].public_id)
    page = guest
    open_beer(page, live)
    counter = page.get_by_test_id("counter")
    expect(counter).to_have_attribute("data-total", "2")
    expect(counter).to_contain_text("0003")
    page.get_by_test_id("shutter").click()
    expect_counted(page, 3)
    expect(page.get_by_test_id("upload-status")).to_contain_text("0003")
    assert photos(live, "beer")[-1].seq == 4  # the stored number is unchanged
    again(page)
    expect(counter).to_have_attribute("data-total", "3")
    assert page.js_errors == []


def test_counter_follows_the_party(guest: Page, live: LiveServer):
    add_beers(live, 3)
    page = guest
    open_beer(page, live)
    counter = page.get_by_test_id("counter")
    expect(counter).to_have_attribute("data-total", "3")
    page.get_by_test_id("shutter").click()
    expect_counted(page, 4)
    expect(page.get_by_test_id("result-text")).to_contain_text(
        re.compile(r"Noch 999\.996 bis zur Million\.")
    )
    # meanwhile others keep drinking; "Noch ein Bier" fetches the fresh total
    add_beers(live, 1000)
    again(page)
    expect(counter).to_have_attribute("data-total", "1004")
    expect(counter).to_contain_text("1005")
    assert page.js_errors == []


# ----------------------------------------------------------------- layouts


def inside(page: Page, testid: str) -> dict:
    """The element is fully on screen, without scrolling."""
    box = page.get_by_test_id(testid).first.bounding_box()
    size = page.viewport_size
    assert box and size, testid
    assert box["x"] >= -1 and box["y"] >= -1, (testid, box)
    assert box["x"] + box["width"] <= size["width"] + 1, (testid, box, size)
    assert box["y"] + box["height"] <= size["height"] + 1, (testid, box, size)
    return box


def no_page_scroll(page: Page) -> None:
    sizes = page.evaluate(
        "() => [document.documentElement.scrollWidth, innerWidth, document.documentElement.scrollHeight, innerHeight]"
    )
    assert sizes[0] <= sizes[1] + 1 and sizes[2] <= sizes[3] + 1, sizes


def test_phone_landscape(guest: Page, live: LiveServer):
    page = guest
    page.set_viewport_size({"width": 844, "height": 390})
    open_beer(page, live)
    frame = inside(page, "frame")
    assert frame["height"] > 380, frame  # the full screen height, not a stamp
    assert frame["width"] / frame["height"] == pytest.approx(3 / 4, abs=0.01)
    assert frame["x"] < 10  # stage left
    for testid in ("shutter", "vessel", "switch-camera", "back", "counter", "guest-pass", "hint"):
        box = inside(page, testid)
        if testid in ("shutter", "vessel", "switch-camera", "counter", "hint"):
            assert box["x"] >= frame["x"] + frame["width"] - 1, (
                testid
            )  # controls right of the stage
    no_page_scroll(page)
    shot(page, "beer-landscape")

    page.get_by_test_id("shutter").click()
    expect_counted(page, 1)
    for testid in ("again", "success-title", "upload-status", "result-photo"):
        inside(page, testid)
    no_page_scroll(page)
    shot(page, "beer-landscape-result", 900)
    again(page)
    assert page.js_errors == []


@pytest.mark.parametrize("size", [(390, 844), (360, 640)], ids=["phone", "small"])
def test_portrait_fits(guest: Page, live: LiveServer, size: tuple[int, int]):
    page = guest
    page.set_viewport_size({"width": size[0], "height": size[1]})
    open_beer(page, live)
    frame = inside(page, "frame")
    # edge to edge on a phone; small phones keep the film edge and controls under it
    assert frame["width"] >= (size[0] - 1 if size[1] > 700 else 0.9 * size[0]), frame
    for testid in ("shutter", "vessel", "switch-camera", "back", "counter", "guest-pass", "hint"):
        inside(page, testid)
    no_page_scroll(page)
    shot(page, f"beer-camera-{'small' if size[1] < 700 else 'phone'}")
    page.get_by_test_id("shutter").click()
    expect_counted(page, 1)
    for testid in ("again", "success-title", "upload-status"):
        inside(page, testid)
    no_page_scroll(page)
    assert page.js_errors == []
