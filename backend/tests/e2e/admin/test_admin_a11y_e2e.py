"""The admin with the keyboard and assistive tech (port of the pre-overhaul
test_admin_a11y_e2e.py): grid navigation, dialogs that keep and return the focus,
accessible names, contrast of the marks, and every page without sideways scrolling."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Browser, Page, expect

from ..conftest import LiveServer, track_errors
from .conftest import (
    DESKTOP_VIEWPORT,
    LANDSCAPE_VIEWPORT,
    PHONE_VIEWPORT,
    Guest,
    admin_context,
    card,
    confirm_dialog,
    errors,
    goto,
    login_api,
    no_horizontal_scroll,
    wait_live,
    wait_until,
)

pytestmark = pytest.mark.e2e


def focused_photo(page: Page) -> str | None:
    return page.evaluate(
        "() => { const e = document.activeElement && document.activeElement.closest('[data-photo-id]');"
        " return e ? e.dataset.photoId : null; }"
    )


def focus_inside(page: Page, selector: str) -> bool:
    return bool(page.evaluate("(s) => !!document.activeElement.closest(s)", selector))


def test_contact_sheet_with_the_keyboard_only(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    g = guests()
    ids = [g.upload() for _ in range(10)]  # newest first on the sheet: ids[9] … ids[0]
    goto(page, live, "/admin/manage")
    wait_live(page)
    page.get_by_test_id("select-all").focus()
    page.keyboard.press("Tab")
    assert focused_photo(page) == ids[9]
    page.keyboard.press("ArrowRight")
    assert focused_photo(page) == ids[8]
    page.keyboard.press("ArrowDown")  # one row further: 7 columns at 1440
    assert focused_photo(page) not in (ids[8], ids[7])
    page.keyboard.press("ArrowUp")
    assert focused_photo(page) == ids[8]

    # Space selects, X hides, Entf asks
    page.keyboard.press("Space")
    expect(page.get_by_test_id("bulk-count")).to_have_text("1 ausgewählt")
    page.keyboard.press("x")
    expect(card(page, ids[8])).to_have_attribute("data-hidden", "true")
    page.keyboard.press("Delete")
    dialog = confirm_dialog(page)
    expect(dialog).to_contain_text("Bier 0009")
    expect(dialog.get_by_role("button", name="Abbrechen")).to_be_focused()
    for shift in (False, True):
        for _ in range(3):
            page.keyboard.press("Shift+Tab" if shift else "Tab")
            assert focus_inside(page, "[data-testid=confirm]")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    wait_until(lambda: focused_photo(page) == ids[8], what="focus back on the frame")
    assert live.core.repos.photos.get(ids[8]) is not None

    # Esc clears the selection (while one exists, Enter and clicks select); then Enter
    # opens the inspector. Entf deletes after asking, the focus moves on.
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("bulkbar")).to_have_count(0)
    page.keyboard.press("Enter")
    expect(
        page.get_by_test_id("inspector").get_by_role("heading", name="Bier 0009")
    ).to_be_visible()
    card(page, ids[8]).focus()
    page.keyboard.press("Delete")
    confirm_dialog(page).get_by_role("button", name="Endgültig löschen").click()
    expect(card(page, ids[8])).to_have_count(0)
    wait_until(lambda: focused_photo(page) == ids[7], what="focus on the neighbour")
    assert errors(page) == []


def test_ban_sheet_keeps_and_returns_the_focus(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    g = guests()
    g.upload()
    goto(page, live, f"/admin/user?id={g.id}")
    ban = page.get_by_test_id("ban")
    ban.focus()
    page.keyboard.press("Enter")
    sheet = page.get_by_role("dialog", name=f"„{g.name}“ sperren?")
    expect(sheet).to_be_visible()
    expect(sheet.get_by_role("button", name="Abbrechen")).to_be_focused()
    for shift in (False, True):
        for _ in range(6):
            page.keyboard.press("Shift+Tab" if shift else "Tab")
            assert focus_inside(page, "[data-testid=ban-sheet]")
    # the page behind is out of reach for assistive tech
    assert page.evaluate(
        "() => document.querySelector('main').closest('[aria-hidden=true], [inert]') !== null"
    )
    page.keyboard.press("Escape")
    expect(sheet).to_have_count(0)
    expect(ban).to_be_focused()
    user = live.core.repos.users.get(g.id)
    assert user is not None and not user.banned

    # confirmed: the status line says the new state and gets the focus
    page.keyboard.press("Enter")
    page.get_by_test_id("ban-confirm").click()
    expect(page.get_by_test_id("user-status")).to_have_attribute("data-state", "banned")
    expect(page.get_by_test_id("user-status")).to_be_focused()
    assert errors(page) == []


def test_viewer_focus_and_keys(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    g = guests(instagram="key.board")
    older, newer = g.upload(), g.upload()
    goto(page, live, "/admin/live")
    button = card(page, newer).locator("figure button").first
    button.focus()
    page.keyboard.press("Enter")
    viewer = page.get_by_role("dialog", name="Foto Bier 0002")
    expect(viewer).to_be_visible()
    expect(viewer.get_by_test_id("lightbox-close")).to_be_focused()
    for _ in range(8):
        page.keyboard.press("Tab")
        assert focus_inside(page, "[data-testid=lightbox]")
    # hide with the keyboard: the focus stays on the button
    toggle = viewer.get_by_test_id("toggle")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(toggle).to_have_text("Einblenden")
    expect(toggle).to_be_focused()
    page.keyboard.press("ArrowRight")  # the older photo
    expect(page.get_by_role("dialog", name="Foto Bier 0001")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("lightbox")).to_have_count(0)
    # back on the photo shown last
    expect(card(page, older).locator("figure button").first).to_be_focused()
    assert errors(page) == []


def test_live_grid_arrows_and_upload_sheet_focus(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    g = guests()
    ids = [g.upload() for _ in range(4)]
    goto(admin_page, live, "/admin/live")
    card(admin_page, ids[3]).locator("figure button").first.focus()
    admin_page.keyboard.press("ArrowRight")
    assert focused_photo(admin_page) == ids[2]
    admin_page.keyboard.press("ArrowDown")  # two columns on a phone
    assert focused_photo(admin_page) == ids[0]
    pill = admin_page.get_by_test_id("uploads-chip")
    pill.focus()
    admin_page.keyboard.press("Enter")
    sheet = admin_page.get_by_role("dialog", name="Hochladen")
    expect(sheet).to_be_visible()
    for _ in range(5):
        admin_page.keyboard.press("Tab")
        assert focus_inside(admin_page, "[data-testid=uploads-sheet]")
    admin_page.keyboard.press("Escape")
    expect(sheet).to_have_count(0)
    expect(pill).to_be_focused()
    assert errors(admin_page) == []


def test_filters_have_names_on_a_phone(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    guests().upload()
    goto(admin_page, live, "/admin/manage")
    expect(admin_page.get_by_role("button", name=re.compile("Aktivität"))).to_be_visible()
    expect(admin_page.get_by_role("button", name=re.compile(r"\bGast$"))).to_be_visible()
    expect(admin_page.get_by_role("radiogroup", name="Sichtbarkeit")).to_be_visible()
    expect(admin_page.get_by_role("grid", name="Kontaktbogen")).to_be_visible()
    assert errors(admin_page) == []


CONTRAST = """(el) => {
  const parse = (c) => { const m = c.match(/[\\d.]+/g).map(Number); return [m[0], m[1], m[2], m.length > 3 ? m[3] : 1]; };
  const over = (top, under) => top.slice(0, 3).map((v, i) => v * top[3] + under[i] * (1 - top[3])).concat(1);
  const layers = [];
  for (let n = el; n; n = n.parentElement) layers.push(parse(getComputedStyle(n).backgroundColor));
  let bg = parse(getComputedStyle(document.body).backgroundColor);
  for (const layer of layers.reverse()) bg = over(layer, bg);
  const fg = over(parse(getComputedStyle(el).color), bg);
  const lum = (c) => { const [r, g, b] = c.slice(0, 3).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
                       return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}"""


def test_marks_and_badges_contrast(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    g = guests()
    hidden = g.upload()
    g.upload()
    live.core.services.moderation.hide_photo(hidden, actor="pytest")
    twin_source = guests(fp=9)
    live.core.services.moderation.ban_user(
        twin_source.id, reason="x", fingerprint=True, actor="pytest"
    )
    guests(fp=9)  # automatically banned
    paused = guests()
    live.core.services.upload_controls.set_user_paused(paused.id, True, actor="pytest")
    checks: dict[str, str] = {}
    goto(page, live, "/admin/manage")
    checks["manage: hidden caption"] = (
        card(page, hidden).get_by_text("Ausgeblendet").evaluate(CONTRAST)
    )
    checks["manage: delete button"] = page.get_by_test_id("select-all").evaluate(CONTRAST)
    goto(page, live, "/admin/manage?tab=gaeste")
    for testid in ("ban-badge", "auto-ban", "paused-badge"):
        badge = page.get_by_test_id(testid).first.locator("span").first
        checks[f"guests: {testid}"] = badge.evaluate(CONTRAST)
    goto(page, live, "/admin/live")
    checks["live: hidden caption"] = (
        card(page, hidden).get_by_text("Ausgeblendet").evaluate(CONTRAST)
    )
    checks["live: connection"] = page.get_by_test_id("conn").evaluate(CONTRAST)
    for name, ratio in checks.items():
        assert float(ratio) >= 4.5, f"{name}: {float(ratio):.2f}"
    assert errors(page) == []


PAGES = [
    "/admin/live",
    "/admin/manage",
    "/admin/manage?tab=gaeste",
    "/admin/manage?tab=instagram",
    "/admin/manage?tab=sperren",
    "/admin/manage?tab=protokoll",
    "/admin/manage?tab=qr",
    "/admin/manage?tab=plakat",
    "/admin/manage?tab=export",
    "/admin/manage?tab=einstellungen",
    "/admin/user?id={id}",
]


@pytest.mark.parametrize(
    "viewport",
    [PHONE_VIEWPORT, LANDSCAPE_VIEWPORT, DESKTOP_VIEWPORT],
    ids=["phone", "landscape", "desktop"],
)
def test_no_sideways_scrolling(
    browser: Browser, live: LiveServer, guests: Callable[..., Guest], viewport: dict[str, int]
) -> None:
    g = guests(instagram="a.very.long.handle.for_layout1")
    g.upload()
    live.core.services.moderation.ban_user(
        guests().id, reason="ein sehr langer Grund " * 4, actor="pytest"
    )
    ctx = admin_context(browser, viewport)
    try:
        page = track_errors(ctx.new_page())
        # the login page first: signed in, it forwards to the live screen
        goto(page, live, "/admin/login")
        wait_until(
            lambda: no_horizontal_scroll(page), timeout=4, what="no sideways scroll on the login"
        )
        login_api(page, live)
        for path in PAGES:
            goto(page, live, path.format(id=g.id))
            # leave only once the page is in (its event stream): WebKit logs a stream it
            # aborts mid-connect as an error
            wait_live(page)
            # the settled page; while data loads a skeleton may be wider for a moment
            wait_until(
                lambda: no_horizontal_scroll(page), timeout=4, what=f"no sideways scroll on {path}"
            )
        assert errors(page) == []
    finally:
        ctx.close()
