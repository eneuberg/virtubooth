"""The admin through tests/e2e/audit.py (axe, blockers, leaked React Aria classes) on a
phone and on the host's laptop: login, live (and its photo viewer), the upload-controls
sheet, manage (Fotos with the inspector or viewer and the delete question, Gäste,
Instagram, Sperren, Protokoll, Export), the user page and its ban and unban sheets.
Serious and critical axe findings fail; `VB_AXE_REPORT=<file>` lists everything."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Browser, expect

from ..audit import Audit
from ..conftest import LiveServer, settle_dialogs, track_errors
from .conftest import (
    DESKTOP_VIEWPORT,
    PHONE_VIEWPORT,
    Guest,
    admin_context,
    card,
    confirm_dialog,
    errors,
    goto,
    login_api,
    settle,
    wait_live,
)

pytestmark = pytest.mark.e2e

TABS = ("gaeste", "instagram", "sperren", "protokoll", "export")


@pytest.mark.parametrize("kind", ["phone", "desktop"])
def test_admin_screens(
    browser: Browser, live: LiveServer, guests: Callable[..., Guest], kind: str
) -> None:
    # a party in progress: handles, photos, a hidden one, a banned guest with a device ban
    anna = guests(instagram="anna.party", fp=1)
    ids = [anna.upload() for _ in range(3)]
    ben = guests(instagram="ben_b")
    ben.upload()
    troll = guests(fp=2)
    troll.upload()
    live.core.services.moderation.hide_photo(ids[0], actor="pytest")
    live.core.services.moderation.ban_user(
        troll.id, reason="Spam", fingerprint=True, actor="pytest"
    )

    audit = Audit(f"admin {kind}")
    phone = kind == "phone"
    viewport = PHONE_VIEWPORT if phone else DESKTOP_VIEWPORT
    options = {"is_mobile": True, "has_touch": True} if phone else {}
    ctx = admin_context(browser, viewport, **options)
    try:
        page = track_errors(ctx.new_page())
        goto(page, live, "/admin/login")
        expect(page.get_by_role("button", name="Anmelden")).to_be_visible()
        audit.check(page, "login")

        login_api(page, live)
        goto(page, live, "/admin/live")
        wait_live(page)
        expect(card(page, ids[1])).to_be_visible()
        audit.check(page, "live")
        card(page, ids[1]).click()
        expect(page.get_by_test_id("lightbox")).to_be_visible()
        settle_dialogs(page)
        settle(page)
        audit.check(page, "live viewer")
        page.keyboard.press("Escape")
        expect(page.get_by_test_id("lightbox")).to_have_count(0)

        page.get_by_test_id("uploads-chip").click()
        expect(page.get_by_role("dialog", name="Hochladen")).to_be_visible()
        settle_dialogs(page)
        audit.check(page, "upload controls")
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog", name="Hochladen")).to_have_count(0)

        goto(page, live, "/admin/manage")
        expect(card(page, ids[1])).to_be_visible()
        audit.check(page, "manage fotos")
        card(page, ids[1]).click()
        if phone:  # a tap opens the full-screen viewer
            panel = page.get_by_test_id("lightbox")
            delete = panel.get_by_test_id("lightbox-delete")
        else:  # a click opens the inspector next to the sheet
            panel = page.get_by_test_id("inspector")
            delete = panel.get_by_test_id("delete")
        expect(panel).to_be_visible()
        settle_dialogs(page)
        settle(page)
        audit.check(page, "manage fotos, " + ("viewer" if phone else "inspector"))
        delete.click()
        expect(confirm_dialog(page)).to_be_visible()
        settle_dialogs(page)
        audit.check(page, "delete question")
        confirm_dialog(page).get_by_role("button", name="Abbrechen").click()
        expect(confirm_dialog(page)).to_have_count(0)

        for tab in TABS:
            goto(page, live, f"/admin/manage?tab={tab}")
            expect(page.get_by_role("heading", level=1)).to_be_visible()
            settle(page)
            expect(page.locator("[aria-busy=true]")).to_have_count(0)
            audit.check(page, f"manage {tab}")

        goto(page, live, f"/admin/user?id={anna.id}")
        expect(page.get_by_test_id("user-name")).to_have_text(anna.name)
        audit.check(page, "user page")
        page.get_by_test_id("ban").click()
        ban = page.get_by_role("dialog", name=f"„{anna.name}“ sperren?")
        expect(ban).to_be_visible()
        settle_dialogs(page)
        audit.check(page, "ban sheet")
        ban.get_by_role("button", name="Abbrechen").click()
        expect(ban).to_have_count(0)

        goto(page, live, f"/admin/user?id={troll.id}")
        page.get_by_test_id("unban").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        settle_dialogs(page)
        audit.check(page, "unban sheet")
        page.keyboard.press("Escape")

        audit.assert_clean()
        assert errors(page) == []
    finally:
        ctx.close()
