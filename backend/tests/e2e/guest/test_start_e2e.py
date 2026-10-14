"""Start in a real browser: the activity strips with their live lines, "Deine
Bilder" (only the guest's own visible photos) and the viewer, the guest pass and
its "Du" sheet (Instagram name), the status slot (paused, stopped), the banned
screen, and the layouts (small phone, landscape, desktop). Ported from
the pre-overhaul test_core_e2e.py, test_core_ui_e2e.py and the guest part of
test_desktop_e2e.py."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from virtubooth.domain.models import PhotoQuery

from ..conftest import (
    QUICK_TAP_MS,
    LiveServer,
    accept_consent_in_browser,
    covered_by_toast,
    join_via_api,
    shot,
)
from .conftest import errors_besides, no_horizontal_scroll, only_user, reload, upload

pytestmark = pytest.mark.e2e


def wake(page: Page) -> None:
    """What a guest returning to the tab does: the session re-checks."""
    page.evaluate("() => window.dispatchEvent(new Event('focus'))")


def test_activity_strips_with_live_lines(guest_page: Page, live: LiveServer):
    page = guest_page
    beer, booth = page.get_by_test_id("tile-beer"), page.get_by_test_id("tile-booth")
    expect(beer).to_be_visible()
    expect(booth).to_be_visible()
    expect(beer).to_contain_text("Beer Cam")
    expect(page.get_by_test_id("beer-count")).to_have_text("0000")
    expect(beer).to_contain_text("von 1 Mio. Bieren")
    expect(booth).to_contain_text("10 Filter")
    upload(page, "beer")
    reload(page)
    expect(page.get_by_test_id("beer-count")).to_have_text("0001")
    expect(beer).to_have_attribute("href", "/x/beer/")
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_deine_bilder_shows_only_own_visible_photos(guest_page: Page, live: LiveServer, make_page):
    page = guest_page
    expect(page.get_by_test_id("my-photos-empty")).to_be_visible()
    expect(page.get_by_test_id("my-photos")).to_contain_text("Noch keine Bilder")
    a = upload(page, "beer", (200, 60, 40))["photo"]
    b = upload(page, "booth", (40, 60, 200))["photo"]
    c = upload(page, "beer", (60, 200, 40))["photo"]
    live.core.services.moderation.hide_photo(b["id"], actor="admin")
    other = make_page()
    join_via_api(other, live)
    d = upload(other, "beer")["photo"]
    reload(page)
    tiles = page.locator("[data-testid=my-photos] [data-testid^=photo-]")
    expect(tiles).to_have_count(2)
    ids = [t.get_attribute("data-testid") for t in tiles.all()]
    assert ids == [f"photo-{c['id']}", f"photo-{a['id']}"]  # newest first, own, visible
    assert f"photo-{d['id']}" not in ids
    expect(page.get_by_test_id("my-photos").get_by_role("heading")).to_have_text(
        re.compile(r"Deine Bilder\s*2")
    )
    expect(page.get_by_test_id("my-photos-empty")).to_have_count(0)

    # the viewer: large, Speichern downloads the JPEG under the server's name
    page.get_by_test_id(f"photo-{c['id']}").get_by_role("button").click()
    viewer = page.get_by_test_id("photo-viewer")
    expect(viewer.get_by_role("dialog")).to_be_visible()
    expect(viewer).to_contain_text("Bier")
    save = page.get_by_test_id("photo-save")
    expect(save).to_be_enabled()
    with page.expect_download() as info:
        save.click()
    assert info.value.suggested_filename == f"beer-{c['seq']:05d}.jpg"
    expect(page.get_by_text("Gespeichert")).to_be_visible()
    # the toast moves above the sheet: Speichern and the arrows take the next tap at once
    assert covered_by_toast(page) == []
    with page.expect_download():
        save.tap(timeout=QUICK_TAP_MS)
    # arrow keys walk through the photos
    expect(viewer.get_by_role("img")).to_have_attribute("src", c["url"])
    page.keyboard.press("ArrowRight")
    expect(viewer.get_by_role("img")).to_have_attribute("src", a["url"])
    page.keyboard.press("Escape")
    expect(viewer.get_by_role("dialog")).to_have_count(0)
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_viewer_closes_when_the_host_hides_its_photo(page: Page, live: LiveServer):
    """The host hides the photo a guest is looking at: on the next refresh of "Deine
    Bilder" the viewer closes and says so, instead of jumping to the next photo."""
    page.clock.install()
    join_via_api(page, live)
    older = upload(page, "beer", (200, 60, 40))["photo"]
    newer = upload(page, "beer", (60, 200, 40))["photo"]
    reload(page)
    page.get_by_test_id(f"photo-{newer['id']}").get_by_role("button").click()
    viewer = page.get_by_test_id("photo-viewer")
    expect(viewer.get_by_role("img")).to_have_attribute("src", newer["url"])
    live.core.services.moderation.hide_photo(newer["id"], actor="admin")
    page.clock.fast_forward(20_000)  # the photos are stale now
    wake(page)
    expect(page.get_by_text("Dieses Bild ist nicht mehr zu sehen.")).to_be_visible()
    expect(viewer.get_by_role("dialog")).to_have_count(0)
    # the other photo is still there and opens as before
    tiles = page.locator("[data-testid=my-photos] [data-testid^=photo-]")
    expect(tiles).to_have_count(1)
    page.get_by_test_id(f"photo-{older['id']}").get_by_role("button").click()
    expect(viewer.get_by_role("img")).to_have_attribute("src", older["url"])
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_a_new_shot_shows_in_deine_bilder_on_the_way_back(guest_page: Page, live: LiveServer):
    """Start -> Beer Cam -> shot -> back, all inside the app (no reload): the photo is
    in "Deine Bilder" right away, not "Noch keine Bilder" from before the shot."""
    page = guest_page
    expect(page.get_by_test_id("my-photos-empty")).to_be_visible()
    page.get_by_test_id("tile-beer").click()
    expect(page.get_by_test_id("beer-app")).to_have_attribute("data-ready", "1", timeout=20_000)
    page.get_by_test_id("shutter").click()
    expect(page.get_by_test_id("upload-status")).to_have_attribute(
        "data-state", "done", timeout=20_000
    )
    page.get_by_test_id("back").click()
    expect(page.get_by_test_id("start")).to_be_visible()
    (photo,) = live.core.repos.photos.list(PhotoQuery(user_id=only_user(live).id))
    expect(page.get_by_test_id(f"photo-{photo.public_id}")).to_be_visible()
    expect(page.get_by_test_id("my-photos-empty")).to_have_count(0)
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_instagram_name_in_the_du_sheet(guest_page: Page, live: LiveServer):
    page = guest_page
    passed = page.get_by_test_id("guest-pass")
    expect(passed).to_contain_text("Instagram hinzufügen")
    name = only_user(live).name
    assert passed.locator("[title]").first.get_attribute("title") == name
    passed.focus()
    page.keyboard.press("Enter")
    sheet = page.get_by_role("dialog", name=name)
    expect(sheet).to_be_visible()
    expect(sheet).to_contain_text("zufällig")  # why the name is random
    expect(page.get_by_test_id("guest-upload-state")).to_contain_text(
        "Du kannst Fotos machen und hochladen."
    )
    field = sheet.get_by_label("Instagram-Name")
    # Escape closes it and focus goes back to the pass
    page.keyboard.press("Escape")
    expect(sheet).to_have_count(0)
    expect(passed).to_be_focused()

    passed.click()
    field.fill("@müller")
    sheet.get_by_role("button", name="Speichern").click()
    expect(sheet).to_contain_text("keine Umlaute")
    expect(field).to_be_focused()
    field.fill("x" * 40)
    expect(field).to_have_value("x" * 30)  # Instagram's limit
    field.fill("neu.name")
    sheet.get_by_role("button", name="Speichern").click()
    expect(sheet).to_have_count(0)
    expect(passed).to_contain_text("@neu.name")
    expect(page.get_by_text("Gespeichert: @neu.name")).to_be_visible()
    assert only_user(live).instagram == "neu.name"

    # remove it again
    passed.click()
    expect(field).to_have_value("neu.name")
    sheet.get_by_role("button", name="Entfernen").click()
    expect(sheet).to_have_count(0)
    expect(passed).to_contain_text("Instagram hinzufügen")
    assert only_user(live).instagram is None
    assert errors_besides(page, "400 (Bad Request)", "status of 400") == []


