"""The activity switcher (the title of an activity's top bar) and the guest pass
inside activities: the other activities and Start, client-side navigation."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import LiveServer, settle_dialogs, shot

pytestmark = pytest.mark.e2e


def test_switcher_lists_the_other_activities_and_start(guest_page: Page, live: LiveServer):
    page = guest_page
    page.get_by_test_id("tile-beer").click()
    page.wait_for_url(live.url("/x/beer/"))
    page.evaluate("() => { window.__sameDocument = true; }")
    menu = page.get_by_test_id("activity-menu")
    expect(menu).to_contain_text("Beer Cam")
    expect(page.get_by_test_id("guest-pass")).to_be_visible()  # compact, top right
    menu.click()
    items = page.get_by_role("menuitem")
    expect(items).to_have_count(3)  # here (Beer Cam), Fotobox, Start
    expect(page.get_by_role("menuitem", name="Beer Cam")).to_be_disabled()
    settle_dialogs(page)
    shot(page, "activity_menu")
    page.get_by_role("menuitem", name="Fotobox").click()
    page.wait_for_url(live.url("/x/booth/"))
    expect(page.get_by_test_id("activity-menu")).to_contain_text("Fotobox")
    assert page.evaluate("() => window.__sameDocument === true")  # no page load in between
    # keyboard: open, arrow to Start, Enter
    page.get_by_test_id("activity-menu").focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("menu")).to_be_visible()
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.wait_for_url(live.url("/"))
    expect(page.get_by_test_id("start")).to_be_visible()
    assert page.js_errors == []  # type: ignore[attr-defined]
