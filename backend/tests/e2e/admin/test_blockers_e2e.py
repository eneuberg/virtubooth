"""Content blockers vs. the rendered admin (guest/blockers.py: the vendored cosmetic
rules, the full lists with VB_BLOCKLISTS) on a phone and on the host's laptop: login,
live (and its photo viewer), the upload-controls sheet, manage (Fotos with the
inspector or viewer and the delete question, Gäste, Instagram, Sperren, Protokoll,
Export), the user page and its ban and unban sheets."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Browser, expect

from ..conftest import LiveServer, settle_dialogs, track_errors
from ..guest.blockers import assert_survives_blockers
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

    phone = kind == "phone"
    viewport = PHONE_VIEWPORT if phone else DESKTOP_VIEWPORT
    options = {"is_mobile": True, "has_touch": True} if phone else {}
    ctx = admin_context(browser, viewport, **options)
    try:
        page = track_errors(ctx.new_page())
        goto(page, live, "/admin/login")
        expect(page.get_by_role("button", name="Anmelden")).to_be_visible()
        assert_survives_blockers(page, f"{kind} login")

        login_api(page, live)
        goto(page, live, "/admin/live")
        wait_live(page)
        expect(card(page, ids[1])).to_be_visible()
        assert_survives_blockers(page, f"{kind} live")
        card(page, ids[1]).click()
        expect(page.get_by_test_id("lightbox")).to_be_visible()
        settle_dialogs(page)
        settle(page)
        assert_survives_blockers(page, f"{kind} live viewer")
        page.keyboard.press("Escape")
        expect(page.get_by_test_id("lightbox")).to_have_count(0)

        page.get_by_test_id("uploads-chip").click()
        expect(page.get_by_role("dialog", name="Hochladen")).to_be_visible()
        settle_dialogs(page)
        assert_survives_blockers(page, f"{kind} upload controls")
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog", name="Hochladen")).to_have_count(0)

        goto(page, live, "/admin/manage")
        expect(card(page, ids[1])).to_be_visible()
        assert_survives_blockers(page, f"{kind} manage fotos")
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
        assert_survives_blockers(page, f"{kind} manage fotos, {'viewer' if phone else 'inspector'}")
        delete.click()
        expect(confirm_dialog(page)).to_be_visible()
        settle_dialogs(page)
        assert_survives_blockers(page, f"{kind} delete question")
        confirm_dialog(page).get_by_role("button", name="Abbrechen").click()
        expect(confirm_dialog(page)).to_have_count(0)

        for tab in TABS:
            goto(page, live, f"/admin/manage?tab={tab}")
            expect(page.get_by_role("heading", level=1)).to_be_visible()
            settle(page)
            expect(page.locator("[aria-busy=true]")).to_have_count(0)
            assert_survives_blockers(page, f"{kind} manage {tab}")

        goto(page, live, f"/admin/user?id={anna.id}")
        expect(page.get_by_test_id("user-name")).to_have_text(anna.name)
        assert_survives_blockers(page, f"{kind} user page")
        page.get_by_test_id("ban").click()
        ban = page.get_by_role("dialog", name=f"„{anna.name}“ sperren?")
        expect(ban).to_be_visible()
        settle_dialogs(page)
        assert_survives_blockers(page, f"{kind} ban sheet")
        ban.get_by_role("button", name="Abbrechen").click()
        expect(ban).to_have_count(0)

        goto(page, live, f"/admin/user?id={troll.id}")
        page.get_by_test_id("unban").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        settle_dialogs(page)
        assert_survives_blockers(page, f"{kind} unban sheet")
        page.keyboard.press("Escape")

        assert errors(page) == []
    finally:
        ctx.close()
