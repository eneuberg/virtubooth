"""The user page (/admin/user?id=): status line, pausing, banning in a sheet (with the
device-trait option), automatic bans and their release, unban, the guest's photos."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

from ..conftest import LiveServer
from .conftest import Guest, card, confirm_dialog, errors, fp_hash, goto, no_horizontal_scroll, toast, wait_live

pytestmark = pytest.mark.e2e


def open_details(page: Page) -> None:
    page.get_by_role("button", name="Technische Details").click()


def test_ban_with_the_device_option_and_unban(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    g = guests(instagram="troll", fp=1)
    twin = guests(fp=1)  # same phone model: same device trait, but known before the ban
    p1, p2 = g.upload(), g.upload()
    goto(page, live, f"/admin/user?id={g.id}")
    wait_live(page)
    expect(page.get_by_test_id("user-name")).to_have_text(g.name)
    expect(page.get_by_test_id("user-status")).to_have_text("Darf hochladen. 2\u00a0Fotos.")
    expect(page.get_by_test_id("user-insta")).to_contain_text("@troll")
    expect(page.locator("[data-testid=photo-tile]")).to_have_count(2)
    open_details(page)
    expect(page.get_by_test_id("device")).to_contain_text("iPhone, iOS 18.5, Safari 18.5")
    expect(page.get_by_test_id("fp-shared")).to_have_text("Auch auf 1 anderen Gerät:")
    expect(page.get_by_test_id("fingerprints").get_by_role("link", name=twin.name)).to_have_attribute(
        "href", f"/admin/user?id={twin.id}"
    )

    page.get_by_test_id("ban").click()
    sheet = page.get_by_role("dialog", name=f"„{g.name}“ sperren?")
    expect(sheet).to_be_visible()
    expect(sheet).to_contain_text("Alle 2 sichtbaren Fotos werden ausgeblendet")
    expect(sheet.get_by_test_id("fp-warning")).to_contain_text("1 anderes Gerät hat dieses Merkmal schon")
    expect(sheet.get_by_role("button", name="Abbrechen")).to_be_focused()
    sheet.get_by_label("Grund (freiwillig, nur für euch)").fill("Spam")
    sheet.get_by_text("Gerätemerkmal auch sperren").click()
    sheet.get_by_test_id("ban-confirm").click()
    expect(sheet).to_have_count(0)
    expect(toast(page)).to_contain_text("Gast und Gerätemerkmal gesperrt")
    expect(page.get_by_test_id("user-status")).to_have_attribute("data-state", "banned")
    expect(page.get_by_test_id("user-status")).to_contain_text(re.compile(r"Gesperrt seit \d\d:\d\d: Spam"))
    expect(page.get_by_test_id("user-status")).to_be_focused()
    for pid in (p1, p2):
        expect(card(page, pid).locator("figure")).to_have_attribute("data-hidden", "true")
        expect(card(page, pid)).to_contain_text("Ausgeblendet (Sperre)")
        photo = live.core.repos.photos.get(pid)
        assert photo is not None and photo.hidden_reason == "ban"
    assert live.core.repos.bans.is_banned(fp_hash(1))
    assert g.upload_response().status_code == 403
    assert twin.upload_response().status_code == 201  # known guests are not hit by the device ban
    assert guests(fp=1).state == "banned"  # a new identity on that device trait is

    page.get_by_test_id("unban").click()
    sheet = page.get_by_role("dialog", name=f"„{g.name}“ entsperren?")
    expect(sheet.get_by_test_id("unban-fp-peers")).to_contain_text("Entsperrt auch 1 weiteres Gerät")
    sheet.get_by_text("Gerätemerkmal-Sperre auch aufheben").click()
    sheet.get_by_test_id("unban-confirm").click()
    expect(toast(page)).to_contain_text("Gast und Gerätemerkmal entsperrt, 1 weiteres Gerät entsperrt")
    expect(page.get_by_test_id("user-status")).to_have_attribute("data-state", "ok")
    for pid in (p1, p2):
        expect(card(page, pid).locator("figure")).not_to_have_attribute("data-hidden", "true")
    assert not live.core.repos.bans.is_banned(fp_hash(1))
    assert g.upload_response().status_code == 201
    assert no_horizontal_scroll(page)
    assert errors(page) == []


def test_auto_banned_twin_and_its_release(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    troll = guests(fp=4)
    live.core.services.moderation.ban_user(troll.id, reason="Ärger", fingerprint=True, actor="pytest")
    twin, other = guests(fp=4), guests(fp=4)
    assert twin.state == "banned" and other.state == "banned"
    goto(page, live, f"/admin/user?id={twin.id}")
    expect(page.get_by_test_id("user-status")).to_have_attribute("data-state", "auto-banned")
    note = page.get_by_test_id("auto-ban-note")
    expect(note).to_contain_text("Automatisch gesperrt")
    expect(note).to_contain_text(f"gesperrt über „{troll.name}“")
    expect(note).to_contain_text("vielleicht ist das jemand anderes")
    open_details(page)
    expect(page.get_by_test_id("fingerprints")).to_contain_text(f"{other.name} (automatisch gesperrt)")
    # pausing makes no sense while banned
    expect(page.get_by_role("switch", name=re.compile("Hochladen pausieren"))).to_be_disabled()

    page.get_by_test_id("unban").click()
    sheet = page.get_by_role("dialog", name=re.compile("entsperren"))
    expect(sheet.get_by_test_id("auto-ban-explain")).to_contain_text("Entsperren gilt nur für dieses Gerät")
    sheet.get_by_test_id("unban-confirm").click()
    expect(page.get_by_test_id("user-status")).to_have_attribute("data-state", "ok")
    assert not live.core.repos.users.get(twin.id).banned  # type: ignore[union-attr]
    assert live.core.repos.bans.is_banned(fp_hash(4))  # only this device

    # the troll's page lifts the device ban: the other twin is released with it
    goto(page, live, f"/admin/user?id={troll.id}")
    open_details(page)
    page.get_by_test_id("unban-fingerprint").click()
    expect(toast(page)).to_contain_text("Gerätemerkmal entsperrt, 1 weiteres Gerät entsperrt")
    assert not live.core.repos.users.get(other.id).banned  # type: ignore[union-attr]
    assert live.core.repos.users.get(troll.id).banned  # type: ignore[union-attr]
    assert errors(page) == []


def test_pause_and_resume_uploads(admin_page: Page, live: LiveServer, guests: Callable[..., Guest]) -> None:
    g = guests()
    pid = g.upload()
    goto(admin_page, live, f"/admin/user?id={g.id}")
    wait_live(admin_page)
    switch = admin_page.get_by_role("switch", name=re.compile("Hochladen pausieren"))
    expect(switch).not_to_be_checked()
    admin_page.get_by_test_id("guest-uploads-toggle").click()
    expect(switch).to_be_checked()
    expect(admin_page.get_by_test_id("user-status")).to_have_attribute("data-state", "paused")
    expect(admin_page.get_by_test_id("guest-uploads-source")).to_have_text(
        re.compile(r"von Hand pausiert seit \d\d:\d\d")
    )
    expect(toast(admin_page)).to_contain_text(f"Hochladen für {g.name} pausiert")
    user = live.core.repos.users.get(g.id)
    assert user is not None and user.uploads_paused and user.uploads_paused_source == "admin"
    # not a ban: the photo stays visible, the guest just can't upload
    photo = live.core.repos.photos.get(pid)
    assert photo is not None and not photo.hidden
    assert g.upload_response().json()["error"] == "uploads_paused"

    admin_page.get_by_test_id("guest-uploads-toggle").click()
    expect(switch).not_to_be_checked()
    expect(admin_page.get_by_test_id("user-status")).to_have_attribute("data-state", "ok")
    assert g.upload_response().status_code == 201
    assert no_horizontal_scroll(admin_page)
    assert errors(admin_page, 403) == []


def test_photos_on_the_user_page(admin_page: Page, live: LiveServer, guests: Callable[..., Guest]) -> None:
    g = guests(instagram="phone.user")
    keep, doomed = g.upload(), g.upload()
    goto(admin_page, live, f"/admin/user?id={g.id}")
    card(admin_page, keep).get_by_test_id("toggle").click()
    expect(card(admin_page, keep).locator("figure")).to_have_attribute("data-hidden", "true")
    card(admin_page, doomed).locator("figure button").first.click()
    viewer = admin_page.get_by_test_id("lightbox")
    viewer.get_by_test_id("lightbox-delete").click()
    confirm_dialog(admin_page).get_by_role("button", name="Endgültig löschen").click()
    expect(viewer).to_have_count(0)
    expect(card(admin_page, doomed)).to_have_count(0)
    assert live.core.repos.photos.get(doomed) is None
    expect(admin_page.get_by_test_id("uploads-count")).to_have_text("1")
    assert no_horizontal_scroll(admin_page)
    assert errors(admin_page) == []


def test_unknown_or_missing_guest(admin_page: Page, live: LiveServer) -> None:
    goto(admin_page, live, "/admin/user?id=999")
    expect(admin_page.get_by_text("Gast nicht gefunden.")).to_be_visible()
    goto(admin_page, live, "/admin/user?id=abc")
    expect(admin_page.get_by_text("Kein Gast ausgewählt.")).to_be_visible()
    admin_page.get_by_role("link", name="Zur Gästeliste").click()
    admin_page.wait_for_url(live.url("/admin/manage?tab=gaeste"))
    assert errors(admin_page, 404) == []