def test_long_handle_ellipsizes_on_a_small_phone(make_page, live: LiveServer):
    page = make_page("small")
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    # the longest handle Instagram allows, in wide letters: too wide in every engine
    # ("a" * 30 just fits in WebKit's metrics)
    handle = "w" * 30
    live.core.repos.users.set_instagram(only_user(live).id, handle)
    reload(page)
    passed = page.get_by_test_id("guest-pass")
    expect(passed).to_contain_text("@" + handle)
    box = passed.bounding_box()
    assert box is not None and box["x"] + box["width"] <= 360 - 16 + 1
    label = passed.get_by_text("@" + handle)
    assert label.evaluate("(el) => el.scrollWidth > el.clientWidth")  # cut with an ellipsis
    assert no_horizontal_scroll(page)
    shot(page, "start_long_handle_small")
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_paused_and_stopped_show_in_the_status_slot(guest_page: Page, live: LiveServer):
    page = guest_page
    expect(page.get_by_test_id("status-slot")).to_have_count(0)
    user = only_user(live)
    controls = live.core.services.upload_controls
    controls.set_user_paused(user.id, True, actor="admin")
    wake(page)
    slot = page.get_by_test_id("status-slot")
    expect(slot).to_have_attribute("data-kind", "paused")
    expect(slot).to_have_text(re.compile("Hochladen pausiert"))
    expect(page.get_by_test_id("guest-pass")).to_have_attribute("data-status", "paused")
    slot.click()
    info = page.get_by_role("dialog", name="Hochladen pausiert")
    expect(info).to_contain_text("Die Gastgeber geben es bald wieder frei")
    info.get_by_role("button", name="Alles klar").click()
    expect(info).to_have_count(0)
    shot(page, "start_paused")

    # paused wins over stopped (server precedence); unpaused, the stop shows
    controls.set_stop(True, actor="admin")
    controls.set_user_paused(user.id, False, actor="admin")
    reload(page)
    expect(slot).to_have_attribute("data-kind", "stopped")
    expect(slot).to_contain_text("Hochladen ist kurz angehalten")

    # the host lifts the stop: the next check clears the slot and says so
    controls.set_stop(False, actor="admin")
    page.wait_for_timeout(2100)  # quick re-checks are throttled to one per 2 s
    wake(page)
    expect(slot).to_have_count(0)
    expect(page.get_by_text("Du kannst wieder hochladen.")).to_be_visible()
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_banned_guest_sees_why_and_can_come_back(guest_page: Page, live: LiveServer):
    page = guest_page
    user = only_user(live)
    live.core.services.moderation.ban_user(user.id, reason="Test", actor="admin")
    reload(page)
    banned = page.get_by_test_id("banned")
    expect(banned).to_be_visible()
    expect(banned).to_contain_text("Gesperrt")
    expect(banned).to_contain_text("Dieses Gerät ist gesperrt")
    expect(page.get_by_test_id("start")).to_have_count(0)
    again = banned.get_by_role("button", name="Seite neu laden")
    expect(again).to_be_focused()
    shot(page, "banned")
    # activities stay closed too
    page.goto(live.url("/x/beer/"))
    expect(page.get_by_test_id("banned")).to_be_visible()
    # the host lifts the ban: the guest reloads and is back
    live.core.services.moderation.unban_user(user.id, actor="admin")
    page.get_by_test_id("banned").get_by_role("button", name="Seite neu laden").click()
    page.goto(live.url("/"))
    expect(page.get_by_test_id("start")).to_be_visible()
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_a_ban_found_on_start_asks_for_no_photos(page: Page, live: LiveServer):
    """Back on the tab after a ban: the session's re-check finds it, Start makes way,
    and "Deine Bilder" (403 for a banned device, logged as an error) is not asked for,
    not even with stale photos."""
    page.clock.install()
    join_via_api(page, live)
    expect(page.get_by_test_id("my-photos")).to_have_attribute("data-state", "ready")
    asked: list[str] = []
    page.on("request", lambda r: asked.append(r.url) if "/api/me/photos" in r.url else None)
    live.core.services.moderation.ban_user(only_user(live).id, reason="Test", actor="admin")
    page.clock.fast_forward(20_000)  # the photos are stale now
    wake(page)
    expect(page.get_by_test_id("banned")).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert asked == []
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_start_on_desktop(make_page, live: LiveServer):
    """The host's PC: hero and own photos left, the strips right; Enter on a strip opens it."""
    page = make_page("desk")
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    title = page.get_by_role("heading", level=1)
    beer = page.get_by_test_id("tile-beer")
    expect(beer).to_be_visible()
    t, b = title.bounding_box(), beer.bounding_box()
    assert t and b and b["x"] > t["x"] + t["width"] / 2, (t, b)  # side by side
    assert no_horizontal_scroll(page)
    page.get_by_test_id("tile-booth").focus()
    page.keyboard.press("Enter")
    page.wait_for_url(live.url("/x/booth/"))
    assert page.js_errors == []  # type: ignore[attr-defined]


