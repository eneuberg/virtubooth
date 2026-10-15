"""„Als Gast teilnehmen“: the admin presses the button in the Gäste section, the guest
app opens in a new tab signed in as the admin guest (no QR code), takes a photo with the
Beer Cam, and the admin sees the guest and the photo marked as its admin guest."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, expect

from virtubooth.domain.models import PhotoQuery

from ..conftest import LiveServer, new_context, track_errors, wait_until_ready
from .conftest import errors, goto, login_api, wait_live

pytestmark = pytest.mark.e2e


def test_admin_joins_as_guest_uploads_and_sees_it_marked(browser: Browser, live: LiveServer):
    # a laptop with a webcam: the admin panel and, in a second tab, the guest app
    ctx = new_context(browser, "desktop")
    try:
        page = track_errors(ctx.new_page())
        login_api(page, live)
        goto(page, live, "/admin/manage?tab=gaeste")
        wait_live(page)
        button = page.get_by_role("main").get_by_test_id("host-guest-button")
        expect(button).to_have_text("Als Gast teilnehmen")
        expect(page.get_by_test_id("host-guest-hint")).to_contain_text(
            "„Hochladen stoppen“ gilt aber auch für dich"
        )
        # the sidebar (next to „Live öffnen“) has the same button
        expect(page.get_by_test_id("host-guest-button")).to_have_count(2)

        with ctx.expect_page() as opened:
            button.click()
        guest = track_errors(opened.value)
        guest.wait_for_url(live.url("/"))
        wait_until_ready(guest)
        # signed in right away: no join sheet, no gate, and the pass says who it is
        expect(guest.get_by_test_id("start")).to_be_visible()
        expect(guest.get_by_test_id("join")).to_have_count(0)
        expect(guest.get_by_test_id("guest-pass-host")).to_have_text(
            "Admin-Gast · nur du siehst das"
        )
        host = live.core.repos.users.host()
        assert host is not None and host.code_id is None

        guest.get_by_test_id("tile-beer").click()
        expect(guest.get_by_test_id("beer-app")).to_have_attribute(
            "data-ready", "1", timeout=20_000
        )
        guest.get_by_test_id("shutter").click()
        expect(guest.get_by_test_id("upload-status")).to_have_attribute(
            "data-state", "done", timeout=20_000
        )
        (photo,) = live.core.repos.photos.list(PhotoQuery(user_id=host.id))

        # back in the admin: the button now reopens it, the row is marked
        expect(button).to_have_text("Als Gast öffnen")
        row = page.locator(f'[data-testid=guest-row][data-id="{host.id}"]')
        expect(row.get_by_test_id("host-badge")).to_have_text("Admin-Gast")
        expect(row.get_by_test_id("guest-code")).to_have_text("über die Verwaltung")

        # the photo names its guest as the admin guest (the inspector's „von …“)
        goto(page, live, f"/admin/manage?tab=fotos&photo={photo.public_id}")
        expect(page.get_by_test_id("user-link")).to_have_text(f"{host.name} · Admin-Gast")

        # the user page: marked, and the ban button is off with the reason next to it
        goto(page, live, f"/admin/user?id={host.id}")
        expect(page.get_by_test_id("host-badge")).to_be_visible()
        expect(page.get_by_test_id("ban")).to_be_disabled()
        expect(page.get_by_test_id("host-ban-note")).to_contain_text("lässt sich nicht sperren")
        expect(page.get_by_test_id("user-code")).to_contain_text("über die Verwaltung beigetreten")

        # the live screen's tile
        goto(page, live, "/admin/live")
        expect(page.get_by_test_id("photo-card").first).to_contain_text("Admin-Gast")

        assert errors(page) == []
        assert guest.js_errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()
