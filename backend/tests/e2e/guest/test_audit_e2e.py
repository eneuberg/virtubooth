"""The guest app's main screens through tests/e2e/audit.py (axe, blockers, leaked React
Aria classes) on a phone and on a desktop: the gate, the join sheet, Start empty and
with photos (plus a status), the "Du" sheet, the photo viewer, help, the banned screen.
Serious and critical axe findings fail; `VB_AXE_REPORT=<file>` lists everything."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..audit import Audit
from ..conftest import LiveServer, accept_consent_in_browser, settle_dialogs
from .conftest import errors_besides, reload, upload

pytestmark = pytest.mark.e2e


def test_the_audit_is_not_vacuous(page: Page, live: LiveServer):
    """An image without a text, a leaked React Aria class and a cookie banner: each is
    caught (axe critical, the class check, the blocker rules)."""
    page.goto(live.entry("/"))
    expect(page.get_by_test_id("join")).to_be_visible()
    page.evaluate(
        """() => { const img = document.createElement('img'); img.src = '/icon.svg';
            const leak = document.createElement('div'); leak.className = 'react-aria-Button';
            const banner = document.createElement('div'); banner.dataset.testid = 'consent-banner';
            // inside the open sheet: React Aria hides everything else from assistive tech
            document.querySelector('[role=dialog]').append(img, leak);
            document.body.append(banner); }"""
    )
    audit = Audit("synthetic")
    audit.check(page, "broken")
    found = "\n".join(audit.problems)
    assert "axe critical image-alt" in found, found
    assert "react-aria-Button" in found, found
    assert "consent-banner" in found, found
    with pytest.raises(AssertionError):
        audit.assert_clean()


@pytest.mark.parametrize("view", ["phone", "desk"])
def test_guest_screens(make_page, live: LiveServer, view: str):  # type: ignore[no-untyped-def]
    audit = Audit(f"guest {view}")
    page: Page = make_page(view)

    page.goto(live.url("/"))
    expect(page.get_by_test_id("gate")).to_be_visible()
    audit.check(page, "gate")

    page.goto(live.entry("/"))
    expect(page.get_by_test_id("join")).to_be_visible()
    settle_dialogs(page)
    page.get_by_role("button", name="Mehr dazu").click()
    audit.check(page, "join sheet")
    accept_consent_in_browser(page)
    expect(page.get_by_test_id("my-photos-empty")).to_be_visible()
    expect(page.get_by_test_id("beer-count")).to_be_visible()
    audit.check(page, "start, no photos")

    upload(page, "beer")
    upload(page, "booth")
    live.core.services.upload_controls.set_stop(True, actor="admin")
    reload(page)
    expect(page.locator("[data-testid=my-photos] [data-testid^=photo-]")).to_have_count(2)
    expect(page.get_by_test_id("status-slot")).to_be_visible()
    audit.check(page, "start, photos, uploads stopped")

    page.get_by_test_id("guest-pass").click()
    expect(page.get_by_test_id("guest-sheet").get_by_role("dialog")).to_be_visible()
    settle_dialogs(page)
    audit.check(page, "du sheet")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)

    page.locator("[data-testid^=photo-] button").first.click()
    expect(page.get_by_test_id("photo-viewer").get_by_role("dialog")).to_be_visible()
    settle_dialogs(page)
    audit.check(page, "photo viewer")
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)

    page.get_by_role("button", name="Hilfe").click()
    expect(page.get_by_test_id("help").get_by_role("dialog")).to_be_visible()
    settle_dialogs(page)
    audit.check(page, "help")
    page.keyboard.press("Escape")

    [user] = live.core.repos.users.list()
    live.core.services.moderation.ban_user(user.id, actor="admin")
    reload(page)
    expect(page.get_by_test_id("banned")).to_be_visible()
    audit.check(page, "banned")

    audit.assert_clean()
    # the gate is an HTTP 404 page: the browser logs that, nothing else
    assert errors_besides(page, f"404 (Not Found) @ {live.url('/')}") == []
