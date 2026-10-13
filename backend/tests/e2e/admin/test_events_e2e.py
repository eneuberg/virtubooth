"""The admin event stream from the browser's side (contracts/api.md §4): a stream that
falls behind is ended by the server; the browser reconnects with Last-Event-ID and gets
the missed events replayed, or `stream.resync` when they are gone, and refetches. A
stream whose session ended sends the page to the login."""

from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, Request, expect

from virtubooth.api.routers.admin import events as events_router

from ..conftest import LiveServer
from .conftest import Guest, card, errors, goto, wait_live

pytestmark = pytest.mark.e2e

STOP = {"upload_stop": {"enabled": False, "since": None, "by": None}}


def flood(live: LiveServer, n: int = 400) -> None:
    """More events than an open stream may lag behind (256): it is dropped and ends."""
    for _ in range(n):
        live.core.bus.publish("settings.upload_stop", STOP)


def wait_dropped(live: LiveServer, before: int) -> None:
    deadline = time.monotonic() + 5
    while live.core.bus.subscriber_count >= before:
        assert time.monotonic() < deadline, "the stream was not dropped"
        time.sleep(0.02)


def test_reconnect_replays_what_was_missed(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    g = guests()
    pid = g.upload()
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)
    lists: list[Request] = []
    admin_page.on("request", lambda r: lists.append(r) if "/api/admin/photos?" in r.url else None)
    subscribers = live.core.bus.subscriber_count
    flood(live)
    wait_dropped(live, subscribers)
    # happens while the browser is away; the server keeps it in its history
    live.core.services.moderation.hide_photo(pid, actor="pytest")
    expect(card(admin_page, pid).locator("figure")).to_have_attribute("data-hidden", "true", timeout=15_000)
    expect(admin_page.get_by_test_id("conn")).to_have_attribute("data-state", "live")
    # replayed, not refetched
    assert lists == []
    assert errors(admin_page) == []


def test_resync_after_a_gap(admin_page: Page, live: LiveServer, guests: Callable[..., Guest]) -> None:
    g = guests()
    pid = g.upload()
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)
    subscribers = live.core.bus.subscriber_count
    flood(live)
    wait_dropped(live, subscribers)
    # what the browser missed is no longer kept: it gets `stream.resync` and refetches
    live.core.bus._history = deque(maxlen=1)  # type: ignore[attr-defined]
    live.core.services.moderation.hide_photo(pid, actor="pytest")
    flood(live, 3)
    fresh = g.upload()
    expect(card(admin_page, pid).locator("figure")).to_have_attribute("data-hidden", "true", timeout=15_000)
    expect(card(admin_page, fresh)).to_be_visible()
    expect(admin_page.get_by_test_id("conn")).to_have_attribute("data-state", "live")
    assert errors(admin_page) == []


def test_a_server_restart_means_resync(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    g = guests()
    pid = g.upload()
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)
    subscribers = live.core.bus.subscriber_count
    flood(live)
    wait_dropped(live, subscribers)
    live.core.bus.epoch = "0badcafe"  # ids of the old process are stale now
    live.core.services.moderation.hide_photo(pid, actor="pytest")
    expect(card(admin_page, pid).locator("figure")).to_have_attribute("data-hidden", "true", timeout=15_000)
    assert errors(admin_page) == []


def test_the_end_of_the_session_leads_to_the_login(
    admin_page: Page, live: LiveServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events_router, "SESSION_RECHECK_SECONDS", 0.0)
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)
    other = admin_page.context.new_page()
    other.goto(live.url("/admin/login"))
    assert other.evaluate("async () => (await fetch('/api/admin/logout', {method: 'POST'})).status") == 200
    other.close()
    admin_page.wait_for_url(re.compile(r"/admin/login\?next=%2Fadmin%2Flive$"), timeout=20_000)
    # the refused stream (401) is logged by the browser: expected here, nothing else
    assert [e for e in errors(admin_page, 401) if "/api/admin/events" not in e] == []
