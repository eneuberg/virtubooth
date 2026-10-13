"""Content blockers vs. the rendered guest UI: the join sheet, Start (with photos and
a status), the "Du" sheet, the viewer, help, the gate. Element-hiding rules key on
class names, ids and test ids; a hidden join sheet would leave the guest at a page
that never starts. Uses the reusable helper in blockers.py (the old DOM blocker
checks of e2e_legacy, now on the real DOM)."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import LiveServer, accept_consent_in_browser, settle_dialogs
from .blockers import assert_survives_blockers, notice_word_hits, rendered_elements
from .conftest import upload

pytestmark = pytest.mark.e2e


def test_the_helper_is_not_vacuous(page: Page, live: LiveServer):
    """A cookie-banner-like element on our page is caught by the vendored rules,
    and a cookie word in the join sheet by the name check."""
    page.goto(live.entry("/"))
    expect(page.get_by_test_id("join")).to_be_visible()
    page.evaluate(
        """() => { const d = document.createElement('div'); d.dataset.testid = 'consent-banner';
            document.body.append(d);
            document.querySelector('[data-testid=join] [role=dialog]').classList.add('cookie-notice'); }"""
    )
    with pytest.raises(AssertionError, match="consent-banner"):
        assert_survives_blockers(page, "synthetic")
    assert notice_word_hits(rendered_elements(page, "synthetic"))


def test_join_sheet_survives_blockers(page: Page, live: LiveServer):
    page.goto(live.entry("/x/beer/"))
    expect(page.get_by_test_id("join")).to_be_visible()
    settle_dialogs(page)
    page.get_by_role("button", name="Mehr dazu").click()
    assert assert_survives_blockers(page, "join sheet", join=True) > 40


def test_start_and_its_sheets_survive_blockers(page: Page, live: LiveServer):
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    upload(page, "beer")
    upload(page, "booth")
    live.core.services.upload_controls.set_stop(True, actor="admin")
    page.reload()
    expect(page.locator("[data-testid=my-photos] [data-testid^=photo-]")).to_have_count(2)
    expect(page.get_by_test_id("status-slot")).to_be_visible()
    assert assert_survives_blockers(page, "start") > 80

    page.get_by_test_id("guest-pass").click()
    expect(page.get_by_test_id("guest-sheet").get_by_role("dialog")).to_be_visible()
    assert_survives_blockers(page, "du sheet")
    page.keyboard.press("Escape")

    page.get_by_test_id("status-slot").click()
    expect(page.get_by_test_id("status-info").get_by_role("dialog")).to_be_visible()
    assert_survives_blockers(page, "status sheet")
    page.keyboard.press("Escape")

    page.locator("[data-testid^=photo-] button").first.click()
    expect(page.get_by_test_id("photo-viewer").get_by_role("dialog")).to_be_visible()
    assert_survives_blockers(page, "viewer")
    page.keyboard.press("Escape")

    page.get_by_role("button", name="Hilfe").click()
    expect(page.get_by_test_id("help").get_by_role("dialog")).to_be_visible()
    assert_survives_blockers(page, "help")
    assert page.js_errors == []  # type: ignore[attr-defined]


def test_gate_and_banned_survive_blockers(page: Page, live: LiveServer):
    page.goto(live.url("/"))
    expect(page.get_by_test_id("gate")).to_be_visible()
    assert_survives_blockers(page, "gate")
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    [user] = live.core.repos.users.list()
    live.core.services.moderation.ban_user(user.id, actor="admin")
    page.reload()
    expect(page.get_by_test_id("banned")).to_be_visible()
    assert_survives_blockers(page, "banned")
