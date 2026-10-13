"""Core UI in a real browser: the join dialog on small phones, keyboard use of
the dialogs, the home page when the API can't be reached, the debug log, the
user chip, error texts (Instagram, Retry-After, in-app browsers)."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import (
    accept_consent_in_browser,
    allow_clipboard,
    needs_clipboard,
    new_context,
    settle_dialogs,
    shot,
    track_errors,
)

pytestmark = pytest.mark.e2e

# visible area with the browser's bars: iPhone SE in Safari, small Androids,
# iPhone 5/SE 1st gen, iPhone mini in Safari, Galaxy S-class, Pixel-ish
PHONES = [(375, 548), (360, 560), (320, 568), (375, 629), (360, 640), (390, 844)]

ACCEPT = "Alles klar"
MORE = re.compile(r"\bvb-sheet--more\b")


@pytest.fixture
def e2e_settings():
    # the account name adds a line to the join text, like at a real party
    return {"instagram_account": "@e2e.party.account"}


IN_SHEET_AT = """([x, y]) => {
  const el = document.elementFromPoint(x, y);
  return !!el && !!el.closest('button[type=submit]') && !!el.closest('[data-testid=join]');
}"""


def network_noise(errors: list[str]) -> list[str]:
    """Console lines for requests a test made fail on purpose."""
    noise = ("Failed to load resource", "ERR_", "NetworkError", "net::", "/api/")
    return [e for e in errors if not any(n in e for n in noise)]


def vb(page: Page, expression: str, arg=None):  # type: ignore[no-untyped-def]
    """Evaluate `expression` with the page's SDK module bound to `vb`."""
    return page.evaluate(
        f"async (arg) => {{ const vb = await import('/static/core/vb.js'); return ({expression}); }}", arg
    )


# ----------------------------------------------------------- join dialog


@pytest.mark.parametrize(("width", "height"), PHONES, ids=[f"{w}x{h}" for w, h in PHONES])
def test_join_button_is_on_screen_on_small_phones(browser, live, width, height):
    ctx = new_context(browser, viewport={"width": width, "height": height})
    try:
        page = track_errors(ctx.new_page())
        page.goto(live.entry("/"))
        expect(page.get_by_role("dialog", name="Willkommen bei E2E Party")).to_be_visible()
        settle_dialogs(page)
        box = page.get_by_role("button", name=ACCEPT).bounding_box()
        assert box is not None
        assert box["x"] >= 0 and box["x"] + box["width"] <= width, box
        assert box["y"] >= 0 and box["y"] + box["height"] <= height, box
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        assert page.evaluate(IN_SHEET_AT, [x, y]), "something covers the button"
        # when the text doesn't fit, it scrolls above the buttons and the dialog shows that
        if page.locator(".vb-sheet-body").evaluate("(el) => el.scrollHeight > el.clientHeight + 4"):
            expect(page.get_by_role("dialog")).to_have_class(MORE)
        shot(page, f"join_{width}x{height}")
        page.mouse.click(x, y)  # right there, no scrolling
        expect(page.get_by_test_id("join")).to_have_count(0)
        assert len(live.core.repo.list_users()) == 1
        assert page.js_errors == []
    finally:
        ctx.close()


def test_join_dialog_scroll_hint_goes_away_at_the_end(browser, live):
    ctx = new_context(browser, viewport={"width": 320, "height": 460})
    try:
        page = track_errors(ctx.new_page())
        page.goto(live.entry("/"))
        sheet = page.get_by_role("dialog")
        expect(sheet).to_have_class(MORE)
        settle_dialogs(page)
        shot(page, "join_320x460_more")
        page.locator(".vb-sheet-body").evaluate("(el) => { el.scrollTop = el.scrollHeight; }")
        expect(sheet).not_to_have_class(MORE)
        assert page.js_errors == []
    finally:
        ctx.close()


def test_party_name_shows_before_joining(page, live):
    page.goto(live.entry("/"))
    expect(page.get_by_test_id("join")).to_be_visible()
    expect(page.locator("#party-name")).to_have_text("E2E Party")
    expect(page).to_have_title("E2E Party")


