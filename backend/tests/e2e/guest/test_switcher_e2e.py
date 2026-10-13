"""The activity switcher (the title of an activity's top bar) and the guest pass
inside activities: the other activities and Start, client-side navigation."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import LiveServer, accept_consent_in_browser, settle_dialogs, shot
from .conftest import only_user, reload

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


@pytest.mark.parametrize("ext", ["beer", "booth"])
def test_a_long_pseudonym_leaves_the_title_whole(make_page, live: LiveServer, ext: str):
    """The longest pseudonyms (adjective + "Erdmännchen") on a small phone: the guest
    pass shortens the name, the activity title stays readable ("Foto…" before)."""
    page = make_page("small")
    page.goto(live.entry(f"/x/{ext}/"))
    accept_consent_in_browser(page)
    with live.core.db.tx() as c:
        c.execute(
            "UPDATE users SET name=? WHERE id=?",
            ("Glitzerndes Erdmännchen #123", only_user(live).id),
        )
    reload(page)
    menu = page.get_by_test_id("activity-menu")
    expect(menu).to_contain_text("Beer Cam" if ext == "beer" else "Fotobox")
    passed = page.get_by_test_id("guest-pass")
    expect(passed).to_contain_text("Glitzerndes")
    title_cut = menu.locator("span.truncate").evaluate("(el) => el.scrollWidth > el.clientWidth")
    assert not title_cut
    box = passed.bounding_box()
    assert box is not None and box["x"] + box["width"] <= 360
    shot(page, f"long_pseudonym_{ext}")
    assert page.js_errors == []  # type: ignore[attr-defined]
