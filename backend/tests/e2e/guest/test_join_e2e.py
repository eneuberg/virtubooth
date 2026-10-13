"""The join sheet in a real browser: QR entry → join → Start, the Instagram name
(valid, invalid, pasted link), changed texts, deep links, two tabs, keyboard only,
small phones. Ported from e2e_legacy/test_core_e2e.py and test_core_ui_e2e.py
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
from .conftest import errors_besides, only_user, reload

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
    expect(sheet).to_contain_text("Gleich geht’s zur Beer Cam.")
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
