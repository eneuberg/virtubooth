"""The static gate page (gate.html, HTTP 404) for no access and for unknown pages,
with and without JavaScript, and the in-app browser hints (gate and Start).
Ported from e2e_legacy/test_core_e2e.py (gate) and test_core_ui_e2e.py
(gate/404 pages, in-app browser hint)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import LiveServer, accept_consent_in_browser, shot
from .conftest import INSTAGRAM_UA, no_horizontal_scroll, reload

pytestmark = pytest.mark.e2e


def errors_besides_the_page_404(page: Page, url: str) -> list[str]:
    """The browser logs the 404 of the page itself; anything else is a real error."""
    return [e for e in page.js_errors if not e.endswith(f"status of 404 (Not Found) @ {url}")]  # type: ignore[attr-defined]


def test_gate_without_access(page: Page, live: LiveServer):
    response = page.goto(live.url("/"))
    assert response is not None and response.status == 404
    expect(page.locator("html")).to_have_attribute("data-vb-mode", "gate")
    gate = page.get_by_test_id("gate")
    expect(gate).to_be_visible()
    expect(gate.get_by_role("heading", level=1)).to_have_text("Scan den QR-Code")
    expect(page.get_by_test_id("notfound")).to_be_hidden()
    expect(page.get_by_test_id("gate-app-hint")).to_be_hidden()  # a normal browser needs no hint
    assert no_horizontal_scroll(page)
    assert errors_besides_the_page_404(page, live.url("/")) == []


def test_gate_for_a_wrong_token_and_a_deep_link(page: Page, live: LiveServer):
    response = page.goto(live.url("/x/beer/?t=not-the-party-token-0000"))
    assert response is not None and response.status == 404
    expect(page.get_by_test_id("gate")).to_be_visible()
    assert not any(c["name"] == "vb_access" for c in page.context.cookies())


def test_not_found_with_access_leads_back_to_start(page: Page, live: LiveServer):
    page.goto(live.entry("/"))
    response = page.goto(live.url("/nowhere"))
    assert response is not None and response.status == 404
    expect(page.locator("html")).to_have_attribute("data-vb-mode", "notfound")
    notfound = page.get_by_test_id("notfound")
    expect(notfound).to_be_visible()
    expect(notfound.get_by_role("heading", level=1)).to_have_text("Hier ist nichts.")
    expect(page.get_by_test_id("gate")).to_be_hidden()
    assert errors_besides_the_page_404(page, live.url("/nowhere")) == []
    notfound.get_by_role("link", name="Zum Start").click()
    page.wait_for_url(live.url("/"))
    accept_consent_in_browser(page)
    expect(page.get_by_test_id("start")).to_be_visible()


def test_gate_works_without_javascript(browser, live: LiveServer):
    ctx = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 844})
    try:
        page = ctx.new_page()
        page.goto(live.url("/"))
        expect(page.get_by_test_id("gate")).to_be_visible()
        expect(page.get_by_test_id("notfound")).to_be_hidden()
        page.goto(live.entry("/"))  # the cookie comes with the 303, no script involved
        page.goto(live.url("/nowhere"))
        expect(page.get_by_test_id("notfound")).to_be_visible()
        expect(page.get_by_test_id("gate")).to_be_hidden()
    finally:
        ctx.close()


def test_gate_tells_in_app_browsers_what_to_do(make_page, live: LiveServer):
    page = make_page(user_agent=INSTAGRAM_UA)
    page.goto(live.url("/"))
    hint = page.get_by_test_id("gate-app-hint")
    expect(hint).to_be_visible()
    expect(hint).to_contain_text("Browser von Instagram")
    expect(hint).to_contain_text("Kamera-App")
    shot(page, "gate_instagram")
    assert errors_besides_the_page_404(page, live.url("/")) == []


def test_start_tells_in_app_browsers_what_to_do(make_page, live: LiveServer):
    page = make_page(user_agent=INSTAGRAM_UA)
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    hint = page.get_by_test_id("inapp-hint")
    expect(hint).to_be_visible()
    expect(hint).to_contain_text("Browser von Instagram")
    expect(hint).to_contain_text("scanne den QR-Code damit")
    shot(page, "start_instagram")
    hint.get_by_role("button", name="Verstanden").click()
    expect(hint).to_have_count(0)
    reload(page)
    expect(page.get_by_test_id("start")).to_be_visible()
    expect(page.get_by_test_id("inapp-hint")).to_have_count(0)  # not again in this tab
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_no_in_app_hint_in_a_real_browser(guest_page: Page):
    expect(guest_page.get_by_test_id("start")).to_be_visible()
    expect(guest_page.get_by_test_id("inapp-hint")).to_have_count(0)
