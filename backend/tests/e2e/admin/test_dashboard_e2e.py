"""The dashboard: "Hochladen stoppen" and "Anmeldung stoppen" in one tap on every admin
screen, the status strip in sync across screens, the live overview, and the guest's join
sheet while joining is closed."""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx2 as httpx
import pytest
from playwright.sync_api import Page, expect

from ..conftest import JOIN_ACCEPT, LiveServer, accept_consent_in_browser
from .conftest import Guest, errors, goto, wait_live

pytestmark = pytest.mark.e2e


def newcomer(live: LiveServer) -> tuple[httpx.Client, dict]:
    """A browser that scanned the QR code and asked who it is (not joined)."""
    c = httpx.Client(base_url=live.base_url, headers={"Origin": live.base_url})
    assert c.get(live.entry("/")).status_code == 303
    r = c.post("/api/identify", json={})
    assert r.status_code == 200, r.text
    return c, r.json()


def join(c: httpx.Client, version: str) -> httpx.Response:
    return c.post("/api/join", json={"accept": True, "version": version, "fp": {"hash": "cd" * 32}})


def test_one_tap_stops_on_every_screen(
    admin_page: Page, desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    known = guests()
    goto(admin_page, live, "/admin/live")  # the host's phone
    goto(desktop_page, live, "/admin/manage")  # the laptop
    screens = (admin_page, desktop_page)
    for p in screens:
        wait_live(p)
        expect(p.get_by_test_id("status-strip")).to_have_attribute("data-state", "off")

    # the phone: one tap stops every upload, no question asked
    stop = admin_page.get_by_test_id("quick-upload-stop")
    expect(stop).to_have_attribute("aria-pressed", "false")
    stop.click()
    expect(stop).to_have_attribute("aria-pressed", "true")
    expect(admin_page.get_by_role("dialog")).to_have_count(0)
    expect(admin_page.get_by_role("alertdialog")).to_have_count(0)
    for p in screens:
        strip = p.get_by_test_id("status-strip-uploads")
        expect(strip).to_be_visible()
        expect(strip).to_contain_text("Hochladen gestoppt")
        expect(strip).to_contain_text(re.compile(r"Für alle, seit \d\d:\d\d"))
        expect(p.get_by_test_id("uploads-chip")).to_have_attribute("data-state", "stopped")
    assert known.upload_response().json()["error"] == "uploads_stopped"

    # the laptop: joining stops right next to it
    desktop_page.get_by_test_id("quick-join-stop").click()
    for p in screens:
        expect(p.get_by_test_id("status-strip-join")).to_contain_text("Anmeldung gestoppt")
        expect(p.get_by_test_id("quick-join-stop")).to_have_attribute("aria-pressed", "true")
    client, answer = newcomer(live)
    assert answer["state"] == "needs_consent" and answer["join_closed"] is True
    refused = join(client, answer["consent"]["version"])
    assert refused.status_code == 403 and refused.json()["error"] == "join_closed"

    # resume uploads from the strip on the phone: the join stop stays
    admin_page.get_by_role("button", name="Hochladen fortsetzen").click()
    for p in screens:
        expect(p.get_by_test_id("status-strip-uploads")).to_have_count(0)
        expect(p.get_by_test_id("quick-upload-stop")).to_have_attribute("aria-pressed", "false")
        expect(p.get_by_test_id("status-strip-join")).to_be_visible()
    assert known.upload_response().status_code == 201

    # and the join stop off on the laptop's toggle
    desktop_page.get_by_test_id("quick-join-stop").click()
    for p in screens:
        expect(p.get_by_test_id("status-strip")).to_have_attribute("data-state", "off")
    assert join(client, answer["consent"]["version"]).status_code == 201
    client.close()

    actions = [e.action for e in live.core.repos.audit.list()]
    for action in ("uploads.stop", "uploads.resume", "join.stop", "join.resume"):
        assert actions.count(action) == 1, action
    assert errors(admin_page) == [] and errors(desktop_page) == []


def test_live_overview_counts_and_follows_the_party(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    anna = guests(instagram="anna")
    guests()
    lurker, _ = newcomer(live)  # scanned, never joined
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)

    def stat(name: str):  # type: ignore[no-untyped-def]
        return admin_page.get_by_test_id(f"overview-{name}").locator("dd")

    expect(stat("guests")).to_have_text("2")
    expect(stat("scanned")).to_have_text("3")
    expect(stat("not-joined")).to_have_text("1")
    expect(stat("active")).to_have_text("2")
    expect(stat("uploading")).to_have_text("0")

    # an upload arrives: the event stream refreshes the numbers, no reload
    anna.upload()
    expect(stat("uploading")).to_have_text("1")
    expect(stat("recent")).to_have_text("1")

    # "Alle Zahlen": the Übersicht in the manage area
    admin_page.get_by_test_id("overview-more").click()
    expect(admin_page).to_have_url(re.compile(r"/admin/manage\?tab=uebersicht$"))
    section = admin_page.get_by_test_id("overview-section")
    expect(section.get_by_test_id("overview-instagram").locator("dd")).to_have_text("1")
    expect(section.get_by_test_id("overview-activities")).to_contain_text("Beer Cam")
    lurker.close()
    assert errors(admin_page) == []


def test_join_sheet_while_joining_is_closed(page: Page, live: LiveServer) -> None:
    controls = live.core.services.join_controls
    controls.set_stop(True, actor="pytest")
    page.goto(live.entry("/"))
    sheet = page.get_by_test_id("join")
    expect(sheet.get_by_test_id("join-closed")).to_contain_text(
        "Gerade kann niemand neu beitreten."
    )
    expect(page.locator(JOIN_ACCEPT)).to_have_count(0)

    # the host opens joining again: the guest's re-check brings the button back
    controls.set_stop(False, actor="pytest")
    sheet.get_by_test_id("join-recheck").click()
    expect(page.locator(JOIN_ACCEPT)).to_be_visible()
    accept_consent_in_browser(page)
    expect(page.get_by_test_id("start")).to_be_visible()
    assert live.core.repos.overview.overview().scans.joined == 1
    assert page.js_errors == []  # type: ignore[attr-defined]
