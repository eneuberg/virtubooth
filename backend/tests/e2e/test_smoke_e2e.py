"""Smoke tests of the built frontend behind the real server (any build that
follows docs/overhaul/contracts/web-serving.md; the UI tests come in wave 2)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from .conftest import LiveServer, wait_until_ready

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
