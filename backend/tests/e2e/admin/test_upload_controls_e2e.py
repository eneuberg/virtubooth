"""The party switches, always in sight on every admin screen (the manage sidebar, the
top of the manage area on phones, the Live header): "Hochladen für alle stoppen", the
new-guest pause (switching it off asks: release or keep) and the way to paused guests."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Locator, Page, expect

from ..conftest import LiveServer, track_errors
from .conftest import Guest, errors, goto, toast, wait_live

pytestmark = pytest.mark.e2e

STOP = re.compile("Hochladen für alle stoppen")
PAUSE = re.compile("Neue Gäste pausieren")


def switch(page: Page, name: re.Pattern[str]) -> Locator:
    """The switch itself (role="switch", checked state), by its label."""
    return page.get_by_test_id("party-controls").get_by_role("switch", name=name)


def row(page: Page, test_id: str) -> Locator:
    """The switch's visible row: label, state line, track (what a tap hits)."""
    return page.get_by_test_id("party-controls").get_by_test_id(test_id)


def test_stop_all_uploads_and_back(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    known = guests()
    paused = guests()
    live.core.services.upload_controls.set_user_paused(paused.id, True, actor="pytest")
    live.core.services.upload_controls.set_pause(True, restore=None, actor="pytest")
    lock = live.core.services.upload_controls.pause_state()

    goto(admin_page, live, "/admin/live")
    second = track_errors(admin_page.context.new_page())  # another admin screen
    goto(second, live, "/admin/manage")
    for p in (admin_page, second):
        wait_live(p)
        # all three switches in sight, no menu or sheet in between
        for test_id in ("upload-stop-switch", "join-stop-switch", "upload-pause-switch"):
            expect(row(p, test_id)).to_be_visible()
        expect(switch(p, PAUSE)).to_be_checked()
        expect(switch(p, STOP)).not_to_be_checked()

    row(admin_page, "upload-stop-switch").click()
    expect(switch(admin_page, STOP)).to_be_checked()
    expect(admin_page.get_by_role("dialog")).to_have_count(0)
    expect(row(admin_page, "upload-stop-switch")).to_contain_text(
        re.compile(r"Gestoppt seit \d\d:\d\d")
    )
    # every admin screen shows it at once
    for p in (admin_page, second):
        expect(row(p, "upload-stop-switch")).to_have_attribute("data-state", "on")
    expect(admin_page.get_by_test_id("party-badges")).to_contain_text("Hochladen gestoppt")
    r = known.upload_response()
    assert r.status_code == 403 and r.json()["error"] == "uploads_stopped"

    # the same switch, on the other screen, resumes
    row(second, "upload-stop-switch").click()
    for p in (admin_page, second):
        expect(switch(p, STOP)).not_to_be_checked()
        expect(switch(p, PAUSE)).to_be_checked()
    # back to exactly as before: the paused guest and the new-guest pause are untouched
    assert known.upload_response().status_code == 201
    assert live.core.services.upload_controls.pause_state() == lock
    assert paused.upload_response().json()["error"] == "uploads_paused"
    assert errors(admin_page) == [] and errors(second) == []


def test_pause_new_guests_then_restore(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    known = guests()
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)
    expect(switch(admin_page, PAUSE)).not_to_be_checked()
    expect(admin_page.get_by_test_id("uploads-paused-list")).to_have_count(0)

    row(admin_page, "upload-pause-switch").click()
    expect(switch(admin_page, PAUSE)).to_be_checked()
    expect(row(admin_page, "upload-pause-switch")).to_contain_text(
        re.compile(r"Seit \d\d:\d\d, noch niemand betroffen\.")
    )

    newcomer = guests()
    assert newcomer.paused
    r = newcomer.upload_response()
    assert r.status_code == 403 and r.json()["error"] == "uploads_paused"
    assert known.upload_response().status_code == 201  # guests from before keep uploading

    expect(row(admin_page, "upload-pause-switch")).to_contain_text("1\u00a0Gast betroffen")
    expect(admin_page.get_by_test_id("uploads-paused-list")).to_have_text("1\u00a0Gast pausiert")
    row(admin_page, "upload-pause-switch").click()
    dialog = admin_page.get_by_role("dialog", name="Pause für neue Gäste beenden")
    expect(dialog.get_by_test_id("pause-end-text")).to_contain_text(
        "1 Gast ist während der Pause beigetreten"
    )
    # still on until the host decides
    expect(switch(admin_page, PAUSE)).to_be_checked()
    expect(dialog.get_by_test_id("pause-end-keep")).to_have_text("Pausiert lassen")
    dialog.get_by_test_id("pause-end-restore").click()
    expect(dialog).to_have_count(0)
    expect(toast(admin_page)).to_contain_text("1\u00a0Gast wieder freigeschaltet.")
    expect(switch(admin_page, PAUSE)).not_to_be_checked()
    expect(admin_page.get_by_test_id("uploads-paused-list")).to_have_count(0)
    assert newcomer.upload_response().status_code == 201
    assert errors(admin_page) == []


def test_pause_new_guests_then_keep(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=gaeste")
    wait_live(page)
    # the sidebar holds the switches on desktop
    expect(page.get_by_role("complementary").get_by_test_id("party-controls")).to_be_visible()
    row(page, "upload-pause-switch").click()
    expect(switch(page, PAUSE)).to_be_checked()

    newcomer = guests()
    # the guest list follows live: the new row carries the paused badge
    table_row = page.locator('table[aria-label="Gäste"] tbody tr').filter(has_text=newcomer.name)
    expect(table_row.get_by_test_id("paused-badge")).to_have_text("Hochladen pausiert")

    row(page, "upload-pause-switch").click()
    page.get_by_test_id("pause-end-keep").click()
    expect(page.get_by_test_id("pause-end-text")).to_have_count(0)
    expect(switch(page, PAUSE)).not_to_be_checked()
    assert newcomer.upload_response().json()["error"] == "uploads_paused"
    later = guests()
    assert not later.paused and later.upload_response().status_code == 201

    # "1 Gast pausiert": the list filtered to paused guests (release them there)
    page.get_by_test_id("uploads-paused-list").click()
    page.wait_for_url(re.compile(r"/admin/manage\?tab=gaeste&show=paused"))
    rows = page.locator('table[aria-label="Gäste"] tbody tr:has([role=gridcell])')
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text(newcomer.name)
    assert errors(page) == []


def test_the_switches_are_keyboard_switches(desktop_page: Page, live: LiveServer) -> None:
    page = desktop_page
    goto(page, live, "/admin/live")
    wait_live(page)
    join_switch = switch(page, re.compile("Anmeldung stoppen"))
    join_switch.focus()
    page.keyboard.press("Space")
    expect(join_switch).to_be_checked()
    assert live.core.repos.app_settings.join_stop().enabled
    page.keyboard.press("Space")
    expect(join_switch).not_to_be_checked()
    assert errors(page) == []
