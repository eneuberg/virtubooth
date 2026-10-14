"""The Live-Wall end to end against the real backend (no fakes): the host sets the
wall password in the admin, a TV logs in on /livewall, a guest's photo appears
(delay 0 s), hiding it in the admin takes it off the wall at once, and changing the
password logs the wall out. The analysis worker is off (VB_WALL_WORKER=off)."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, expect

from ..admin.conftest import (
    DESKTOP_VIEWPORT,
    Guest,
    admin_context,
    card,
    errors,
    goto,
    login_api,
    toast,
    wait_live,
)
from ..conftest import LOADED, LiveServer, track_errors, wait_until_ready
from .conftest import TV, js_errors

pytestmark = pytest.mark.e2e

PASSWORD = "wall-geheim-1"


@pytest.fixture
def admin(browser: Browser, live: LiveServer) -> Iterator[Page]:
    ctx = admin_context(browser, DESKTOP_VIEWPORT)
    page = track_errors(ctx.new_page())
    login_api(page, live)
    yield page
    ctx.close()


@pytest.fixture
def tv(browser: Browser, live: LiveServer) -> Iterator[Page]:
    ctx = browser.new_context(**TV)
    yield track_errors(ctx.new_page())
    ctx.close()


def set_password(admin: Page, live: LiveServer, password: str) -> None:
    goto(admin, live, "/admin/manage?tab=livewall")
    admin.get_by_label("Live-Wall-Passwort").fill(password)
    admin.get_by_test_id("wall-password-submit").click()
    expect(admin.get_by_test_id("wall-password-status")).to_have_text(
        re.compile(r"^Passwort gesetzt am .+\.$")
    )


def still_wall(admin: Page, live: LiveServer) -> None:
    """Delay 0 s and a spotlight that keeps the newest photo (through the admin API)."""
    api = admin.context.request
    config = api.get(live.url("/api/x/wall/admin/config")).json()["config"]
    config["delay_s"] = 0
    config["spotlight"] |= {"algorithm": "newest", "interval_s": 60, "transition": "crossfade"}
    r = api.put(
        live.url("/api/x/wall/admin/config"), data=config, headers={"Origin": live.base_url}
    )
    assert r.ok, r.text()


def test_wall_with_the_real_backend(admin: Page, tv: Page, live: LiveServer) -> None:
    set_password(admin, live, PASSWORD)
    still_wall(admin, live)

    tv.goto(live.url("/livewall"), wait_until=LOADED)
    wait_until_ready(tv)
    login = tv.get_by_test_id("wall-login")
    login.get_by_label("Passwort").fill(PASSWORD)
    login.get_by_role("button", name="Live-Wall starten").click()
    expect(tv.get_by_test_id("wall-empty")).to_contain_text("Noch keine Fotos.")

    # a guest's photo shows up on its own (stream: photo.add after the 0 s delay)
    guest = Guest(live)
    try:
        photo_id = guest.upload()
    finally:
        guest.client.close()
    slide = tv.locator(".wall-stage .wall-slide").last
    expect(slide).to_have_attribute("data-photo", photo_id, timeout=10_000)
    expect(slide.locator("img")).to_have_js_property("complete", True)
    expect(tv.get_by_test_id("wall-corner")).to_contain_text("1 Foto")

    # hidden in the admin: off the wall at once
    goto(admin, live, "/admin/live")
    wait_live(admin)
    card(admin, photo_id).get_by_role("button", name=re.compile("ausblenden$")).click()
    expect(toast(admin)).to_contain_text("ausgeblendet")
    expect(tv.locator(f".wall-slide[data-photo={photo_id}]")).to_have_count(0, timeout=5000)
    expect(tv.get_by_test_id("wall-empty")).to_contain_text("Noch keine Fotos.")

    # a new password logs every wall out (`bye`): back to the login
    set_password(admin, live, PASSWORD + "-neu")
    expect(tv.get_by_test_id("wall-login")).to_be_visible(timeout=10_000)
    assert js_errors(tv, 401) == []
    assert errors(admin) == []