def test_join_dialog_keeps_the_keyboard_inside(page, live):
    page.goto(live.entry("/"))
    dialog = page.get_by_role("dialog", name="Willkommen bei E2E Party")
    expect(dialog).to_be_focused()
    field = page.locator("#vb-join-insta")
    accept = page.get_by_role("button", name=ACCEPT)
    page.keyboard.press("Tab")
    expect(field).to_be_focused()
    page.keyboard.press("Tab")
    expect(accept).to_be_focused()
    page.keyboard.press("Tab")
    expect(field).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(accept).to_be_focused()
    assert vb(page, "vb.sheetOpen()") is True
    # it can't be dismissed: declining means not using the site
    page.keyboard.press("Escape")
    page.mouse.click(5, 5)
    expect(dialog).to_be_visible()
    page.keyboard.press("Tab")
    expect(field).to_be_focused()
    page.keyboard.press("Enter")  # submits the form
    expect(page.get_by_test_id("join")).to_have_count(0)
    assert vb(page, "vb.sheetOpen()") is False
    assert page.js_errors == []


def test_join_errors_say_what_is_wrong_with_the_handle(page, live):
    page.goto(live.entry("/"))
    field = page.locator("#vb-join-insta")
    assert field.get_attribute("maxlength") == "31"  # 30 + a leading @
    field.fill("jürgen")
    page.get_by_role("button", name=ACCEPT).click()
    expect(page.locator(".vb-field-error")).to_contain_text("keine Umlaute")
    expect(field).to_be_focused()
    field.fill("@party.anna")
    page.get_by_role("button", name=ACCEPT).click()
    expect(page.get_by_test_id("join")).to_have_count(0)
    assert live.core.repo.list_users()[0].instagram == "party.anna"
    assert network_noise(page.js_errors) == []


@needs_clipboard
def test_pasted_profile_link_keeps_just_the_handle(page, live):
    """maxlength (31) would cut a pasted link to its first 31 characters."""
    allow_clipboard(page.context)
    page.goto(live.entry("/"))
    field = page.locator("#vb-join-insta")
    page.evaluate("(t) => navigator.clipboard.writeText(t)", "https://www.instagram.com/party.anna/?igsh=abcdefghijklmnop")
    field.focus()
    page.keyboard.press("ControlOrMeta+V")
    expect(field).to_have_value("@party.anna")


def test_second_tab_joining_keeps_its_handle(context, live):
    """Both tabs show the join dialog on a first visit. The first is accepted
    without a handle, the second with one: the handle is stored and the second
    tab says it's the same guest."""
    a = track_errors(context.new_page())
    b = track_errors(context.new_page())
    a.goto(live.entry("/"))
    b.goto(live.entry("/"))
    expect(b.get_by_test_id("join")).to_be_visible()
    accept_consent_in_browser(a)
    accept_consent_in_browser(b, instagram="@tab.b")
    expect(b.get_by_role("status").filter(has_text="Du bist schon dabei als")).to_contain_text("@tab.b")
    expect(b.get_by_test_id("user-chip")).to_have_text("🙂 @tab.b")
    users = live.core.repo.list_users()
    assert len(users) == 1 and users[0].instagram == "tab.b"
    assert a.js_errors == [] and b.js_errors == []


def test_second_tab_with_another_handle_is_told_which_one_counts(context, live):
    a = track_errors(context.new_page())
    b = track_errors(context.new_page())
    a.goto(live.entry("/"))
    b.goto(live.entry("/"))
    expect(b.get_by_test_id("join")).to_be_visible()
    accept_consent_in_browser(a, instagram="@tab.a")
    accept_consent_in_browser(b, instagram="@tab.b")
    toast = b.get_by_role("status").filter(has_text="Du bist schon dabei als")
    expect(toast).to_contain_text("@tab.a")
    expect(toast).to_contain_text("Tipp auf deinen Namen")
    assert live.core.repo.list_users()[0].instagram == "tab.a"


# ------------------------------------------------------ Instagram dialog


def test_instagram_dialog_keyboard_scrim_and_focus(guest_page, live):
    page = guest_page
    chip = page.get_by_test_id("user-chip")
    chip.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="Dein Instagram")
    expect(dialog).to_be_visible()
    field = page.locator("#vb-insta-edit")
    expect(field).to_be_focused()
    assert field.get_attribute("maxlength") == "31"
    save = page.get_by_role("button", name="Speichern")
    cancel = page.get_by_role("button", name="Abbrechen")
    for target in (save, cancel, field):
        page.keyboard.press("Tab")
        expect(target).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(cancel).to_be_focused()
    assert vb(page, "vb.sheetOpen()") is True
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(chip).to_be_focused()
    assert vb(page, "vb.sheetOpen()") is False

    # a tap on the scrim closes it too
    chip.click()
    expect(dialog).to_be_visible()
    settle_dialogs(page)
    page.mouse.click(5, 5)
    expect(dialog).to_have_count(0)

    # the error names the problem
    chip.click()
    field.fill("@müller")
    save.click()
    expect(page.locator(".vb-field-error")).to_contain_text("keine Umlaute")
    expect(field).to_be_focused()
    field.fill("@" + "x" * 40)
    expect(field).to_have_value("@" + "x" * 30)  # maxlength: 30 + the @
    field.fill("@neu.name")
    save.click()
    expect(dialog).to_have_count(0)
    expect(chip).to_have_text("🙂 @neu.name")
    assert network_noise(page.js_errors) == []  # the 400 shows up as a console line


