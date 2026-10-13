"""Smoke tests of the built frontend behind the real server (any build that
follows docs/overhaul/contracts/web-serving.md; the UI tests come in wave 2)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import (
    ADMIN_PASSWORD,
    LiveServer,
    accept_consent_in_browser,
    new_context,
    track_errors,
    wait_until_ready,
)

pytestmark = pytest.mark.e2e


def errors_besides_the_page_404(page: Page, url: str) -> list[str]:
    """The browser logs the 404 of the page itself; anything else is a real error."""
    expected = f"status of 404 (Not Found) @ {url}"
    return [e for e in page.js_errors if not e.endswith(expected)]  # type: ignore[attr-defined]


def test_gate_without_token(page: Page, live: LiveServer):
    response = page.goto(live.url("/"))
    assert response is not None and response.status == 404
    expect(page.locator("html")).to_have_attribute("data-vb-mode", "gate")
    assert errors_besides_the_page_404(page, live.url("/")) == []


def test_not_found_page_with_access(page: Page, live: LiveServer):
    page.goto(live.entry("/"))
    # let the app's first requests finish: WebKit logs a request that a navigation
    # aborts as an error ("… due to access control checks")
    page.wait_for_load_state("networkidle")
    response = page.goto(live.url("/nowhere"))
    assert response is not None and response.status == 404
    expect(page.locator("html")).to_have_attribute("data-vb-mode", "notfound")
    assert errors_besides_the_page_404(page, live.url("/nowhere")) == []


def test_guest_app_boots_under_the_csp(page: Page, live: LiveServer):
    response = page.goto(live.entry("/"))
    assert response is not None and response.ok
    assert page.url == live.url("/")  # the token moved into a cookie
    wait_until_ready(page)
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_admin_app_boots_under_the_csp(page: Page, live: LiveServer):
    response = page.goto(live.url("/admin/login"))
    assert response is not None and response.ok
    wait_until_ready(page)
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_admin_pages_redirect_to_login(page: Page, live: LiveServer):
    page.goto(live.url("/admin/user?id=5"))
    assert page.url.startswith(live.url("/admin/login?next="))
    assert page.js_errors == []  # type: ignore[attr-defined]


@pytest.mark.parametrize("device", ["phone", "desktop"])
def test_an_english_browser_gets_the_german_app(browser, live: LiveServer, device: str):
    """Guests' phones are not all German. React Aria picks its locale from the browser and
    crashed with an English one (only de-DE strings are bundled), so every app root pins
    de-DE (UiProvider). Guest app with its join sheet and Start, admin login and live."""
    ctx = new_context(browser, device, locale="en-US")
    try:
        page = track_errors(ctx.new_page())
        page.goto(live.entry("/"))
        accept_consent_in_browser(page)
        expect(page.get_by_test_id("start")).to_be_visible()
        assert page.evaluate("() => navigator.language") == "en-US"
        expect(page.locator("html")).to_have_attribute("lang", "de")
        page.goto(live.url("/admin/login"))
        wait_until_ready(page)
        expect(page.get_by_role("button", name="Anmelden")).to_be_visible()
        page.get_by_label("Passwort").fill(ADMIN_PASSWORD)
        page.get_by_role("button", name="Anmelden").click()
        page.wait_for_url(live.url("/admin/live"))
        wait_until_ready(page)
        expect(page.get_by_test_id("conn")).to_have_attribute("data-state", "live")
        assert page.js_errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()
