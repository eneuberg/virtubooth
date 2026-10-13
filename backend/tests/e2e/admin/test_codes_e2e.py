"""Admin → QR-Codes: the table with code 1, a new code, „Token ändern“ with a pasted
link of a printed code (token and Ziel), „Löschen“ into a grey tombstone, the
„Gelöschte zeigen“ switch and the deep link `&code=<id>`, on the host's laptop and
on a phone."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ...conftest import PARTY_TOKEN
from ..conftest import LiveServer, shot
from ..guest.blockers import assert_survives_blockers
from .conftest import errors, goto, no_horizontal_scroll, settle, toast

pytestmark = pytest.mark.e2e

PRINTED = "printed-qr-token-0123456789"


def rows(page: Page):  # type: ignore[no-untyped-def]
    return page.get_by_test_id("code-row")


def row(page: Page, code_id: int):  # type: ignore[no-untyped-def]
    return page.locator(f'[data-testid="code-row"][data-id="{code_id}"]')


@pytest.mark.parametrize("device", ["desktop", "phone"])
def test_create_retoken_and_delete_a_code(
    request: pytest.FixtureRequest, live: LiveServer, device: str
) -> None:
    page: Page = request.getfixturevalue("desktop_page" if device == "desktop" else "admin_page")
    codes = live.core.repos.codes
    first = codes.get(1)
    assert first is not None and first.token == PARTY_TOKEN

    goto(page, live, "/admin/manage?tab=qr")
    expect(page.get_by_role("heading", name="QR-Codes", level=1)).to_be_visible()
    expect(rows(page)).to_have_count(1)
    expect(row(page, 1)).to_contain_text(first.name)
    expect(page.get_by_test_id("code-count")).to_have_text("1 aktiv")
    assert no_horizontal_scroll(page)
    shot(page, f"admin-qr-{device}-table")

    # a new code: the next number, an animal name
    page.get_by_test_id("new-code").click()
    sheet = page.get_by_test_id("new-code-sheet")
    expect(sheet).to_be_visible()
    settle(page)
    sheet.get_by_test_id("code-create").click()
    expect(toast(page)).to_contain_text("angelegt.")
    second = codes.get(2)
    assert second is not None and second.name.endswith(" 2") and second.active
    expect(toast(page)).to_have_text(f"QR-Code {second.name} angelegt.")
    detail = page.get_by_test_id("code-sheet")
    expect(detail).to_be_visible()
    expect(detail.get_by_role("heading", name=second.name)).to_be_visible()
    expect(detail.get_by_test_id("code-url")).to_have_text(live.url(f"/?t={second.token}"))
    settle(page)

    # take over a printed code: its link sets token and Ziel
    detail.get_by_test_id("code-token").click()
    token_sheet = page.get_by_test_id("token-sheet")
    expect(token_sheet).to_be_visible()
    settle(page)
    token_sheet.get_by_text("Eigenes", exact=True).click()
    token_sheet.get_by_label("Token oder Link").fill(live.url(f"/x/booth/?t={PRINTED}"))
    expect(token_sheet.get_by_test_id("token-target-note")).to_have_text(
        "Ziel auf „Fotobox“ gesetzt, wie im Link."
    )
    shot(page, f"admin-qr-{device}-token-sheet")
    token_sheet.get_by_test_id("token-save").click()
    expect(toast(page)).to_have_text(f"Token von {second.name} geändert.")
    retokened = codes.get(2)
    assert retokened is not None
    assert (retokened.token, retokened.token_gen, retokened.target) == (PRINTED, 2, "booth")
    expect(detail).to_be_visible()
    expect(detail.get_by_test_id("code-url")).to_have_text(live.url(f"/x/booth/?t={PRINTED}"))
    expect(row(page, 2)).to_contain_text("Fotobox")
    settle(page)

    # „Löschen“: a grey tombstone, hidden unless „Gelöschte zeigen“
    detail.get_by_test_id("code-delete").click()
    dialog = page.get_by_test_id("code-delete-dialog").get_by_role("alertdialog")
    expect(dialog).to_contain_text(f"{second.name} löschen?")
    expect(page.get_by_test_id("last-code-warning")).to_have_count(0)
    settle(page)
    dialog.get_by_role("button", name="Löschen", exact=True).click()
    expect(toast(page)).to_have_text(f"{second.name} gelöscht.")
    expect(page.get_by_test_id("code-count")).to_have_text("1 aktiv · 1 gelöscht")
    expect(row(page, 2)).to_have_count(0)
    assert not codes.get(2).active  # type: ignore[union-attr]
    switch = page.get_by_role("switch", name="Gelöschte zeigen")
    expect(switch).not_to_be_checked()
    page.get_by_test_id("show-revoked").click()
    expect(switch).to_be_checked()
    expect(row(page, 2)).to_have_attribute("data-revoked", "true")
    expect(row(page, 2)).to_contain_text("Gelöscht")
    shot(page, f"admin-qr-{device}-revoked")
    page.get_by_test_id("show-revoked").click()
    expect(row(page, 2)).to_have_count(0)

    # a row opens its sheet
    row(page, 1).get_by_role("rowheader").click()
    expect(
        page.get_by_test_id("code-sheet").get_by_role("heading", name=first.name)
    ).to_be_visible()
    assert no_horizontal_scroll(page)
    assert errors(page) == []


@pytest.mark.parametrize("device", ["desktop", "phone"])
def test_deep_link_opens_a_codes_sheet(
    request: pytest.FixtureRequest, live: LiveServer, device: str
) -> None:
    page: Page = request.getfixturevalue("desktop_page" if device == "desktop" else "admin_page")
    first = live.core.repos.codes.get(1)
    assert first is not None
    goto(page, live, "/admin/manage?tab=qr&code=1")
    sheet = page.get_by_test_id("code-sheet")
    expect(sheet.get_by_role("heading", name=first.name)).to_be_visible()
    expect(sheet).to_contain_text("QR-Code Nr. 1")
    expect(sheet.get_by_test_id("code-url")).to_have_text(live.entry("/"))
    settle(page)
    # content blockers' element rules hide nothing of the sheet or the table under it
    assert_survives_blockers(page, f"{device} qr code sheet")
    shot(page, f"admin-qr-{device}-code-sheet")
    page.keyboard.press("Escape")
    expect(sheet).to_have_count(0)
    page.wait_for_url(live.url("/admin/manage?tab=qr"))
    assert no_horizontal_scroll(page)
    assert errors(page) == []
