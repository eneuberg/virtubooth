"""Fotobox filters the host switched off: gone from the strip and from Start's count,
and a guest whose filter went away gets the first one.

The booth fetches the catalogue again every 30 s; the page's clock (Playwright's fake
timers, running in real time otherwise) jumps ahead instead of the test waiting."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page, expect

from virtubooth.extensions.booth import FILTERS

from ..conftest import LiveServer, join_via_api
from .conftest import Admin, fonts_ready, open_booth, select_filter

pytestmark = pytest.mark.e2e

IDS = list(FILTERS)
OFF = ("vhs", "comic")
NBSP = " "


@pytest.fixture
def guest(page: Page, live: LiveServer) -> Page:
    """A joined guest on Start whose timers the test can move forward."""
    page.clock.install()
    join_via_api(page, live)
    fonts_ready(page)
    return page


def set_filters(admin: Admin, enabled: list[str]) -> dict[str, Any]:
    res = admin.request.fetch("/api/admin/x/booth/filters", method="PUT", data={"enabled": enabled})
    assert res.ok, (res.status, res.text())
    body: dict[str, Any] = res.json()
    return body


def strip_ids(page: Page) -> list[str]:
    return list(
        page.get_by_test_id("filter-strip")
        .locator("[data-filter]")
        .evaluate_all("els => els.map(e => e.dataset.filter)")
    )


def test_switched_off_filters_leave_the_strip_and_the_count(
    guest: Page, live: LiveServer, admin: Admin
) -> None:
    page = guest
    card_count = page.get_by_text(f"10{NBSP}Filter")
    expect(card_count).to_be_visible()

    open_booth(page, live)
    assert strip_ids(page) == IDS
    select_filter(page, "vhs")

    body = set_filters(admin, [f for f in IDS if f not in OFF])
    assert [f["id"] for f in body["filters"] if not f["enabled"]] == list(OFF)

    # the next refetch (every 30 s): "vhs" is gone, the first filter takes over
    page.clock.fast_forward(31_000)
    booth = page.get_by_test_id("booth")
    expect(booth).to_have_attribute("data-filter", "normal")
    expect(page.get_by_test_id("filter-vhs")).to_have_count(0)
    assert strip_ids(page) == [f for f in IDS if f not in OFF]
    expect(page.get_by_test_id("filter-normal")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_test_id("filter-name")).to_have_text("Normal")

    fonts_ready(page)
    page.goto(live.url("/"))
    expect(page.get_by_text(f"8{NBSP}Filter")).to_be_visible()

    # back on: the next visit of the booth has all ten again
    set_filters(admin, IDS)
    open_booth(page, live)
    assert strip_ids(page) == IDS
    assert page.js_errors == []  # type: ignore[attr-defined]
