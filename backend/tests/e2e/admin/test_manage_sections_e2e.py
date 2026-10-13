"""Manage: sections and their deep links, the guests table (search, status, paging),
bans and device bans (auto-ban release), the audit log with paging."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from playwright.sync_api import Page, expect

from ..conftest import LiveServer
from .conftest import Guest, errors, fp_hash, goto, no_horizontal_scroll, toast, wait_live

pytestmark = pytest.mark.e2e


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def body_rows(page: Page, table: str):  # type: ignore[no-untyped-def]
    """Data rows (an empty table shows one row with its empty state)."""
    return page.locator(f'table[aria-label="{table}"] tbody tr:has([role=gridcell])')


def make_users(live: LiveServer, n: int) -> None:
    for _ in range(n):
        live.core.repos.users.create(
            public_id=os.urandom(8).hex(),
            at=now(),
            consent_version="1",
            instagram=None,
            fp_hash=None,
            fp_components={},
            ip="10.0.0.1",
            user_agent="pytest",
        )


@pytest.mark.parametrize(
    ("tab", "heading"),
    [("fotos", "Fotos"), ("gaeste", "Gäste"), ("instagram", "Instagram"), ("sperren", "Sperren"),
     ("protokoll", "Protokoll"), ("export", "Export"), ("nope", "Fotos")],
)  # fmt: skip
def test_tab_deep_links(desktop_page: Page, live: LiveServer, tab: str, heading: str) -> None:
    goto(desktop_page, live, f"/admin/manage?tab={tab}")
    expect(desktop_page.get_by_role("heading", name=heading, level=1)).to_be_visible()
    current = desktop_page.get_by_role("navigation", name="Verwaltung").locator(
        "[aria-current=page]"
    )
    expect(current).to_contain_text(heading)
    assert errors(desktop_page) == []


def test_sidebar_moves_focus_to_the_section(desktop_page: Page, live: LiveServer) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage")
    page.get_by_role("link", name=re.compile("^Gäste")).click()
    page.wait_for_url(live.url("/admin/manage?tab=gaeste"))
    expect(page.get_by_role("heading", name="Gäste", level=1)).to_be_focused()
    page.keyboard.press("Tab")
    expect(page.get_by_role("searchbox", name="Gäste suchen")).to_be_focused()
    assert errors(page) == []


def test_guests_table_search_status_paging(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    make_users(live, 103)
    ben = guests(instagram="ben.b")
    troll = guests()
    live.core.services.moderation.ban_user(troll.id, reason="Spam", actor="pytest")
    goto(page, live, "/admin/manage?tab=gaeste")
    rows = body_rows(page, "Gäste")
    expect(rows).to_have_count(100)
    expect(page.get_by_test_id("guest-count")).to_have_text("105 Gäste")
    page.get_by_role("button", name="Mehr laden").click()
    expect(rows).to_have_count(105)

    page.get_by_role("searchbox", name="Gäste suchen").fill("ben.b")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("@ben.b")
    assert "q=ben.b" in page.url
    page.get_by_role("searchbox", name="Gäste suchen").fill(f"#{troll.id}")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Gesperrt")
    page.get_by_role("searchbox", name="Gäste suchen").fill("")
    expect(rows).to_have_count(105)  # both pages are still there

    page.get_by_test_id("guest-filter").get_by_role("button").click()
    page.get_by_role("option", name="Gesperrt", exact=True).click()
    expect(rows).to_have_count(1)
    assert "show=banned" in page.url
    expect(page.get_by_test_id("guest-count")).to_have_text("1 Treffer")
    rows.first.click()
    page.wait_for_url(live.url(f"/admin/user?id={troll.id}"))
    expect(page.get_by_test_id("user-name")).to_have_text(troll.name)
    page.go_back()
    expect(rows).to_have_count(1)
    assert ben.id > 0
    assert errors(page) == []


def test_bans_device_bans_and_auto_ban_release(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    troll = guests(instagram="troll", fp=3)
    troll.upload()
    live.core.services.moderation.ban_user(
        troll.id, reason="Spam", fingerprint=True, actor="pytest"
    )
    twin = guests(fp=3)  # the same phone model: starts banned automatically
    assert twin.state == "banned"
    goto(page, live, "/admin/manage?tab=sperren")
    wait_live(page)
    users = body_rows(page, "Gesperrte Gäste")
    expect(users).to_have_count(2)
    twin_row = users.filter(has_text=twin.name)
    expect(twin_row.get_by_test_id("auto-ban")).to_have_text("Automatisch gesperrt")
    expect(twin_row).to_contain_text(f"Gleiches Gerätemerkmal wie „{troll.name}“")
    devices = body_rows(page, "Gesperrte Gerätemerkmale")
    expect(devices).to_have_count(1)
    expect(devices.first.get_by_test_id("fp-auto-note")).to_contain_text("1 nur deshalb gesperrt")
    expect(devices.first).to_contain_text(troll.name)

    # one tap releases the automatically banned device only
    twin_row.get_by_role("button", name=f"{twin.name} entsperren").click()
    expect(toast(page)).to_contain_text(f"{twin.name} ist entsperrt")
    expect(users).to_have_count(1)
    assert live.core.repos.bans.is_banned(fp_hash(3))
    assert twin.upload_response().status_code == 201

    # lifting the device ban leaves the troll banned
    devices.first.get_by_test_id("unban-fp").click()
    expect(toast(page)).to_contain_text("Gerätemerkmal entsperrt")
    expect(devices).to_have_count(0)
    assert not live.core.repos.bans.is_banned(fp_hash(3))
    troll_user = live.core.repos.users.get(troll.id)
    assert troll_user is not None and troll_user.banned
    users.first.get_by_test_id("unban-user").click()
    expect(users).to_have_count(0)
    expect(page.get_by_text("Niemand gesperrt")).to_be_visible()
    assert errors(page) == []


def test_audit_log_with_paging(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    g = guests()
    pid = g.upload()
    for i in range(110):
        live.core.repos.audit.log("admin:abcdef12", "photo.hide", f"photo:{pid}", {}, at=now())
        if i == 0:
            live.core.repos.audit.log(
                "anonymous", "admin.login_failed", "ip:10.0.0.9", {}, at=now()
            )
    live.core.services.moderation.ban_user(g.id, reason="Spam", actor="admin:abcdef12")
    goto(page, live, "/admin/manage?tab=protokoll")
    rows = body_rows(page, "Protokoll")
    expect(rows).to_have_count(100)
    expect(rows.first).to_contain_text("Gast gesperrt")
    expect(rows.first).to_contain_text("Grund: Spam")
    expect(rows.first).to_contain_text("Admin-Sitzung abcd")
    page.get_by_role("button", name="Ältere Einträge").click()
    expect(rows).to_have_count(113)  # 110 + failed login + ban + the test's own login
    expect(page.get_by_test_id("audit")).to_contain_text("Falsches Admin-Passwort")
    expect(page.get_by_test_id("audit")).to_contain_text("Unbekannt")
    # a photo target opens the photo
    rows.nth(1).get_by_role("link", name="Foto ansehen").click()
    page.wait_for_url(re.compile(rf"/admin/manage\?photo={pid}$"))
    expect(
        page.get_by_test_id("inspector").get_by_role("heading", name="Bier 0001")
    ).to_be_visible()
    assert errors(page) == []


def test_manage_sections_on_a_phone(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    g = guests(instagram="a.very.long.handle.for_layout1")
    g.upload()
    for tab in ("fotos", "gaeste", "instagram", "sperren", "protokoll", "export"):
        goto(admin_page, live, f"/admin/manage?tab={tab}")
        strip = admin_page.get_by_role("navigation", name="Bereiche der Verwaltung")
        expect(strip.locator("[aria-current=page]")).to_be_visible()
        assert no_horizontal_scroll(admin_page), tab
    assert errors(admin_page) == []
