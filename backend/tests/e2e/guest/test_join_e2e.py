"""The join sheet in a real browser: QR entry → join → Start, the Instagram name
(valid, invalid, pasted link), changed texts, deep links, two tabs, keyboard only,
small phones. Ported from the pre-overhaul test_core_e2e.py and test_core_ui_e2e.py
(selectors changed, behaviour kept) plus the guest part of test_firefox_e2e.py
(no camera before joining)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import (
    JOIN_ACCEPT,
    LiveServer,
    accept_consent_in_browser,
    allow_clipboard,
    needs_clipboard,
    settle_dialogs,
    shot,
    track_errors,
)
from .conftest import errors_besides, only_user, reload, upload

pytestmark = pytest.mark.e2e

TITLE = "Willkommen bei E2E Party"
# visible area with the browser's bars: iPhone SE in Safari, small Androids,
# iPhone 5/SE 1st gen, Galaxy S-class, the reference phone
PHONES = [(375, 548), (360, 560), (320, 568), (360, 640), (390, 844)]

# records getUserMedia calls, then lets the browser handle them as usual
CAMERA_SPY = """(() => {
  const md = window.MediaDevices && MediaDevices.prototype;
  window.__cameraRequests = [];
  if (!md || !md.getUserMedia) return;
  const gum = md.getUserMedia;
  Object.defineProperty(md, 'getUserMedia', { configurable: true, writable: true,
    value: function (c) { window.__cameraRequests.push(JSON.parse(JSON.stringify(c || {}))); return gum.call(this, c); } });
})();"""

IN_SHEET_AT = """([x, y]) => {
  const el = document.elementFromPoint(x, y);
  return !!el && !!el.closest('button[type=submit]') && !!el.closest('[data-testid=join]');
}"""


def test_qr_entry_join_then_start(page: Page, live: LiveServer):
    page.goto(live.entry("/"))
    assert page.url == live.url("/")  # the token moved into a cookie
    sheet = page.get_by_role("dialog", name=TITLE)
    expect(sheet).to_be_visible()
    expect(page).to_have_title("E2E Party")  # the party's name shows before joining
    expect(page.get_by_text("E2E Party", exact=True)).to_be_visible()
    # the server's texts, typeset: no emoji in the title or the button
    expect(sheet.get_by_role("heading", level=2)).not_to_contain_text("🎉")
    expect(page.locator(JOIN_ACCEPT)).to_have_text("Alles klar, los geht’s!")
    expect(sheet).to_contain_text("@e2e.party")
    accept_consent_in_browser(page, instagram="@e2e.guest")
    expect(page.get_by_test_id("start")).to_be_visible()
    expect(page.get_by_test_id("guest-pass")).to_contain_text("@e2e.guest")
    user = only_user(live)
    assert user.instagram == "e2e.guest"
    assert user.fp_hash and len(user.fp_hash) == 64
    assert not user.fp_components.get("fallback")
    assert page.evaluate("() => localStorage.getItem('vb_uid')")  # the uid_token fallback copy
    # second visit: no sheet, the same guest
    reload(page)
    expect(page.get_by_test_id("start")).to_be_visible()
    expect(page.get_by_test_id("join")).to_have_count(0)
    assert len(live.core.repos.users.list()) == 1
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_lost_cookie_comes_back_through_the_stored_uid(page: Page, live: LiveServer):
    """ITP or a cleared cookie: localStorage still has the uid_token, so the guest
    keeps the identity instead of joining again."""
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    name = only_user(live).name
    page.context.clear_cookies(name="vb_uid")
    reload(page)
    expect(page.get_by_test_id("start")).to_be_visible()
    expect(page.get_by_test_id("join")).to_have_count(0)
    expect(page.get_by_test_id("guest-pass")).to_contain_text(name.rsplit(" #", 1)[0])
    assert len(live.core.repos.users.list()) == 1
    assert any(c["name"] == "vb_uid" for c in page.context.cookies())  # pinned again
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_join_sheet_has_one_action_and_works_by_keyboard_only(page: Page, live: LiveServer):
    page.goto(live.entry("/"))
    dialog = page.get_by_role("dialog", name=TITLE)
    expect(dialog).to_be_focused()  # the dialog, not the field: no phone keyboard over the text
    settle_dialogs(page)
    # one action: the accept button. "Mehr dazu" only discloses text.
    buttons = page.get_by_test_id("join").get_by_role("button")
    names = [b.inner_text().strip() for b in buttons.all()]
    assert names == ["Mehr dazu", "Alles klar, los geht’s!"], names
    expect(page.locator("[data-testid=join] button[aria-expanded]")).to_have_count(1)
    # it can't be dismissed: declining means not using the site
    page.keyboard.press("Escape")
    page.mouse.click(5, 5)
    expect(dialog).to_be_visible()
    more = page.get_by_role("button", name="Mehr dazu")
    field = page.get_by_test_id("join").get_by_role("textbox")
    accept = page.locator(JOIN_ACCEPT)
    page.keyboard.press("Tab")
    expect(more).to_be_focused()
    page.keyboard.press("Enter")
    expect(dialog).to_contain_text("erkennt die Seite dein Gerät")
    page.keyboard.press("Tab")  # the Live-Wall opt-out under „Mehr dazu“
    expect(page.get_by_test_id("analysis-opt-out").get_by_role("switch")).to_be_focused()
    page.keyboard.press("Tab")
    expect(field).to_be_focused()
    page.keyboard.press("Tab")
    expect(accept).to_be_focused()
    page.keyboard.press("Tab")  # focus stays inside the sheet
    expect(more).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(accept).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(field).to_be_focused()
    page.keyboard.type("@keys.only")
    page.keyboard.press("Enter")  # submits
    expect(page.get_by_test_id("join")).to_have_count(0)
    expect(page.get_by_test_id("guest-pass")).to_contain_text("@keys.only")
    assert only_user(live).instagram == "keys.only"
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_join_errors_say_what_is_wrong_with_the_name(page: Page, live: LiveServer):
    page.goto(live.entry("/"))
    field = page.get_by_test_id("join").get_by_role("textbox")
    assert field.get_attribute("maxlength") == "30"
    field.fill("jürgen")
    page.locator(JOIN_ACCEPT).click()
    expect(page.get_by_test_id("join")).to_contain_text("keine Umlaute")
    expect(field).to_be_focused()
    expect(field).to_have_attribute("aria-invalid", "true")
    assert live.core.repos.users.list() == []
    field.fill("@party.anna")  # the typed @ goes: the field shows a fixed one
    expect(field).to_have_value("party.anna")
    page.locator(JOIN_ACCEPT).click()
    expect(page.get_by_test_id("join")).to_have_count(0)
    assert only_user(live).instagram == "party.anna"
    assert errors_besides(page, "400 (Bad Request)", "status of 400") == []


@needs_clipboard
def test_pasted_profile_link_keeps_just_the_name(page: Page, live: LiveServer):
    """maxlength (30) would cut a pasted link to its first 30 characters."""
    allow_clipboard(page.context)
    page.goto(live.entry("/"))
    field = page.get_by_test_id("join").get_by_role("textbox")
    page.evaluate(
        "(t) => navigator.clipboard.writeText(t)",
        "https://www.instagram.com/party.anna/?igsh=abcdefghijklmnop",
    )
    field.focus()
    page.keyboard.press("ControlOrMeta+V")
    expect(field).to_have_value("party.anna")


def test_changed_texts_are_shown_again_before_joining(page: Page, live: LiveServer):
    """The host bumps the texts' version while the sheet is open: the guest gets the
    new texts (here: a new party name) and accepts those, no reload needed."""
    page.goto(live.entry("/"))
    expect(page.get_by_role("dialog", name=TITLE)).to_be_visible()
    live.core.settings = live.core.settings.replace(consent_version="2", party_name="Neue Party")
    page.locator(JOIN_ACCEPT).click()
    expect(page.get_by_role("dialog", name="Willkommen bei Neue Party")).to_be_visible()
    expect(page.get_by_test_id("join").get_by_role("alert")).to_contain_text(
        "Die Hinweise haben sich gerade geändert"
    )
    assert live.core.repos.users.list() == []
    page.locator(JOIN_ACCEPT).click()
    expect(page.get_by_test_id("join")).to_have_count(0)
    expect(page.get_by_test_id("start")).to_be_visible()
    assert only_user(live).consent_version == "2"
    assert errors_besides(page, "409 (Conflict)", "status of 409") == []


def test_deep_link_to_an_activity_shows_the_join_sheet_first(page: Page, live: LiveServer):
    """A QR code on the Beer Cam: the sheet comes first, and the camera (with the
    browser's camera prompt) only after joining."""
    page.add_init_script(CAMERA_SPY)
    page.goto(live.entry("/x/beer/"))
    assert page.url == live.url("/x/beer/")
    sheet = page.get_by_test_id("join")
    expect(sheet).to_be_visible()
    expect(sheet).to_contain_text("Danach öffnet sich „Beer Cam“.")
    page.wait_for_timeout(500)
    assert page.evaluate("() => window.__cameraRequests.length") == 0
    assert page.get_by_test_id("activity-menu").count() == 0  # the activity is not rendered
    accept_consent_in_browser(page)
    assert page.url == live.url("/x/beer/")
    expect(page.get_by_test_id("start")).to_have_count(0)
    assert len(live.core.repos.users.list()) == 1


def test_second_tab_joining_keeps_its_handle(context, live: LiveServer):
    """Both tabs show the sheet on a first visit. The first joins without a name,
    the second with one: the name is stored and the second tab says it is the
    same guest."""
    a = track_errors(context.new_page())
    b = track_errors(context.new_page())
    a.goto(live.entry("/"))
    b.goto(live.entry("/"))
    expect(b.get_by_test_id("join")).to_be_visible()
    accept_consent_in_browser(a)
    accept_consent_in_browser(b, instagram="@tab.b")
    expect(b.get_by_text("Du bist schon dabei als")).to_contain_text("@tab.b")
    expect(b.get_by_test_id("guest-pass")).to_contain_text("@tab.b")
    user = only_user(live)
    assert user.instagram == "tab.b"
    assert a.js_errors == [] and b.js_errors == []  # type: ignore[attr-defined]


def test_second_tab_with_another_handle_is_told_which_one_counts(context, live: LiveServer):
    a = track_errors(context.new_page())
    b = track_errors(context.new_page())
    a.goto(live.entry("/"))
    b.goto(live.entry("/"))
    expect(b.get_by_test_id("join")).to_be_visible()
    accept_consent_in_browser(a, instagram="@tab.a")
    accept_consent_in_browser(b, instagram="@tab.b")
    note = b.get_by_text("Du bist schon dabei als")
    expect(note).to_contain_text("@tab.a")
    expect(note).to_contain_text("Tipp auf deinen Namen")
    expect(b.get_by_test_id("guest-pass")).to_contain_text("@tab.a")
    assert only_user(live).instagram == "tab.a"
    assert a.js_errors == [] and b.js_errors == []  # type: ignore[attr-defined]


@pytest.mark.parametrize(("width", "height"), PHONES, ids=[f"{w}x{h}" for w, h in PHONES])
def test_join_button_is_on_screen_on_small_phones(
    make_page, live: LiveServer, width: int, height: int
):
    page = make_page("phone", viewport={"width": width, "height": height})
    page.goto(live.entry("/"))
    expect(page.get_by_role("dialog", name=TITLE)).to_be_visible()
    settle_dialogs(page)
    box = page.locator(JOIN_ACCEPT).bounding_box()
    assert box is not None
    assert box["x"] >= 0 and box["x"] + box["width"] <= width, box
    assert box["y"] >= 0 and box["y"] + box["height"] <= height, box
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    assert page.evaluate(IN_SHEET_AT, [x, y]), "something covers the button"
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    shot(page, f"join_{width}x{height}")
    page.mouse.click(x, y)  # right there, no scrolling
    expect(page.get_by_test_id("join")).to_have_count(0)
    assert len(live.core.repos.users.list()) == 1
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_join_sheet_marks_more_text_below_until_the_end(make_page, live: LiveServer):
    page = make_page("phone", viewport={"width": 320, "height": 460})
    page.goto(live.entry("/"))
    expect(page.get_by_role("dialog", name=TITLE)).to_be_visible()
    settle_dialogs(page)
    footer = page.locator("[data-testid=join] [data-more]")
    expect(footer).to_have_count(1)  # the footer shows an edge: there is more above it
    page.get_by_test_id("join").locator(".overflow-y-auto").evaluate(
        "(el) => { el.scrollTop = el.scrollHeight; }"
    )
    expect(footer).to_have_count(0)
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_live_wall_analysis_opt_out(page: Page, live: LiveServer):
    """„Meine Fotos nicht automatisch auswerten“: in the join sheet's „Mehr dazu“
    and later in the Du sheet."""
    page.goto(live.entry("/"))
    sheet = page.get_by_test_id("join")
    sheet.get_by_role("button", name="Mehr dazu").click()
    expect(sheet).to_contain_text("Für die Live-Wall der Party werden Fotos automatisch")
    switch = page.get_by_test_id("analysis-opt-out").get_by_role("switch")
    page.get_by_test_id("analysis-opt-out").get_by_text("Meine Fotos nicht").click()
    expect(switch).to_be_checked()
    accept_consent_in_browser(page)
    expect(page.get_by_test_id("start")).to_be_visible()
    assert only_user(live).analysis_opt_out is True

    page.get_by_test_id("guest-pass").click()
    du = page.get_by_test_id("guest-analysis-opt-out").get_by_role("switch")
    expect(du).to_be_checked()
    page.get_by_test_id("guest-analysis-opt-out").get_by_text("Meine Fotos nicht").click()
    expect(du).not_to_be_checked()
    expect(page.get_by_text("Deine Fotos werden wieder ausgewertet")).to_be_visible()
    for _ in range(50):  # the PUT lands right after the switch flips
        if not only_user(live).analysis_opt_out:
            break
        page.wait_for_timeout(100)
    assert only_user(live).analysis_opt_out is False
    assert page.js_errors == []  # type: ignore[attr-defined]


def _external_ai_on(live: LiveServer) -> None:
    live.core.repos.app_settings.put(
        "x.llm.config",
        {"enabled": True, "detect": {"local": True, "external": True}},
        at="2026-10-15T20:00:00.000+00:00",
    )


def test_external_ai_opt_out(page: Page, live: LiveServer):
    """„Keine Weitergabe an externe KI“: in plain sight in the join sheet while the host
    has an external AI on, explained under „Mehr dazu“, changeable in the Du sheet."""
    _external_ai_on(live)
    page.goto(live.entry("/"))
    sheet = page.get_by_test_id("join")
    switch = page.get_by_test_id("ai-opt-out").get_by_role("switch")
    expect(switch).not_to_be_checked()
    sheet.get_by_role("button", name="Mehr dazu").click()
    expect(sheet).to_contain_text("externen KI-Dienst (Anthropic, USA)")
    expect(sheet).not_to_contain_text("verlässt den Server")
    page.get_by_test_id("ai-opt-out").get_by_text("Keine Weitergabe an externe KI").click()
    expect(switch).to_be_checked()
    shot(page, "join-ai-opt-out-phone")
    accept_consent_in_browser(page)
    expect(page.get_by_test_id("start")).to_be_visible()
    assert only_user(live).ai_opt_out is True

    page.get_by_test_id("guest-pass").click()
    du = page.get_by_test_id("guest-ai-opt-out").get_by_role("switch")
    expect(du).to_be_checked()
    page.get_by_test_id("guest-ai-opt-out").get_by_text("Keine Weitergabe an externe KI").click()
    expect(du).not_to_be_checked()
    expect(page.get_by_text("Deine Fotos dürfen wieder an die externe KI")).to_be_visible()
    for _ in range(50):  # the PUT lands right after the switch flips
        if not only_user(live).ai_opt_out:
            break
        page.wait_for_timeout(100)
    assert only_user(live).ai_opt_out is False
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_the_explanation_is_there_without_external_ai(page: Page, live: LiveServer):
    page.goto(live.entry("/"))
    sheet = page.get_by_test_id("join")
    expect(page.get_by_test_id("ai-opt-out")).to_have_count(0)
    sheet.get_by_role("button", name="Mehr dazu").click()
    expect(sheet).to_contain_text("externen KI-Dienst (Anthropic, USA)")
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_display_name_in_the_du_sheet(page: Page, live: LiveServer):
    page.goto(live.entry("/"))
    accept_consent_in_browser(page, instagram="e2e.fred")
    expect(page.get_by_test_id("guest-pass")).to_contain_text("@e2e.fred")
    page.get_by_test_id("guest-pass").click()
    sheet = page.get_by_test_id("guest-sheet")
    field = sheet.get_by_label("Anzeigename")
    expect(field).to_have_attribute("placeholder", "@e2e.fred")
    # reserved: said at the field
    field.fill("Admin")
    sheet.get_by_role("button", name="Name speichern").click()
    expect(sheet.get_by_text("Dieser Name geht leider nicht.")).to_be_visible()
    shot(page, "du-display-name-error-phone")
    field.fill("  Party   Fred ")
    sheet.get_by_role("button", name="Name speichern").click()
    expect(page.get_by_test_id("guest-sheet")).to_have_count(0)
    expect(page.get_by_test_id("guest-pass")).to_contain_text("Party Fred")
    user = only_user(live)
    assert user.display_name == "Party Fred" and user.shown_name == "Party Fred"
    page.get_by_test_id("guest-pass").click()
    shot(page, "du-sheet-phone")
    assert errors_besides(page, "400 (Bad Request) @ http://127.0.0.1") == []


def test_delete_my_own_photo(page: Page, live: LiveServer):
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    photo = upload(page, "beer")["photo"]
    reload(page)
    page.get_by_test_id(f"photo-{photo['id']}").click()
    viewer = page.get_by_test_id("photo-viewer")
    expect(viewer).to_be_visible()
    viewer.get_by_test_id("photo-delete").click()
    confirm = page.get_by_test_id("photo-delete-confirm")
    expect(confirm).to_contain_text("Das lässt sich nicht rückgängig machen.")
    shot(page, "photo-delete-confirm-phone")
    confirm.get_by_role("button", name="Foto löschen").click()
    expect(page.get_by_text("Foto gelöscht.")).to_be_visible()
    expect(page.get_by_test_id("photo-viewer")).to_have_count(0)
    expect(page.get_by_test_id(f"photo-{photo['id']}")).to_have_count(0)
    gone = live.core.repos.photos.get(photo["id"], include_deleted=True)
    assert gone is not None and gone.deleted
    assert page.js_errors == []  # type: ignore[attr-defined]
