"""Admin screens with the keyboard and assistive tech: tabs (roving tabindex),
the confirm dialog and the lightbox (focus in, Tab stays inside, focus back
on close, accessible names), names of controls, contrast of admin colours."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from ..conftest import fp

# the admin e2e module's server setup: a "snap" extension, HTTP guests, a PC page
from .test_admin_e2e import card, desktop_page, e2e_extensions, guests  # noqa: F401

pytestmark = pytest.mark.e2e

TABS = ["fotos", "gaeste", "instagram", "sperren", "protokoll"]


def focused(page: Page) -> str:
    """id or data-testid of the focused element ('' for <body>)"""
    return page.evaluate(
        "() => { const e = document.activeElement;"
        " return e === document.body ? '' : (e.id || e.dataset.testid || e.tagName); }"
    )


def focus_inside(page: Page, testid: str) -> bool:
    return page.evaluate(
        "(t) => !!document.activeElement.closest(`[data-testid='${t}']`)", testid
    )


def press_tab(page: Page, times: int, *, shift: bool = False) -> None:
    for _ in range(times):
        page.keyboard.press("Shift+Tab" if shift else "Tab")


# ------------------------------------------------------------------- tabs


def test_tabs_move_with_arrow_keys(desktop_page, live):
    page = desktop_page
    page.goto(live.url("/admin/manage"))
    expect(page.get_by_role("tab", name="📸 Fotos")).to_have_attribute("aria-selected", "true")
    # roving tabindex: only the selected tab is in the Tab order
    assert [page.get_attribute(f"#tab-{t}", "tabindex") for t in TABS] == ["0", "-1", "-1", "-1", "-1"]
    page.focus("#tab-fotos")

    page.keyboard.press("ArrowRight")
    assert focused(page) == "tab-gaeste"
    expect(page.locator("#tab-gaeste")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#panel-gaeste")).to_be_visible()
    expect(page.locator("#panel-fotos")).to_be_hidden()
    assert "tab=gaeste" in page.url
    assert [page.get_attribute(f"#tab-{t}", "tabindex") for t in TABS] == ["-1", "0", "-1", "-1", "-1"]

    page.keyboard.press("End")
    assert focused(page) == "tab-protokoll"
    expect(page.locator("#panel-protokoll")).to_be_visible()
    page.keyboard.press("ArrowRight")  # wraps around
    assert focused(page) == "tab-fotos"
    page.keyboard.press("ArrowLeft")
    assert focused(page) == "tab-protokoll"
    page.keyboard.press("Home")
    assert focused(page) == "tab-fotos"
    expect(page.locator("#tab-fotos")).to_have_attribute("aria-selected", "true")
    # Tab leaves the tab list into the shown panel
    page.keyboard.press("Tab")
    assert focused(page) == "panel-fotos"
    assert page.js_errors == []


# ------------------------------------------------------------ confirm dialog


def test_confirm_dialog_keeps_and_returns_focus(desktop_page, live, guests):
    page = desktop_page
    g = guests()
    g.upload()
    page.goto(live.url(f"/admin/user?id={g.user.id}"))
    ban = page.get_by_test_id("ban")
    ban.focus()
    page.keyboard.press("Enter")

    dialog = page.get_by_role("alertdialog", name=f"{g.user.name} sperren?")
    expect(dialog).to_be_visible()
    expect(dialog).to_have_attribute("aria-modal", "true")
    expect(dialog).to_have_accessible_description(re.compile("sichtbare Foto wird versteckt"))
    # destructive: Enter would cancel, not ban
    assert focused(page) == "confirm-cancel"
    for shift in (False, True):
        for _ in range(4):
            page.keyboard.press("Shift+Tab" if shift else "Tab")
            assert focus_inside(page, "confirm"), focused(page)
    # the page behind is out of reach while it is open
    assert page.evaluate("() => document.querySelector('main').inert")
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("confirm")).to_have_count(0)
    assert focused(page) == "ban"
    assert not page.evaluate("() => document.querySelector('main').inert")
    assert not live.core.repo.get_user(g.user.id).banned

    # confirmed: the page is rebuilt; focus lands on the ban panel, not on <body>
    page.keyboard.press("Enter")
    page.get_by_test_id("confirm-ok").click()
    expect(page.get_by_test_id("user-status")).to_have_text("🚫 GESPERRT")
    expect(page.get_by_test_id("ban-panel").get_by_role("heading")).to_be_focused()
    assert page.js_errors == []


# ---------------------------------------------------------------- lightbox


def test_lightbox_focus_and_keyboard(desktop_page, live, guests):
    page = desktop_page
    g = guests(instagram="key.board")
    older, newer = g.upload(), g.upload()
    page.goto(live.url("/admin/manage"))
    thumb = card(page, newer).get_by_test_id("thumb")
    thumb.focus()
    page.keyboard.press("Enter")

    lightbox = page.get_by_role("dialog", name="Foto 📷 Schnappschuss #2")
    expect(lightbox).to_be_visible()
    expect(lightbox).to_have_attribute("aria-modal", "true")
    assert focused(page) == "lightbox-close"
    for _ in range(12):
        page.keyboard.press("Tab")
        assert focus_inside(page, "lightbox"), focused(page)
    page.keyboard.press("Shift+Tab")
    assert focus_inside(page, "lightbox")

    # take it down with the keyboard: focus stays on the (rebuilt) toggle
    toggle = lightbox.get_by_test_id("toggle")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(toggle).to_have_text("👁 Wieder zeigen")
    expect(toggle).to_be_focused()
    assert live.core.repo.get_photo(newer).hidden

    page.keyboard.press("ArrowRight")  # the older photo
    expect(page.get_by_role("dialog", name="Foto 📷 Schnappschuss #1")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("lightbox")).to_have_count(0)
    # back on the thumbnail of the photo shown last
    expect(card(page, older).get_by_test_id("thumb")).to_be_focused()
    assert page.js_errors == []


def test_delete_from_lightbox_asks_on_top(desktop_page, live, guests):
    page = desktop_page
    g = guests()
    first, doomed, last = g.upload(), g.upload(), g.upload()
    page.goto(live.url("/admin/manage"))
    card(page, doomed).get_by_test_id("thumb").click()
    page.get_by_test_id("lightbox-delete").click()
    ok = page.get_by_test_id("confirm-ok")
    expect(ok).to_be_visible()
    # the question is in front of the lightbox, not hidden behind it
    on_top = ok.evaluate(
        """(el) => { const r = el.getBoundingClientRect();
            return el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); }"""
    )
    assert on_top
    ok.click()
    expect(page.get_by_test_id("lightbox")).to_have_count(0)
    expect(card(page, doomed)).to_have_count(0)
    # the API answer and the event both report the deletion: one step back, not two
    page.wait_for_timeout(300)
    assert page.url == live.url("/admin/manage")
    assert live.core.repo.get_photo(doomed) is None
    # focus goes to the photo that took its place, not to <body>
    expect(card(page, first).get_by_test_id("thumb")).to_be_focused()
    assert live.core.repo.get_photo(last) is not None
    assert page.js_errors == []


def test_deleting_a_tile_moves_focus_to_its_neighbour(desktop_page, live, guests):
    page = desktop_page
    g = guests()
    first, doomed = g.upload(), g.upload()
    page.goto(live.url("/admin/manage"))
    card(page, doomed).get_by_test_id("delete").focus()
    page.keyboard.press("Enter")
    page.get_by_test_id("confirm-ok").click()
    expect(card(page, doomed)).to_have_count(0)
    expect(card(page, first).get_by_test_id("thumb")).to_be_focused()
    assert page.js_errors == []


# ------------------------------------------------------- names and colours


def test_filter_selects_have_names_on_a_phone(admin_page, live, guests):
    guests().upload()
    admin_page.goto(live.url("/admin/manage"))
    # the visible field labels are hidden on a phone
    expect(admin_page.get_by_role("combobox", name="Aktivität")).to_be_visible()
    expect(admin_page.get_by_role("combobox", name="Gast")).to_be_visible()


CONTRAST = """(el) => {
  const parse = (c) => { const m = c.match(/[\\d.]+/g).map(Number); return [m[0], m[1], m[2], m.length > 3 ? m[3] : 1]; };
  const over = (top, under) => top.slice(0, 3).map((v, i) => v * top[3] + under[i] * (1 - top[3])).concat(1);
  // background: the element's and its ancestors' colours over the page colour
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


def test_admin_danger_colours_contrast(desktop_page, live, guests):
    """The admin's own red/orange styles (core's .vb-btn--danger is core's)."""
    page = desktop_page
    g = guests()
    hidden, banned_hidden = g.upload(), g.upload()
    repo = live.core.repo
    repo.hide_photo(hidden, "pytest")
    page.goto(live.url("/admin/manage"))
    checks = {
        "hidden badge": card(page, hidden).get_by_test_id("status"),
        "take-down button": card(page, banned_hidden).get_by_test_id("toggle"),
        "tile delete": card(page, hidden).get_by_test_id("delete"),
    }
    for name, locator in checks.items():
        ratio = locator.evaluate(CONTRAST)
        assert ratio >= 4.5, f"{name}: {ratio:.2f}"
    repo.ban_user(g.user.id, "x", "pytest")
    repo.ban_fingerprint(fp(1)["hash"], "x", "pytest", g.user.id)
    assert guests(fp_n=1).state == "banned"  # auto-banned
    page.goto(live.url("/admin/manage?tab=sperren"))
    rows = page.locator("[data-testid=banned-user-row]")
    expect(rows).to_have_count(2)
    for badge in (rows.get_by_test_id("auto-ban"), rows.locator(".adm-badge--ban:not(.adm-badge--auto)")):
        expect(badge).to_have_count(1)
        assert badge.evaluate(CONTRAST) >= 4.5
    page.goto(live.url(f"/admin/user?id={g.user.id}"))
    status = card(page, banned_hidden).get_by_test_id("status")
    expect(status).to_have_text("🙈 Versteckt (Sperre)")
    assert status.evaluate(CONTRAST) >= 4.5
    assert page.js_errors == []
