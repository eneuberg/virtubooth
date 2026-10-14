"""The toast never sits on the buttons the admin needs next. On a phone it used to cover
the viewer's actions (Ausblenden, Löschen…, Gast öffnen), the confirm dialog's
"Endgültig löschen" and the selection bar for its 5-7 s; the next tap waited until it
was gone. Now it moves up above the open sheet, the viewer's panel or the bar (and keeps
its undo). Each test taps right after the toast appears, with a short timeout."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

from ..conftest import QUICK_TAP_MS, LiveServer, covered_by_toast, settle_toast
from .conftest import DESKTOP_VIEWPORT, Guest, card, confirm_dialog, errors, goto, toast, wait_live

pytestmark = pytest.mark.e2e


def undo_reachable(page: Page) -> None:
    """The toast's own button still takes a tap (not under a sheet, on screen)."""
    toast(page).get_by_role("button", name="Rückgängig").click(trial=True, timeout=QUICK_TAP_MS)


def test_live_viewer_buttons_stay_free_under_the_undo_toast(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = admin_page
    g = guests()
    g.upload()
    second = g.upload()
    goto(page, live, "/admin/live")
    wait_live(page)
    card(page, second).locator("figure button").first.click()
    viewer = page.get_by_test_id("lightbox")
    viewer.get_by_role("button", name="Ausblenden").tap()
    expect(toast(page)).to_contain_text("ausgeblendet")
    assert covered_by_toast(page) == []
    undo_reachable(page)
    # the next taps land at once: back in, then on to the older photo
    viewer.get_by_role("button", name="Einblenden").tap(timeout=QUICK_TAP_MS)
    expect(toast(page)).to_contain_text("eingeblendet")
    assert covered_by_toast(page) == []
    viewer.get_by_role("button", name="Älteres Foto").tap(timeout=QUICK_TAP_MS)
    expect(viewer).to_contain_text("Bier 0001")
    viewer.get_by_role("button", name="Ausblenden").tap(timeout=QUICK_TAP_MS)
    expect(toast(page)).to_contain_text("Bier 0001 ausgeblendet")
    viewer.get_by_test_id("lightbox-close").tap(timeout=QUICK_TAP_MS)
    expect(viewer).to_have_count(0)
    assert errors(page) == []


def test_user_viewer_delete_right_after_hiding(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = admin_page
    g = guests(instagram="phone.user")
    keep, doomed = g.upload(), g.upload()
    goto(page, live, f"/admin/user?id={g.id}")
    card(page, doomed).locator("figure button").first.click()
    viewer = page.get_by_test_id("lightbox")
    viewer.get_by_role("button", name="Ausblenden").tap()
    expect(toast(page)).to_contain_text("ausgeblendet")
    assert covered_by_toast(page) == []
    viewer.get_by_test_id("lightbox-delete").tap(timeout=QUICK_TAP_MS)
    # the question opens on top: the toast moves above it, its buttons stay free
    dialog = confirm_dialog(page)
    expect(dialog).to_be_visible()
    assert covered_by_toast(page) == []
    undo_reachable(page)
    dialog.get_by_role("button", name="Endgültig löschen").tap(timeout=QUICK_TAP_MS)
    expect(viewer).to_have_count(0)
    expect(card(page, doomed)).to_have_count(0)
    expect(toast(page)).to_contain_text("Foto gelöscht")
    assert live.core.repos.photos.get(doomed) is None
    assert live.core.repos.photos.get(keep) is not None
    assert errors(page) == []


def test_manage_selection_bar_and_confirm_under_the_toast(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = admin_page
    g = guests()
    a, b = g.upload(), g.upload()
    goto(page, live, "/admin/manage")
    card(page, a).get_by_test_id("select").tap()
    page.get_by_test_id("bulk-hide").tap()
    expect(toast(page)).to_contain_text("ausgeblendet")
    # a new selection while the undo toast still shows: the bar is free
    card(page, b).get_by_test_id("select").tap(timeout=QUICK_TAP_MS)
    bar = page.get_by_test_id("bulkbar")
    buttons = [page.get_by_test_id(f"bulk-{x}") for x in ("hide", "unhide", "delete", "clear")]
    assert covered_by_toast(page, bar, *buttons) == []
    undo_reachable(page)
    page.get_by_test_id("bulk-delete").tap(timeout=QUICK_TAP_MS)
    dialog = confirm_dialog(page)
    expect(dialog).to_be_visible()
    assert covered_by_toast(page) == []
    dialog.get_by_role("button", name="Endgültig löschen").tap(timeout=QUICK_TAP_MS)
    expect(card(page, b)).to_have_count(0)
    assert live.core.repos.photos.get(b) is None
    assert errors(page) == []


def test_desktop_toast_keeps_its_corner_and_clears_the_selection_bar(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    g = guests()
    a, b = g.upload(), g.upload()
    goto(page, live, "/admin/manage")
    wait_live(page)
    card(page, a).get_by_test_id("select").click()
    page.get_by_test_id("bulk-hide").click()
    expect(toast(page)).to_contain_text("ausgeblendet")
    # nothing under it: bottom right, 24 px from the edges, as before
    assert covered_by_toast(page, page.get_by_test_id("photo-total")) == []
    box = toast(page).bounding_box()
    assert box is not None
    assert box["x"] + box["width"] == pytest.approx(DESKTOP_VIEWPORT["width"] - 24, abs=1)
    assert box["y"] + box["height"] == pytest.approx(DESKTOP_VIEWPORT["height"] - 24, abs=1)
    # the selection bar runs along the bottom: the toast stands above its right end
    card(page, b).get_by_test_id("select").click()
    clear = page.get_by_test_id("bulk-clear")
    assert covered_by_toast(page, page.get_by_test_id("bulkbar"), clear) == []
    clear.click(timeout=QUICK_TAP_MS)
    expect(page.get_by_test_id("bulkbar")).to_have_count(0)
    # the bar is gone: back to the corner
    page.get_by_role("button", name="Rückgängig").click()
    expect(toast(page)).to_contain_text(re.compile("eingeblendet"))
    settle_toast(page)
    box = toast(page).bounding_box()
    assert box is not None
    assert box["y"] + box["height"] == pytest.approx(DESKTOP_VIEWPORT["height"] - 24, abs=1)
    assert errors(page) == []


def test_last_row_scrolls_out_from_under_the_toast(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    """While a toast shows, a scrolling grid gets room at the bottom: scrolled to the
    end, its last row sits above the toast instead of under it."""
    page = admin_page
    g = guests()
    ids = [g.upload() for _ in range(10)]
    goto(page, live, "/admin/live")
    wait_live(page)
    oldest = card(page, ids[0])  # newest first: the last tile
    oldest.get_by_test_id("toggle").click()
    expect(toast(page)).to_contain_text("ausgeblendet")
    settle_toast(page)
    page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
    tile = oldest.locator("figure").first.bounding_box()
    region = toast(page).bounding_box()
    assert tile is not None and region is not None
    assert tile["y"] + tile["height"] <= region["y"], (tile, region)
    # gone with the toast
    toast(page).get_by_role("button", name="Schließen").click()
    expect(page.locator("html[data-vb-toast-room]")).to_have_count(0)
    assert errors(page) == []
