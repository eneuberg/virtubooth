"""Allgemeines: the event name reaches the guests, the password change logs out the
other admin devices (and only the new password opens the admin), the public address
is checked against this server and the QR-Codes tab warns while it is broken. Fotobox:
the filters have their own section."""

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
    goto(page, live, "/admin/manage?tab=allgemein")
    expect(page.get_by_role("heading", name="Allgemeines", level=1)).to_be_visible()


def test_the_event_name_reaches_the_guests_and_goes_back(
    desktop_page: Page, browser: Browser, live: LiveServer
) -> None:
    admin = desktop_page
    goto(admin, live, "/admin/manage")
    # a section of the main navigation, right after Übersicht
    nav = admin.get_by_role("navigation", name="Verwaltung")
    nav.get_by_role("link", name="Allgemeines").click()
    expect(admin.get_by_role("heading", name="Allgemeines", level=1)).to_be_visible()
    assert admin.url.endswith("/admin/manage?tab=allgemein")

    field = admin.get_by_label("Name des Events")
    expect(field).to_have_value("E2E Party")
    expect(admin.get_by_role("heading", name="Öffentliche Adresse")).to_be_visible()
    expect(admin.get_by_test_id("settings-booth-filters")).to_have_count(0)
    shot(admin, "admin-settings-desktop")
    expect(admin.get_by_test_id("event-name-reset")).to_have_count(0)
    field.fill("  Gartenfest   2026 ")
    admin.get_by_test_id("settings-event").get_by_role("button", name="Speichern").click()
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
    expect(admin.get_by_role("heading", name="Allgemeines", level=1)).to_be_visible()

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


def test_phones_reach_it_from_the_section_strip(admin_page: Page, live: LiveServer) -> None:
    page = admin_page
    goto(page, live, "/admin/manage")
    expect(page.get_by_test_id("settings-link")).to_have_count(0)  # no gear in the header
    strip = page.get_by_role("navigation", name="Bereiche der Verwaltung")
    strip.get_by_role("link", name="Allgemeines").click()
    expect(page.get_by_role("heading", name="Allgemeines", level=1)).to_be_visible()
    expect(strip.get_by_role("link", name="Allgemeines")).to_have_attribute("aria-current", "page")
    for block in ("settings-event", "settings-address", "settings-password"):
        expect(page.get_by_test_id(block)).to_be_visible()
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


def test_fotobox_section_has_the_filters(desktop_page: Page, live: LiveServer) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage")
    page.get_by_role("navigation", name="Verwaltung").get_by_role("link", name="Fotobox").click()
    expect(page.get_by_role("heading", name="Fotobox", level=1)).to_be_visible()
    card = page.get_by_test_id("settings-booth-filters")
    expect(card).to_be_visible()
    expect(card.get_by_role("switch").first).to_be_checked()
    shot(page, "admin-fotobox-desktop")
    assert errors(page) == []


