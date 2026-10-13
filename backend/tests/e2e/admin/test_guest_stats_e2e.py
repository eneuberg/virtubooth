"""Per-guest metrics in the admin: the guests table's „Online“ column (sortable, a dot
while the page is open) and the user page's „Statistik“ (online time, photos per
activity), also on a phone."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.parse import quote

import pytest
from playwright.sync_api import Page, expect

from ..conftest import LiveServer
from .conftest import Guest, beer_jpeg, errors, goto, no_horizontal_scroll, wait_live

pytestmark = pytest.mark.e2e

NBSP = " "


def rows(page: Page):  # type: ignore[no-untyped-def]
    return page.locator('table[aria-label="Gäste"] tbody tr:has([role=gridcell])')


def booth_upload(g: Guest) -> None:
    r = g.client.post(
        "/api/x/booth/upload",
        content=beer_jpeg(),
        headers={
            "Content-Type": "image/jpeg",
            "X-VB-Meta": quote(json.dumps({"filter": "normal", "facing": "user"}), safe=""),
        },
    )
    assert r.status_code == 201, r.text


def online_for(live: LiveServer, g: Guest, seconds: int) -> None:
    """The page beat once (a visit is open), and this much time was added up."""
    assert g.client.post("/api/here", json={"visible": True}).json() == {"ok": True}
    with live.core.db.tx() as c:
        c.execute("UPDATE users SET online_seconds=? WHERE id=?", (seconds, g.id))


def test_online_column_and_statistics(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    quiet = guests(instagram="quiet.one")
    busy = guests(instagram="busy.one")
    busy.upload()
    busy.upload()
    booth_upload(busy)
    online_for(live, busy, 12 * 60 + 34)

    goto(page, live, "/admin/manage?tab=gaeste")
    wait_live(page)
    header = page.get_by_role("columnheader", name="Online")
    expect(header).to_be_visible()
    expect(rows(page)).to_have_count(2)
    busy_cell = rows(page).filter(has_text=busy.name).get_by_test_id("guest-online")
    expect(busy_cell).to_have_text(f"gerade online12{NBSP}min")
    expect(busy_cell.locator("[title='Seite gerade offen']")).to_have_count(1)
    expect(rows(page).filter(has_text=quiet.name).get_by_test_id("guest-online")).to_have_text("–")

    header.click()  # ascending: the least online time first
    expect(rows(page).first).to_contain_text(quiet.name)
    header.click()
    expect(rows(page).first).to_contain_text(busy.name)

    rows(page).first.click()
    page.wait_for_url(live.url(f"/admin/user?id={busy.id}"))
    stats = page.get_by_test_id("user-stats")
    expect(stats.get_by_role("heading", name="Statistik")).to_be_visible()
    expect(page.get_by_test_id("user-online")).to_have_text(
        f"12{NBSP}min in 1{NBSP}Besuchgerade online"
    )
    expect(page.get_by_test_id("user-photo-counts")).to_have_text(
        f"3: Beer Cam{NBSP}2, Fotobox{NBSP}1"
    )
    expect(stats).to_contain_text("Erstes Foto")
    expect(stats).not_to_contain_text("Gelöscht")
    assert errors(page) == []


def test_statistics_follow_the_photos_and_fit_a_phone(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = admin_page
    g = guests(instagram="a.very.long.handle.for_layout1")
    first = g.upload()
    g.upload()
    goto(page, live, f"/admin/user?id={g.id}")
    wait_live(page)
    expect(page.get_by_test_id("user-online")).to_have_text("noch nicht gemessen")
    expect(page.get_by_test_id("user-photo-counts")).to_have_text(f"2: Beer Cam{NBSP}2")
    assert no_horizontal_scroll(page)

    # a photo deleted elsewhere: the page's photos change through the event stream,
    # and the counts follow
    live.core.services.moderation.delete_photo(first, actor="pytest")
    expect(page.get_by_test_id("user-photo-counts")).to_have_text(f"1: Beer Cam{NBSP}1")
    expect(page.get_by_test_id("user-stats")).to_contain_text("Gelöscht1")

    goto(page, live, "/admin/manage?tab=gaeste")
    expect(rows(page)).to_have_count(1)
    assert no_horizontal_scroll(page)
    assert errors(page) == []