@pytest.mark.parametrize("view", ["small", "land", "phone"])
def test_start_fits_without_sideways_scrolling(make_page, live: LiveServer, view: str):
    page = make_page(view)
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    expect(page.get_by_test_id("tile-booth")).to_be_visible()
    upload(page, "beer")
    reload(page)
    expect(page.locator("[data-testid=my-photos] [data-testid^=photo-]")).to_have_count(1)
    assert no_horizontal_scroll(page)
    width = page.viewport_size["width"] if page.viewport_size else 0
    for testid in ("guest-pass", "tile-beer", "tile-booth"):
        box = page.get_by_test_id(testid).bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= width, (testid, box)
    if view == "land":  # two columns: the strips sit next to the party's name
        t = page.get_by_role("heading", level=1).bounding_box()
        b = page.get_by_test_id("tile-beer").bounding_box()
        assert t and b and b["x"] >= t["x"] + 200, (t, b)
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_footer_reopens_the_join_text(guest_page: Page, live: LiveServer):
    page = guest_page
    expect(page.get_by_test_id("start")).to_contain_text(
        "Die Gastgeber posten ausgewählte Fotos auf @e2e.party"
    )
    page.get_by_role("button", name="Was passiert mit meinen Fotos?").click()
    sheet = page.get_by_role("dialog", name="Was passiert mit meinen Fotos?")
    expect(sheet).to_contain_text("erkennt die Seite dein Gerät")  # the accepted texts, read-only
    expect(sheet.get_by_role("textbox")).to_have_count(0)
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Hilfe").click()
    help_sheet = page.get_by_role("dialog", name="Hilfe")
    help_sheet.get_by_role("button", name="Die Kamera startet nicht").click()
    expect(help_sheet).to_contain_text("Danach die Seite neu laden")
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_join_text_comes_from_the_server(page: Page, live: LiveServer):
    """A guest who joined elsewhere (another browser profile, cleared storage) reads
    the server's join texts, not a short fallback: identify sends them."""
    join_via_api(page, live)
    page.evaluate("() => localStorage.clear()")
    reload(page)
    page.get_by_role("button", name="Was passiert mit meinen Fotos?").click()
    sheet = page.get_by_role("dialog", name="Was passiert mit meinen Fotos?")
    # only the server's texts say this (the fallback doesn't)
    expect(sheet).to_contain_text("Bei Ärger können wir einzelne Geräte sperren.")
    expect(sheet).to_contain_text("@e2e.party")
    assert page.evaluate("() => localStorage.getItem('vb_join_text')") is None
    assert page.js_errors == []  # type: ignore[attr-defined]
