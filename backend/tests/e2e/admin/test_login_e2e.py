"""Admin login: wrong password, the lockout in words, `next` (never off-site), logout."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from virtubooth.core.ratelimit import RateLimiter

from ...conftest import ADMIN_PASSWORD
from ..conftest import LiveServer, wait_until_ready
from .conftest import errors, wait_live

pytestmark = pytest.mark.e2e


def submit(page: Page, password: str) -> None:
    page.get_by_label("Passwort").fill(password)
    page.get_by_role("button", name="Anmelden").click()


def test_wrong_password_then_in_and_back_to_next(page: Page, live: LiveServer) -> None:
    page.goto(live.url("/admin/manage?tab=gaeste&show=paused"))
    # the server sends the whole page, query included, as next
    assert page.url == live.url("/admin/login?next=/admin/manage%3Ftab%3Dgaeste%26show%3Dpaused")
    wait_until_ready(page)
    submit(page, "definitely-wrong-password")
    expect(page.get_by_test_id("login-error")).to_have_text("Falsches Passwort.")
    expect(page.get_by_label("Passwort")).to_have_attribute("aria-invalid", "true")
    assert page.url.startswith(live.url("/admin/login"))
    submit(page, ADMIN_PASSWORD)
    page.wait_for_url(live.url("/admin/manage?tab=gaeste&show=paused"))
    expect(page.get_by_role("heading", name="Gäste", level=1)).to_be_visible()
    wait_live(page)  # WebKit logs a stream it aborts mid-connect as an error
    # signed in already: the login page forwards right away
    page.goto(live.url("/admin/login?next=/admin/live"))
    page.wait_for_url(live.url("/admin/live"))
    assert errors(page, 401) == []


def test_empty_password_is_said_inline(page: Page, live: LiveServer) -> None:
    page.goto(live.url("/admin/login"))
    wait_until_ready(page)
    page.get_by_role("button", name="Anmelden").click()
    expect(page.get_by_test_id("login-error")).to_have_text("Bitte das Passwort eingeben.")
    assert errors(page) == []


def test_lockout_says_the_wait_in_words(page: Page, live: LiveServer) -> None:
    # the global budget of wrong guesses is used up (normally 20 per 15 minutes)
    live.core.limits.login_failures_global = RateLimiter(1, 3600)
    # through a proxy: requests straight from loopback are exempt from the lock
    page.set_extra_http_headers({"X-Forwarded-For": "198.51.100.7"})
    page.goto(live.url("/admin/login"))
    wait_until_ready(page)
    submit(page, "wrong-1")
    expect(page.get_by_test_id("login-error")).to_have_text(
        re.compile(
            r"^Zu viele Fehlversuche\. Login ist kurz gesperrt\. Versuch es in \d+\u00a0(Minuten?|Stunden?) "
            r"nochmal \(um \d\d:\d\d\)\.$"
        )
    )
    expect(page.get_by_test_id("login-submit")).to_be_disabled()
    assert errors(page, 401, 429) == []


def test_ip_rate_limit_message(page: Page, live: LiveServer) -> None:
    page.goto(live.url("/admin/login"))
    wait_until_ready(page)
    for _ in range(5):
        submit(page, "wrong-password-xyz")
        expect(page.get_by_test_id("login-error")).to_have_text("Falsches Passwort.")
        page.get_by_label("Passwort").fill("")
    submit(page, ADMIN_PASSWORD)
    # one sentence, not the general "Langsam! … Warte kurz. Versuch es … nochmal"
    expect(page.get_by_test_id("login-error")).to_have_text(
        re.compile(
            r"^Zu viele Versuche hintereinander\. Versuch es in \d+\u00a0(Sekunden?|Minuten?) "
            r"nochmal( \(um \d\d:\d\d\))?\.$"
        )
    )
    assert errors(page, 401, 429) == []


@pytest.mark.parametrize(
    "next_url",
    [
        "https://evil.example/",
        "//evil.example/admin/live",
        "/admin/../x",
        "/admin/Live",
        "javascript:alert(1)",
    ],
)
def test_login_never_redirects_off_site(page: Page, live: LiveServer, next_url: str) -> None:
    page.goto(live.url("/admin/login?next=") + next_url.replace("&", "%26"))
    wait_until_ready(page)
    submit(page, ADMIN_PASSWORD)
    page.wait_for_url(live.url("/admin/live"))


def test_login_returns_to_user_page_with_id(page: Page, live: LiveServer) -> None:
    page.goto(live.url("/admin/user?id=1"))
    assert page.url == live.url("/admin/login?next=/admin/user%3Fid%3D1")
    wait_until_ready(page)
    submit(page, ADMIN_PASSWORD)
    page.wait_for_url(live.url("/admin/user?id=1"))
    expect(page.get_by_text("Gast nicht gefunden.")).to_be_visible()
    assert errors(page, 404) == []


def test_logout(admin_page: Page, live: LiveServer) -> None:
    admin_page.goto(live.url("/admin/manage"))
    wait_until_ready(admin_page)
    admin_page.get_by_role("button", name="Abmelden").click()
    admin_page.wait_for_url(live.url("/admin/login"))
    admin_page.goto(live.url("/admin/live"))
    assert admin_page.url.startswith(live.url("/admin/login?next=/admin/live"))
    assert errors(admin_page, 401) == []
