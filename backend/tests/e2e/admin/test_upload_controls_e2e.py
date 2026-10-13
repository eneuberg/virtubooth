"""Upload controls, one sheet from every header: "Hochladen für alle stoppen", the
new-guest pause (switching it off asks: release or keep) and per-guest release."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Locator, Page, expect

from ..conftest import LiveServer, track_errors
from .conftest import Guest, errors, goto, wait_live

pytestmark = pytest.mark.e2e


def open_sheet(page: Page) -> Locator:
    page.get_by_test_id("uploads-chip").click()
    sheet = page.get_by_role("dialog", name="Hochladen")
    expect(sheet).to_be_visible()
    return sheet


def close_sheet(page: Page) -> None:
    page.get_by_role("dialog", name="Hochladen").get_by_role("button", name="Schließen").click()
    expect(page.get_by_role("dialog", name="Hochladen")).to_have_count(0)


def pill(page: Page) -> Locator:
    return page.get_by_test_id("uploads-chip")


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
        expect(pill(p)).to_have_attribute("data-state", "paused-new")

    sheet = open_sheet(admin_page)
    stop = sheet.get_by_role("switch", name=re.compile("Hochladen für alle stoppen"))
    expect(stop).not_to_be_checked()
    sheet.get_by_test_id("upload-stop-switch").click()
    expect(stop).to_be_checked()
    expect(sheet.get_by_test_id("upload-stop-switch")).to_contain_text(re.compile(r"Gestoppt seit \d\d:\d\d"))
    expect(sheet.get_by_test_id("uploads-result")).to_have_text("Hochladen für alle gestoppt.")
    close_sheet(admin_page)
    # every admin screen shows it at once
    for p in (admin_page, second):
        expect(pill(p)).to_have_attribute("data-state", "stopped")
    r = known.upload_response()
    assert r.status_code == 403 and r.json()["error"] == "uploads_stopped"

    sheet = open_sheet(admin_page)
    sheet.get_by_test_id("upload-stop-switch").click()
    expect(sheet.get_by_role("switch", name=re.compile("Hochladen für alle stoppen"))).not_to_be_checked()
    close_sheet(admin_page)
    expect(pill(second)).to_have_attribute("data-state", "paused-new")
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
    expect(pill(admin_page)).to_have_attribute("data-state", "on")
    expect(pill(admin_page)).to_have_text("Hochladen an")

    sheet = open_sheet(admin_page)
    switch = sheet.get_by_role("switch", name=re.compile("Neue Gäste pausieren"))
    sheet.get_by_test_id("upload-pause-switch").click()
    expect(switch).to_be_checked()
    expect(sheet.get_by_test_id("upload-pause-switch")).to_contain_text(
        re.compile(r"Seit \d\d:\d\d, noch niemand betroffen\.")
    )
    close_sheet(admin_page)
    expect(pill(admin_page)).to_have_text("Neue pausiert")

    newcomer = guests()
    assert newcomer.paused
    r = newcomer.upload_response()
    assert r.status_code == 403 and r.json()["error"] == "uploads_paused"
    assert known.upload_response().status_code == 201  # guests from before keep uploading

    sheet = open_sheet(admin_page)
    expect(sheet.get_by_test_id("upload-pause-switch")).to_contain_text("1\u00a0Gast betroffen")
    expect(sheet.get_by_test_id("paused-guests")).to_contain_text(newcomer.name)
    expect(sheet.get_by_test_id("paused-guests")).to_contain_text("automatisch")
    sheet.get_by_test_id("upload-pause-switch").click()
    expect(sheet.get_by_test_id("pause-end-text")).to_contain_text("1 Gast ist während der Pause beigetreten")
    expect(sheet.get_by_test_id("pause-end-keep")).to_have_text("Pausiert lassen")
    sheet.get_by_test_id("pause-end-restore").click()
    expect(sheet.get_by_test_id("uploads-result")).to_have_text("1\u00a0Gast wieder freigeschaltet.")
    expect(sheet.get_by_role("switch", name=re.compile("Neue Gäste pausieren"))).not_to_be_checked()
    close_sheet(admin_page)
    expect(pill(admin_page)).to_have_attribute("data-state", "on")
    assert newcomer.upload_response().status_code == 201
    assert errors(admin_page) == []


def test_pause_new_guests_then_keep(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=gaeste")
    wait_live(page)
    sheet = open_sheet(page)
    sheet.get_by_test_id("upload-pause-switch").click()
    expect(sheet.get_by_role("switch", name=re.compile("Neue Gäste pausieren"))).to_be_checked()
    close_sheet(page)

    newcomer = guests()
    # the guest list follows live: the new row carries the paused badge
    row = page.locator('table[aria-label="Gäste"] tbody tr').filter(has_text=newcomer.name)
    expect(row.get_by_test_id("paused-badge")).to_have_text("Hochladen pausiert")

    sheet = open_sheet(page)
    sheet.get_by_test_id("upload-pause-switch").click()
    sheet.get_by_test_id("pause-end-keep").click()
    expect(sheet.get_by_test_id("uploads-result")).to_have_text(
        "Neue Gäste können wieder hochladen. 1\u00a0Gast bleibt pausiert."
    )
    assert newcomer.upload_response().json()["error"] == "uploads_paused"
    later = guests()
    assert not later.paused and later.upload_response().status_code == 201

    # "In der Gästeliste ansehen": the list filtered to paused guests
    sheet.get_by_test_id("uploads-paused-list").click()
    page.wait_for_url(re.compile(r"/admin/manage\?tab=gaeste&show=paused"))
    rows = page.locator('table[aria-label="Gäste"] tbody tr:has([role=gridcell])')
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text(newcomer.name)
    assert errors(page) == []


def test_release_one_guest_from_the_sheet(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    g = guests()
    live.core.services.upload_controls.set_user_paused(g.id, True, actor="pytest")
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)
    # the bottom bar's "Hochladen" opens the same sheet
    admin_page.get_by_role("navigation", name="Bereiche").get_by_role("button", name="Hochladen").click()
    sheet = admin_page.get_by_role("dialog", name="Hochladen")
    expect(sheet.get_by_test_id("paused-guests")).to_contain_text("von Hand")
    sheet.get_by_role("button", name=f"Hochladen für {g.name} erlauben").click()
    expect(sheet.get_by_test_id("uploads-result")).to_have_text(f"{g.name} darf wieder hochladen.")
    expect(sheet.get_by_text("Niemand ist pausiert.")).to_be_visible()
    assert g.upload_response().status_code == 201
    # Escape closes it, the focus goes back to where it was
    admin_page.keyboard.press("Escape")
    expect(sheet).to_have_count(0)
    assert errors(admin_page) == []
