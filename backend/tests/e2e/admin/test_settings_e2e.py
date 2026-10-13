"""Einstellungen: the event name reaches the guests, the password change logs out the
other admin devices (and only the new password opens the admin)."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Browser, Page, expect

from ...conftest import ADMIN_PASSWORD
from ..conftest import LiveServer, join_via_api, new_context, shot, track_errors
from .conftest import (
    DESKTOP_VIEWPORT,
    admin_context,
    errors,
    goto,
    login_api,
    no_horizontal_scroll,
    toast,
    wait_live,
)

pytestmark = pytest.mark.e2e

NEW_PASSWORD = "e2e-brand-new-password-2026"


def open_settings(page: Page, live: LiveServer) -> None:
    goto(page, live, "/admin/manage?tab=einstellungen")
    expect(page.get_by_role("heading", name="Einstellungen", level=1)).to_be_visible()


def test_the_event_name_reaches_the_guests_and_goes_back(
    desktop_page: Page, browser: Browser, live: LiveServer
) -> None:
    admin = desktop_page
    goto(admin, live, "/admin/manage")
    # not a section of the list: a link in the sidebar's footer
    admin.get_by_test_id("settings-link").click()
    expect(admin.get_by_role("heading", name="Einstellungen", level=1)).to_be_visible()
    assert admin.url.endswith("/admin/manage?tab=einstellungen")

    field = admin.get_by_label("Name des Events")
    expect(field).to_have_value("E2E Party")
    expect(admin.get_by_role("heading", name="Fotobox-Filter")).to_be_visible()
    shot(admin, "admin-settings-desktop")
    expect(admin.get_by_test_id("event-name-reset")).to_have_count(0)
    field.fill("  Gartenfest   2026 ")
    admin.get_by_role("button", name="Speichern").click()
    expect(toast(admin)).to_have_text("Eventname gespeichert.")
    expect(field).to_have_value("Gartenfest 2026")
    assert live.core.services.host_settings.event_name() == "Gartenfest 2026"

    ctx = new_context(browser)
    guest = track_errors(ctx.new_page())
    join_via_api(guest, live)  # ends on Start, reloaded
    expect(guest.get_by_role("heading", level=1)).to_have_text("Gartenfest 2026")

    reset = admin.get_by_test_id("event-name-reset")
    expect(reset).to_have_text("Zurück zu „E2E Party“")
    reset.click()
    expect(toast(admin)).to_have_text("Eventname zurückgesetzt.")
    expect(field).to_have_value("E2E Party")
    expect(reset).to_have_count(0)

    guest.reload()
    expect(guest.get_by_role("heading", level=1)).to_have_text("E2E Party")
    assert guest.js_errors == []  # type: ignore[attr-defined]
    ctx.close()
    assert errors(admin) == []


def test_password_change_logs_out_the_other_admins(
    desktop_page: Page, browser: Browser, live: LiveServer
) -> None:
    admin = desktop_page
    other_ctx = admin_context(browser, DESKTOP_VIEWPORT)
    other = track_errors(other_ctx.new_page())
    login_api(other, live)
    goto(other, live, "/admin/manage")
    wait_live(other)

    open_settings(admin, live)
    card = admin.get_by_test_id("settings-password")
    expect(card.get_by_test_id("password-source")).to_have_text(
        "Gerade gilt das Passwort aus VB_ADMIN_PASSWORD."
    )
    card.get_by_label("Aktuelles Passwort").fill(ADMIN_PASSWORD)
    card.get_by_label("Neues Passwort", exact=True).fill(NEW_PASSWORD)
    card.get_by_label("Neues Passwort wiederholen").fill(NEW_PASSWORD + "x")
    card.get_by_role("button", name="Passwort ändern").click()
    expect(card.get_by_text("Die beiden neuen Passwörter sind nicht gleich.")).to_be_visible()

    card.get_by_label("Neues Passwort wiederholen").fill(NEW_PASSWORD)
    card.get_by_role("button", name="Passwort ändern").click()
    expect(toast(admin)).to_have_text("Passwort geändert. 1 anderes Gerät abgemeldet.")
    expect(card.get_by_label("Aktuelles Passwort")).to_have_value("")
    expect(card.get_by_test_id("password-source")).to_have_text(
        re.compile(
            r"^Hier geändert am \d\d\.\d\d\.\d{4}, \d\d:\d\d\. VB_ADMIN_PASSWORD gilt nicht mehr\.$"
        )
    )

    # the other device: its live stream ends at once, and it goes to the login page
    other.wait_for_url(re.compile(r"/admin/login"), timeout=10_000)
    # this one stays signed in
    admin.reload()
    expect(admin.get_by_role("heading", name="Einstellungen", level=1)).to_be_visible()

    other.wait_for_load_state()
    other.get_by_label("Passwort").fill(ADMIN_PASSWORD)
    other.get_by_role("button", name="Anmelden").click()
    expect(other.get_by_test_id("login-error")).to_have_text("Falsches Passwort.")
    other.get_by_label("Passwort").fill(NEW_PASSWORD)
    other.get_by_role("button", name="Anmelden").click()
    other.wait_for_url(re.compile(r"/admin/manage"))
    wait_live(other)
    # the refused stream (401) is logged by the browser: expected here, nothing else
    assert [e for e in errors(other, 401) if "/api/admin/events" not in e] == []
    other_ctx.close()
    assert errors(admin) == []


def test_phones_reach_it_from_the_header(admin_page: Page, live: LiveServer) -> None:
    page = admin_page
    goto(page, live, "/admin/manage")
    page.get_by_role("link", name="Einstellungen").click()
    expect(page.get_by_role("heading", name="Einstellungen", level=1)).to_be_visible()
    expect(page.get_by_role("link", name="Einstellungen")).to_have_attribute("aria-current", "page")
    for block in ("settings-event", "settings-booth-filters", "settings-password"):
        expect(page.get_by_test_id(block)).to_be_visible()
    # the section strip keeps its sections: Einstellungen is not one of them
    strip = page.get_by_role("navigation", name="Bereiche der Verwaltung")
    expect(strip.get_by_role("link", name="Einstellungen")).to_have_count(0)
    assert no_horizontal_scroll(page)
    shot(page, "admin-settings-phone")
    # a small phone: the header's title gives way instead of running under the upload pill
    page.set_viewport_size({"width": 360, "height": 780})
    title = page.get_by_text("Verwaltung", exact=True).first.bounding_box()
    pill = page.get_by_test_id("uploads-chip").first.bounding_box()
    assert title is not None and pill is not None
    assert title["x"] + title["width"] <= pill["x"]
    assert no_horizontal_scroll(page)
    assert errors(page) == []
