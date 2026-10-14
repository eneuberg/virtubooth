"""The QR batch end to end: an event name, a new code „#2“ made in the admin, a guest
who joins through it and uploads, the code's numbers in the table and the
overview, its name in the guests list (column and `&code=` filter) and on the
user page, and its three downloads (PNG, big QR PDF, poster PDF with the saved
template) from the code's sheet."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

from ..conftest import LiveServer
from .conftest import Guest, errors, goto, settle, toast
from .test_poster_e2e import template_pdf, upload_via_api

pytestmark = pytest.mark.e2e

PNG = b"\x89PNG\r\n\x1a\n"
EVENT = "Lenas 30."


def cell(table: Locator, row: Locator, header: str) -> Locator:
    """The cell of `row` under the column `header` (columns hidden on small screens
    are not rendered, so the index comes from the headers on the page)."""
    headers = [t.strip() for t in table.get_by_role("columnheader").all_inner_texts()]
    return row.locator("td, th").nth(headers.index(header))


def download(page: Page, button: Locator, target: Path) -> tuple[str, bytes]:
    with page.expect_download() as info:
        button.click()
    info.value.save_as(target)
    return info.value.suggested_filename, target.read_bytes()


def save_default_layout(page: Page) -> None:
    """The QR field where the editor puts it first (a square in the page's middle)."""
    status = page.evaluate(
        """async () => (await fetch('/api/admin/poster/layout', {method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({page: 0, pages: 2, page_width: 595, page_height: 842,
                rect: {x: 0.3, y: 0.4, w: 0.4, h: 0.4 * 595 / 842}})})).status"""
    )
    assert status == 200


def test_a_code_from_creation_to_poster(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest], tmp_path: Path
) -> None:
    page = desktop_page
    live.core.services.host_settings.set_event_name(EVENT, actor="pytest")
    first_guest = guests()  # through code 1

    # code #2, made in the admin
    goto(page, live, "/admin/manage?tab=qr")
    page.get_by_test_id("new-code").click()
    sheet = page.get_by_test_id("new-code-sheet")
    expect(sheet).to_be_visible()
    settle(page)
    sheet.get_by_test_id("code-create").click()
    expect(toast(page)).to_contain_text("angelegt.")
    second = live.core.repos.codes.get(2)
    assert second is not None and second.active

    # a guest opens code 2's link, joins and uploads a beer photo
    guest = guests(entry=live.url(f"/?t={second.token}"))
    guest.upload()

    # the table counts it for #2 (fresh numbers after a reload)
    goto(page, live, "/admin/manage?tab=qr")
    table = page.get_by_test_id("codes")
    row = table.locator('[data-testid="code-row"][data-id="2"]')
    expect(row).to_contain_text(second.name)
    expect(cell(table, row, "Beigetreten")).to_have_text("1")
    expect(cell(table, row, "Fotos")).to_have_text("1")

    # a template with its QR field, then the three downloads from the code's sheet
    upload_via_api(page, template_pdf())
    save_default_layout(page)
    row.get_by_role("rowheader").click()
    detail = page.get_by_test_id("code-sheet")
    expect(detail.get_by_role("heading", name=second.name)).to_be_visible()
    expect(detail.get_by_test_id("code-stat-guests")).to_have_text("1")
    settle(page)
    # the animal as a file name slug ("Schildkröte" → "schildkroete")
    name, data = download(page, detail.get_by_test_id("code-export-png"), tmp_path / "qr.png")
    assert re.fullmatch(r"qr-02-[a-z]+\.png", name) and data.startswith(PNG)
    stem = name.removesuffix(".png")
    name, data = download(page, detail.get_by_test_id("code-export-qr-pdf"), tmp_path / "qr.pdf")
    assert name == f"{stem}-gross.pdf" and data.startswith(b"%PDF-")
    name, data = download(page, detail.get_by_test_id("code-export-poster"), tmp_path / "p.pdf")
    assert name == f"plakat-{stem.removeprefix('qr-')}.pdf" and data.startswith(b"%PDF-")

    # „Gäste über diesen Code anzeigen“: the guests list filtered by code 2
    detail.get_by_test_id("code-guests").click()
    page.wait_for_url(live.url("/admin/manage?tab=gaeste&code=2"))
    guest_rows = page.get_by_test_id("guest-row")
    expect(guest_rows).to_have_count(1)
    expect(guest_rows.first).to_have_attribute("data-id", str(guest.id))
    expect(guest_rows.first.get_by_test_id("guest-code")).to_have_text(second.name)

    # all guests: each with its code in the column „QR-Code“
    goto(page, live, "/admin/manage?tab=gaeste")
    expect(guest_rows).to_have_count(2)
    first = live.core.repos.codes.get(1)
    assert first is not None
    one = page.locator(f'[data-testid="guest-row"][data-id="{first_guest.id}"]')
    expect(one.get_by_test_id("guest-code")).to_have_text(first.name)

    # the user page names the code and links to its sheet
    goto(page, live, f"/admin/user?id={guest.id}")
    expect(page.get_by_test_id("user-code")).to_have_text(second.name)
    page.get_by_test_id("user-code-link").click()
    page.wait_for_url(live.url("/admin/manage?tab=qr&code=2"))
    expect(
        page.get_by_test_id("code-sheet").get_by_role("heading", name=second.name)
    ).to_be_visible()

    # the overview lists the code with its numbers
    goto(page, live, "/admin/manage?tab=uebersicht")
    overview = page.get_by_test_id("overview-codes")
    code_row = overview.locator('[data-testid="overview-code"][data-id="2"]')
    expect(code_row).to_contain_text(second.name)
    expect(cell(overview, code_row, "Beigetreten")).to_have_text("1")
    expect(cell(overview, code_row, "Fotos")).to_have_text("1")
    assert errors(page) == []


def test_row_menu_downloads_without_opening_the_sheet(
    desktop_page: Page, live: LiveServer, tmp_path: Path
) -> None:
    page = desktop_page
    goto(page, live, "/admin/manage?tab=qr")
    row = page.get_by_test_id("codes").locator('[data-testid="code-row"][data-id="1"]')
    menu = row.get_by_test_id("code-row-menu")
    expect(menu).to_have_accessible_name(re.compile(r"^Drucken: "))
    for kind, pattern in (
        ("png", r"qr-01-[a-z]+\.png"),
        ("qr-pdf", r"qr-01-[a-z]+-gross\.pdf"),
        ("poster", r"plakat-01-[a-z]+\.pdf"),
    ):
        expect(menu).to_be_enabled()
        menu.click()
        name, data = download(page, page.get_by_test_id(f"code-menu-{kind}"), tmp_path / kind)
        assert re.fullmatch(pattern, name), name
        assert data.startswith(PNG if kind == "png" else b"%PDF-")
    # the menu is no row click: the code's sheet stayed closed
    expect(page.get_by_test_id("code-sheet")).to_have_count(0)
    assert "code=" not in page.url
    assert errors(page) == []