def test_public_address_check_and_qr_warning(desktop_page: Page, live: LiveServer) -> None:
    page = desktop_page
    open_settings(page, live)
    card = page.get_by_test_id("settings-address")
    status = card.get_by_test_id("address-status")
    expect(status).to_have_attribute("data-status", "auto")
    expect(card.get_by_text("Leer lassen = automatisch aus dem Aufruf")).to_be_visible()

    # this very server: the probe proves it
    field = card.get_by_label("Adresse für QR-Codes und Plakate")
    field.fill(live.base_url + "/")
    card.get_by_role("button", name="Speichern").click()
    expect(toast(page)).to_have_text("Adresse gespeichert.")
    expect(status).to_have_attribute("data-status", "ok")
    expect(status).to_contain_text(re.compile(r"Erreichbar ✓ – geprüft \d\d:\d\d"))
    expect(field).to_have_value(live.base_url)
    goto(page, live, "/admin/manage?tab=qr")
    expect(page.get_by_role("heading", name="QR-Codes", level=1)).to_be_visible()
    expect(page.get_by_test_id("address-warning")).to_have_count(0)

    # a port nobody listens on: a warning, saved anyway
    open_settings(page, live)
    field.fill("http://127.0.0.1:9")
    card.get_by_role("button", name="Speichern").click()
    expect(toast(page)).to_have_text("Adresse gespeichert, aber nicht erreichbar.")
    expect(status).to_have_attribute("data-status", "unreachable")
    expect(status).to_contain_text("Nicht erreichbar – QR-Codes würden ins Leere führen.")
    shot(page, "admin-address-unreachable-desktop")
    goto(page, live, "/admin/manage?tab=qr")
    warning = page.get_by_test_id("address-warning")
    expect(warning).to_contain_text(
        "Die öffentliche Adresse ist nicht geprüft oder nicht erreichbar. "
        "Prüfe sie unter „Allgemeines“, bevor du druckst."
    )
    shot(page, "admin-qr-warning-desktop")
    warning.get_by_role("link", name="Zu „Allgemeines“").click()
    expect(page.get_by_role("heading", name="Allgemeines", level=1)).to_be_visible()

    # empty: automatic again, nothing to check, no warning
    field.fill("")
    card.get_by_role("button", name="Speichern").click()
    expect(status).to_have_attribute("data-status", "auto")
    expect(card.get_by_test_id("public-address-check")).to_have_count(0)
    goto(page, live, "/admin/manage?tab=qr")
    expect(page.get_by_role("heading", name="QR-Codes", level=1)).to_be_visible()
    expect(page.get_by_test_id("address-warning")).to_have_count(0)
    assert errors(page) == []


def css_var(page: Page, name: str) -> str:
    value: str = page.evaluate(
        "(n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim()", name
    )
    return value


def test_the_theme_reaches_the_guests_but_not_the_admin(
    desktop_page: Page, browser: Browser, live: LiveServer
) -> None:
    admin = desktop_page
    open_settings(admin, live)
    card = admin.get_by_test_id("settings-theme")
    expect(card.get_by_role("heading", name="Erscheinungsbild")).to_be_visible()
    expect(card.get_by_role("radio", name="Neon Nacht")).to_be_checked()
    admin_bg = admin.evaluate("getComputedStyle(document.body).backgroundColor")

    ctx = new_context(browser)
    guest = track_errors(ctx.new_page())
    join_via_api(guest, live)
    # Neon Nacht from /api/theme.css, before any script ran
    assert css_var(guest, "--t-background") == "#1b1b1a"

    card.get_by_text("Klassisch", exact=True).click()
    expect(admin.get_by_test_id("theme-preview")).to_have_attribute(
        "style", re.compile(r"--t-background:\s*#2b0f0c")
    )
    card.scroll_into_view_if_needed()
    shot(admin, "admin-theme-card")
    card.get_by_test_id("theme-save").click()
    expect(toast(admin)).to_have_text("Erscheinungsbild gespeichert.")
    assert live.core.services.theme.public().preset == "klassisch"
    # the admin keeps its own look
    assert admin.evaluate("getComputedStyle(document.body).backgroundColor") == admin_bg

    # the guest page follows when it comes back to the foreground (no reload)
    guest.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    guest.wait_for_function(
        "getComputedStyle(document.documentElement).getPropertyValue('--t-background').trim()"
        " === '#2b0f0c'"
    )
    assert guest.evaluate("getComputedStyle(document.body).backgroundColor") != "rgb(27, 27, 26)"
    shot(guest, "guest-start-klassisch")

    card.get_by_test_id("theme-reset").click()
    expect(toast(admin)).to_have_text("Erscheinungsbild zurückgesetzt.")
    guest.reload()
    assert css_var(guest, "--t-background") == "#1b1b1a"
    assert guest.js_errors == []  # type: ignore[attr-defined]
    ctx.close()
    assert errors(admin) == []