# ------------------------------------------------------------ user chip


def test_user_chip_shows_the_handle_and_ellipsizes(browser, live):
    ctx = new_context(browser, viewport={"width": 320, "height": 640})
    try:
        page = track_errors(ctx.new_page())
        page.goto(live.entry("/"))
        accept_consent_in_browser(page)
        chip = page.get_by_test_id("user-chip")
        name = live.core.repo.list_users()[0].name
        short = name.rsplit(" #", 1)[0]
        expect(chip).to_have_text(f"🙂 {short} · Insta?")
        assert chip.get_attribute("title") == name
        live.core.repo.set_instagram(live.core.repo.list_users()[0].id, "a" * 30)
        page.reload()
        expect(chip).to_have_text("🙂 @" + "a" * 30)
        box = chip.bounding_box()
        assert box is not None and box["x"] + box["width"] <= 320 - 16 + 1
        label = page.locator(".vb-chip-text")
        assert label.evaluate("(el) => el.scrollWidth > el.clientWidth")  # cut with an ellipsis
        assert label.evaluate("(el) => getComputedStyle(el).textOverflow") == "ellipsis"
        assert page.evaluate("() => document.documentElement.scrollWidth") <= 320
        shot(page, "home_chip_long_handle_320")
        assert page.js_errors == []
    finally:
        ctx.close()


# ------------------------------------------------------------- home errors


def test_home_offers_a_reload_when_identify_is_blocked(page, live):
    """A content blocker (or a dead network) drops /api/identify. The page
    can't tell which, so it says neither "offline" nor nothing at all."""
    page.route("**/api/identify", lambda route: route.abort("blockedbyclient"))
    page.goto(live.entry("/"))
    notice = page.get_by_test_id("fatal")
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("Keine Antwort")
    expect(notice).to_contain_text("Blocker")
    expect(notice).not_to_contain_text("Keine Verbindung")
    reload = page.get_by_role("button", name="Neu laden")
    expect(reload).to_be_focused()
    shot(page, "home_identify_blocked")
    page.unroute("**/api/identify")
    reload.click()
    accept_consent_in_browser(page)
    expect(page.locator(".home-tile").first).to_be_visible()
    expect(page.get_by_test_id("fatal")).to_have_count(0)
    assert network_noise(page.js_errors) == []


def test_home_says_offline_when_the_phone_is(page, live):
    page.add_init_script("Object.defineProperty(Navigator.prototype, 'onLine', { configurable: true, get: () => false });")
    page.route("**/api/identify", lambda route: route.abort("internetdisconnected"))
    page.goto(live.entry("/"))
    notice = page.get_by_test_id("fatal")
    expect(notice).to_contain_text("Keine Verbindung")
    expect(notice.get_by_role("button", name="Neu laden")).to_be_visible()
    shot(page, "home_offline")


def test_home_failure_shows_the_api_message_and_retry_after(page, live):
    page.route(
        "**/api/extensions",
        lambda route: route.fulfill(
            status=429,
            headers={"Retry-After": "12"},
            content_type="application/json",
            body='{"error": "rate_limited", "message": "Langsam! Zu viele Anfragen. Warte kurz."}',
        ),
    )
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    notice = page.get_by_test_id("fatal")
    expect(notice).to_contain_text("Langsam! Zu viele Anfragen. Warte kurz (in 12 s nochmal).")


