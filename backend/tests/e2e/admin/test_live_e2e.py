"""The live screen (/admin/live): new photos arrive through the event stream, one tap
hides (with undo), and it can never delete (BRIEF invariant)."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Browser, Page, Request, expect

from ..conftest import LiveServer, join_via_api, new_context, track_errors
from .conftest import (
    DESKTOP_VIEWPORT,
    LANDSCAPE_VIEWPORT,
    Guest,
    admin_context,
    card,
    errors,
    goto,
    login_api,
    no_horizontal_scroll,
    toast,
    upload_from_page,
    wait_live,
)

pytestmark = pytest.mark.e2e


def test_new_photo_arrives_live_via_the_event_stream(
    admin_page: Page, browser: Browser, live: LiveServer
) -> None:
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)
    expect(admin_page.get_by_test_id("empty")).to_be_visible()

    guest_ctx = new_context(browser)
    try:
        guest = guest_ctx.new_page()
        join_via_api(guest, live, instagram="anna.party")
        first = upload_from_page(guest)
        assert first["status"] == 201, first
        expect(card(admin_page, first["id"])).to_be_visible(timeout=5000)
        second = upload_from_page(guest, 80)
        expect(card(admin_page, second["id"])).to_be_visible(timeout=5000)
    finally:
        guest_ctx.close()
    # newest on top, counted in the header, never through polling
    cards = admin_page.locator("[data-testid=photo-card]")
    expect(cards.first).to_have_attribute("data-photo-id", second["id"])
    expect(admin_page.get_by_test_id("stat-photos")).to_have_text("2")
    expect(card(admin_page, second["id"])).to_contain_text("Bier 0002")
    expect(admin_page.get_by_test_id("conn")).to_have_attribute("data-state", "live")
    assert errors(admin_page) == []


def test_hide_and_unhide_with_undo(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    g = guests()
    older, newer = g.upload(), g.upload()
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)
    tile = card(admin_page, newer)
    tile.get_by_role("button", name="Bier 0002 ausblenden").click()
    expect(tile.locator("figure")).to_have_attribute("data-hidden", "true")
    expect(tile).to_contain_text("Ausgeblendet")
    expect(toast(admin_page)).to_contain_text("Bier 0002 ausgeblendet")
    photo = live.core.repos.photos.get(newer)
    assert photo is not None and photo.hidden
    expect(admin_page.get_by_test_id("stat-hidden")).to_have_text("1")

    # the undo window
    admin_page.get_by_role("button", name="Rückgängig").click()
    expect(tile.locator("figure")).not_to_have_attribute("data-hidden", "true")
    expect(toast(admin_page)).to_contain_text("Bier 0002 eingeblendet")
    photo = live.core.repos.photos.get(newer)
    assert photo is not None and not photo.hidden

    # and the toggle itself both ways
    tile.get_by_test_id("toggle").click()
    expect(tile.get_by_role("button", name="Bier 0002 einblenden")).to_be_visible()
    tile.get_by_role("button", name="Bier 0002 einblenden").click()
    expect(tile.get_by_role("button", name="Bier 0002 ausblenden")).to_be_focused()
    photo = live.core.repos.photos.get(newer)
    assert photo is not None and not photo.hidden
    assert live.core.repos.photos.get(older) is not None
    expect(admin_page.get_by_test_id("stat-hidden")).to_have_text("0")
    assert no_horizontal_scroll(admin_page)
    assert errors(admin_page) == []


def test_live_has_no_delete_and_sends_no_delete(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    g = guests(instagram="dj.dennis")
    first, second = g.upload(), g.upload()
    sent: list[Request] = []
    admin_page.on("request", lambda r: sent.append(r))
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)
    # every control the screen offers: toggles, the viewer and its actions
    card(admin_page, first).get_by_test_id("toggle").click()
    expect(card(admin_page, first).locator("figure")).to_have_attribute("data-hidden", "true")
    card(admin_page, second).locator("figure button").first.click()
    viewer = admin_page.get_by_test_id("lightbox")
    expect(viewer).to_be_visible()
    expect(viewer).to_contain_text("Bier 0002")
    viewer.get_by_role("button", name="Älteres Foto").click()
    expect(viewer).to_contain_text("Bier 0001")
    viewer.get_by_role("button", name="Einblenden").click()
    expect(viewer.get_by_role("button", name="Ausblenden")).to_be_visible()
    assert viewer.get_by_text(re.compile("Löschen")).count() == 0
    viewer.get_by_test_id("lightbox-close").click()
    expect(viewer).to_have_count(0)

    assert admin_page.get_by_text(re.compile("Löschen")).count() == 0
    assert admin_page.locator("[data-testid*=delete]").count() == 0
    assert [r.url for r in sent if r.method == "DELETE"] == []
    assert [r.url for r in sent if "/bulk" in r.url] == []
    assert live.core.repos.photos.get(first) is not None
    assert live.core.repos.photos.get(second) is not None
    assert errors(admin_page) == []


def test_live_screens_stay_in_sync(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    g = guests()
    pid, other = g.upload(), g.upload()
    goto(admin_page, live, "/admin/live")
    second = track_errors(admin_page.context.new_page())
    goto(second, live, "/admin/live")
    for p in (admin_page, second):
        wait_live(p)
    card(admin_page, pid).get_by_test_id("toggle").click()
    expect(card(second, pid).locator("figure")).to_have_attribute("data-hidden", "true")
    # a deletion in the manage area disappears from the live screen
    status = second.evaluate(
        "async (id) => (await fetch('/api/admin/photos/' + id, {method: 'DELETE'})).status", other
    )
    assert status == 200
    expect(card(admin_page, other)).to_have_count(0)
    expect(admin_page.get_by_test_id("stat-photos")).to_have_text("1")
    assert errors(admin_page) == [] and errors(second) == []


def test_live_falls_back_to_polling(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    admin_page.route("**/api/admin/events**", lambda route: route.abort())
    g = guests()
    goto(admin_page, live, "/admin/live")
    expect(admin_page.get_by_test_id("empty")).to_be_visible()
    expect(admin_page.get_by_test_id("conn")).to_have_attribute(
        "data-state", re.compile("reconnecting|polling"), timeout=8000
    )
    pid = g.upload()
    expect(card(admin_page, pid)).to_be_visible(timeout=12_000)
    real = [e for e in errors(admin_page) if "/api/admin/events" not in e and "EventSource" not in e]
    assert real == []


def test_viewer_deep_link_and_back_button(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    pid = guests().upload()
    goto(admin_page, live, "/admin/live")
    card(admin_page, pid).locator("figure button").first.click()
    expect(admin_page.get_by_test_id("lightbox")).to_be_visible()
    assert admin_page.url == live.url(f"/admin/live?photo={pid}")
    expect(admin_page.get_by_test_id("lightbox-close")).to_be_focused()
    admin_page.go_back()
    expect(admin_page.get_by_test_id("lightbox")).to_have_count(0)
    assert admin_page.url == live.url("/admin/live")
    # focus is back on the photo it showed
    expect(card(admin_page, pid).locator("figure button").first).to_be_focused()
    # the link itself opens it
    goto(admin_page, live, f"/admin/live?photo={pid}")
    expect(admin_page.get_by_test_id("lightbox")).to_be_visible()
    admin_page.keyboard.press("Escape")
    expect(admin_page.get_by_test_id("lightbox")).to_have_count(0)
    assert admin_page.url == live.url("/admin/live")
    assert errors(admin_page) == []


def test_infinite_scroll_and_the_new_photos_pill(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    g = guests()
    ids = [g.upload() for _ in range(40)]
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)
    cards = admin_page.locator("[data-testid=photo-card]")
    expect(cards).to_have_count(30)
    admin_page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
    expect(cards).to_have_count(40)
    assert cards.last.get_attribute("data-photo-id") == ids[0]
    # further down, a new photo waits behind the pill instead of shifting the grid
    fresh = g.upload()
    pill = admin_page.get_by_test_id("new-pill")
    expect(pill).to_have_text("1 neues Foto")
    expect(card(admin_page, fresh)).to_have_count(0)
    pill.click()
    expect(card(admin_page, fresh)).to_be_visible()
    expect(cards.first).to_have_attribute("data-photo-id", fresh)
    assert errors(admin_page) == []


@pytest.mark.parametrize("viewport", ["landscape", "desktop"])
def test_live_layouts(browser: Browser, live: LiveServer, guests: Callable[..., Guest], viewport: str) -> None:
    g = guests(instagram="a.very.long.handle.for_layout1")
    for _ in range(6):
        g.upload()
    size = LANDSCAPE_VIEWPORT if viewport == "landscape" else DESKTOP_VIEWPORT
    ctx = admin_context(browser, size)
    try:
        page = track_errors(ctx.new_page())
        login_api(page, live)
        goto(page, live, "/admin/live")
        wait_live(page)
        expect(page.locator("[data-testid=photo-card]")).to_have_count(6)
        nav = page.get_by_role("navigation", name="Bereiche")
        if viewport == "landscape":
            # the bottom bar is a rail on the left, the grid keeps its height
            box = nav.bounding_box()
            assert box is not None and box["x"] == 0 and box["height"] > box["width"]
        else:
            expect(nav).to_have_count(0)
            expect(page.get_by_role("link", name="Verwaltung")).to_be_visible()
        assert no_horizontal_scroll(page)
        assert errors(page) == []
    finally:
        ctx.close()
