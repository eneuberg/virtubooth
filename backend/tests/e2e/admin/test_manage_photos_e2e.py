"""Manage, Fotos: the contact sheet with filters, multiple selection and bulk actions,
delete only after asking, the inspector and its `?photo=` deep link."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

from ..conftest import LiveServer
from .conftest import (
    Guest,
    card,
    confirm_dialog,
    errors,
    goto,
    no_horizontal_scroll,
    settle,
    toast,
    wait_live,
)

pytestmark = pytest.mark.e2e


def tiles(page: Page):  # type: ignore[no-untyped-def]
    return page.locator("[data-testid=photo-tile]")


def pick(page: Page, testid: str, option: str | re.Pattern[str]) -> None:
    """Choose an option of a React Aria Select."""
    page.get_by_test_id(testid).get_by_role("button").click()
    page.get_by_role("option", name=option).click()


def test_filters_selection_and_bulk_actions(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    a = guests(instagram="anna")
    b = guests()
    a1, a2, b1 = a.upload(), a.upload(), b.upload()
    goto(page, live, "/admin/manage")
    wait_live(page)
    expect(tiles(page)).to_have_count(3)
    expect(page.get_by_test_id("photo-total")).to_have_text("3, davon 0 ausgeblendet")

    # newest first: b1, a2, a1. Select b1, shift-click a2: both, not a1
    card(page, b1).get_by_test_id("select").click()
    card(page, a2).get_by_test_id("select").click(modifiers=["Shift"])
    expect(page.get_by_test_id("bulk-count")).to_have_text("2 ausgewählt")
    page.get_by_test_id("bulk-hide").click()
    expect(page.get_by_test_id("bulkbar")).to_have_count(0)
    expect(toast(page)).to_contain_text("2 Fotos ausgeblendet")
    expect(card(page, b1)).to_have_attribute("data-hidden", "true")
    for pid, hidden in ((b1, True), (a2, True), (a1, False)):
        photo = live.core.repos.photos.get(pid)
        assert photo is not None and photo.hidden is hidden

    # filter: hidden only (in the URL)
    page.get_by_test_id("filter-status").get_by_text("Ausgeblendet", exact=True).click()
    expect(tiles(page)).to_have_count(2)
    assert "status=hidden" in page.url
    # filter: one guest
    pick(page, "filter-user", re.compile(rf"^{re.escape(a.name)} @anna"))
    expect(tiles(page)).to_have_count(1)
    expect(card(page, a2)).to_be_visible()
    assert f"user={a.id}" in page.url
    page.get_by_test_id("filter-status").get_by_text("Alle", exact=True).click()
    expect(tiles(page)).to_have_count(2)

    # bulk delete asks; cancelling keeps the selection
    page.get_by_test_id("select-all").click()
    expect(page.get_by_test_id("bulk-count")).to_have_text("2 ausgewählt")
    page.get_by_test_id("bulk-delete").click()
    dialog = confirm_dialog(page)
    expect(dialog).to_contain_text("2 Fotos endgültig löschen?")
    expect(dialog.get_by_role("button", name="Abbrechen")).to_be_focused()
    dialog.get_by_role("button", name="Abbrechen").click()
    expect(dialog).to_have_count(0)
    expect(page.get_by_test_id("bulk-count")).to_have_text("2 ausgewählt")
    page.get_by_test_id("bulk-delete").click()
    confirm_dialog(page).get_by_role("button", name=re.compile("endgültig löschen")).click()
    expect(tiles(page)).to_have_count(0)
    assert live.core.repos.photos.get(a1) is None and live.core.repos.photos.get(a2) is None
    assert live.core.repos.photos.get(b1) is not None
    assert errors(page) == []


def test_inspector_delete_asks_first(desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]) -> None:
    page = desktop_page
    g = guests(instagram="ben_b")
    keep, doomed = g.upload(), g.upload()
    photo = live.core.repos.photos.get(doomed)
    assert photo is not None
    files = [live.core.repos.photos.path(photo.extension, photo.filename)]
    goto(page, live, "/admin/manage")
    expect(page.get_by_test_id("photo-total")).to_have_text("2, davon 0 ausgeblendet")
    card(page, doomed).click()
    inspector = page.get_by_test_id("inspector")
    expect(inspector.get_by_role("heading", name="Bier 0002")).to_be_visible()
    assert page.url.endswith(f"/admin/manage?photo={doomed}")
    expect(inspector.get_by_test_id("download")).to_have_attribute("href", f"/media/{doomed}?download=1")
    inspector.get_by_test_id("delete").click()
    dialog = confirm_dialog(page)
    expect(dialog).to_contain_text(re.compile(r"Bier.0002. endgültig löschen\?"))
    dialog.get_by_role("button", name="Abbrechen").click()
    assert live.core.repos.photos.get(doomed) is not None

    inspector.get_by_test_id("delete").click()
    confirm_dialog(page).get_by_role("button", name="Endgültig löschen").click()
    expect(card(page, doomed)).to_have_count(0)
    expect(toast(page)).to_contain_text("Foto gelöscht")
    expect(page.get_by_test_id("photo-total")).to_have_text("1, davon 0 ausgeblendet")
    # the inspector moves on to the neighbour
    expect(inspector.get_by_role("heading", name="Bier 0001")).to_be_visible()
    assert live.core.repos.photos.get(doomed) is None
    assert not any(f.exists() for f in files)
    assert live.core.repos.photos.get(keep) is not None
    assert no_horizontal_scroll(page)
    assert errors(page) == []


def test_photo_deep_link_opens_the_inspector(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    g = guests(instagram="dj.dennis")
    shown = g.upload()
    for _ in range(3):
        g.upload()
    # even with a filter that leaves the photo out
    goto(page, live, f"/admin/manage?status=hidden&photo={shown}")
    inspector = page.get_by_test_id("inspector")
    expect(inspector.get_by_role("heading", name="Bier 0001")).to_be_visible()
    expect(inspector).to_contain_text("@dj.dennis")
    expect(inspector).to_contain_text("Flasche")
    inspector.get_by_test_id("toggle").click()
    expect(inspector.get_by_test_id("toggle")).to_have_text("Einblenden")
    inspector.get_by_role("button", name="Schließen").click()
    assert "photo=" not in page.url
    assert errors(page) == []


def test_new_photos_wait_for_the_host(desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]) -> None:
    page = desktop_page
    g = guests()
    g.upload()
    goto(page, live, "/admin/manage")
    wait_live(page)
    expect(tiles(page)).to_have_count(1)
    fresh = g.upload()
    pill = page.get_by_test_id("new-pill")
    expect(pill).to_have_text("1 neues Foto anzeigen")
    expect(card(page, fresh)).to_have_count(0)
    pill.click()
    expect(card(page, fresh)).to_be_visible()
    expect(tiles(page).first).to_have_attribute("data-photo-id", fresh)
    expect(page.get_by_test_id("photo-total")).to_have_text("2, davon 0 ausgeblendet")
    assert errors(page) == []


def test_manage_on_a_phone(admin_page: Page, live: LiveServer, guests: Callable[..., Guest]) -> None:
    g = guests(instagram="phone.user")
    first, doomed = g.upload(), g.upload()
    goto(admin_page, live, "/admin/manage")
    expect(tiles(admin_page)).to_have_count(2)
    assert no_horizontal_scroll(admin_page)
    # a tap opens the full-screen viewer, its delete asks on top of it
    card(admin_page, doomed).click()
    viewer = admin_page.get_by_test_id("lightbox")
    expect(viewer).to_be_visible()
    viewer.get_by_test_id("lightbox-delete").click()
    ok = confirm_dialog(admin_page).get_by_role("button", name="Endgültig löschen")
    expect(ok).to_be_visible()
    settle(admin_page)
    on_top = ok.evaluate(
        """(el) => { const r = el.getBoundingClientRect();
            return el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)); }"""
    )
    assert on_top
    ok.click()
    expect(viewer).to_have_count(0)
    expect(card(admin_page, doomed)).to_have_count(0)
    # the answer and the event both report it: one step back, not two
    admin_page.wait_for_timeout(300)
    assert admin_page.url == live.url("/admin/manage")
    assert live.core.repos.photos.get(first) is not None
    assert errors(admin_page) == []


def test_infinite_scroll_loads_older_photos(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    g = guests()
    ids = [g.upload() for _ in range(55)]
    goto(desktop_page, live, "/admin/manage")
    expect(tiles(desktop_page)).to_have_count(48)
    desktop_page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
    expect(tiles(desktop_page)).to_have_count(55)
    expect(tiles(desktop_page).last).to_have_attribute("data-photo-id", ids[0])
    expect(desktop_page.get_by_test_id("photo-total")).to_have_text("55, davon 0 ausgeblendet")
    assert errors(desktop_page) == []