def test_retry_after_reaches_api_and_upload_errors(guest_page, live):
    page = guest_page
    page.route(
        "**/api/x/nothing/**",
        lambda route: route.fulfill(
            status=429,
            headers={"Retry-After": "120"},
            content_type="application/json",
            body='{"error": "rate_limited", "message": "Langsam! Zu viele Anfragen. Warte kurz."}',
        ),
    )
    upload = vb(page, """vb.uploadJpeg('nothing', new Blob(['x'], { type: 'image/jpeg' }))
        .then(() => null, (e) => [e.name, e.status, e.retryAfter, e.message])""")
    assert upload == ["ApiError", 429, 120, "Langsam! Zu viele Anfragen. Warte kurz (in 2 min nochmal)."]
    call = vb(page, "vb.api('/api/x/nothing/stats').then(() => null, (e) => [e.retryAfter, e.message])")
    assert call == [120, "Langsam! Zu viele Anfragen. Warte kurz (in 2 min nochmal)."]


def test_fatal_never_shows_raw_script_errors(guest_page):
    text = vb(guest_page, "vb.fatal(new TypeError('x is undefined')).textContent")
    assert "x is undefined" not in text and "Neu laden" in text
    # a second error doesn't stack another notice
    vb(guest_page, "vb.fatal(new Error('again'))")
    expect(guest_page.get_by_test_id("fatal")).to_have_count(1)


# --------------------------------------------------------------- debug log


def test_debug_log_lets_taps_through_and_folds(page, live):
    page.goto(live.entry("/?debug=1"))
    log = page.locator(".vb-debug-log")
    expect(log).to_be_visible()
    expect(log).to_contain_text("debug on")
    expect(page.get_by_test_id("join")).to_be_visible()
    settle_dialogs(page)
    box = log.bounding_box()
    assert box is not None and box["y"] < 10  # at the top, away from shutters and buttons
    under = page.evaluate(
        "([x, y]) => !!document.elementFromPoint(x, y).closest('.vb-debug')",
        [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
    )
    assert under is False, "the log catches taps"
    shot(page, "join_with_debug_log")
    accept_consent_in_browser(page)
    toggle = page.get_by_test_id("debug-toggle")
    toggle.click()
    expect(log).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    page.reload()
    expect(page.get_by_test_id("debug-toggle")).to_be_visible()
    expect(page.locator(".vb-debug-log")).to_be_hidden()  # stays folded for the session
    page.get_by_test_id("debug-toggle").click()
    expect(page.locator(".vb-debug-log")).to_be_visible()


# ------------------------------------------------------------ small things


def test_in_app_browser_camera_hint_sends_the_guest_out(browser, live):
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Mobile/15E148 Instagram 390.0.0.27.81 (iPhone14,7; iOS 18_5; de_DE; de; scale=3.00; 1170x2532)"
    )
    ctx = new_context(browser, user_agent=ua)
    try:
        page = ctx.new_page()
        page.goto(live.url("/"))  # any page of ours; the gate is fine
        for name in ("NotAllowedError", "SecurityError", "NotFoundError"):
            text = page.evaluate(
                "async (name) => (await import('/static/core/camera.js')).cameraErrorMessage({ name })", name
            )
            assert "Safari oder Chrome" in text, text
            assert "aA" not in text and "Schloss" not in text
    finally:
        ctx.close()
    ctx = new_context(browser)
    try:
        page = ctx.new_page()
        page.goto(live.url("/"))
        text = page.evaluate(
            "async () => (await import('/static/core/camera.js')).cameraErrorMessage({ name: 'NotAllowedError' })"
        )
        assert "verweigert" in text and "Safari oder Chrome" not in text
    finally:
        ctx.close()


def contrast(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    def lum(rgb: tuple[int, int, int]) -> float:
        def chan(c: int) -> float:
            v = c / 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

        r, g, b = (chan(c) for c in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_danger_button_text_is_readable(guest_page):
    colors = guest_page.evaluate("""() => {
      const b = document.createElement('button');
      b.className = 'vb-btn vb-btn--danger';
      b.textContent = 'Löschen';
      document.body.append(b);
      const cs = getComputedStyle(b);
      const out = [cs.color, cs.backgroundColor];
      b.remove();
      return out;
    }""")
    fg, bg = (tuple(int(v) for v in c[c.index("(") + 1:c.index(")")].split(",")[:3]) for c in colors)
    assert contrast(fg, bg) >= 4.5, colors


@pytest.mark.parametrize("path", ["/", "/nowhere"])
def test_gate_and_404_emoji_are_big(page, live, path):
    if path == "/nowhere":
        page.goto(live.entry("/"))
        accept_consent_in_browser(page)
    page.goto(live.url(path))
    emoji = page.locator(".vb-notice-emoji")
    expect(emoji).to_be_visible()
    assert emoji.evaluate("(el) => parseFloat(getComputedStyle(el).fontSize)") >= 60
    shot(page, "gate" if path == "/" else "notfound")
