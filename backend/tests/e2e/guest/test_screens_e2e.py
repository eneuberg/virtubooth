"""Screenshots of the guest screens at the four review viewports (opt-in):

    VB_SCREENSHOT_DIR=dir uv run pytest tests/e2e/guest/test_screens_e2e.py -m e2e

Start (empty, with photos, paused), the join sheet, the "Du" sheet, the viewer,
banned, the gate and not-found, each at phone 390x844, small 360x640, landscape
844x390 and desktop 1440x900. The photos are the design mockups' synthetic scenes
(no real guests). Every screen must also be free of console errors."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from playwright.sync_api import Page, expect

from ..conftest import (
    BROWSER_NAME,
    LiveServer,
    accept_consent_in_browser,
    join_via_api,
    settle_dialogs,
)
from .conftest import SCREENSHOT_DIR, reload

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not SCREENSHOT_DIR, reason="set VB_SCREENSHOT_DIR=dir"),
]

MOCKUP_IMG = (
    Path(__file__).resolve().parents[4] / "docs" / "overhaul" / "design" / "mockups" / "img"
)
# what the guest shot, oldest first: Deine Bilder shows them newest first
OWN = [
    ("beer", "beer-1"),
    ("booth", "booth-3"),
    ("beer", "beer-2"),
    ("booth", "booth-6"),
    ("beer", "beer-4"),
]


@pytest.fixture
def e2e_settings() -> dict[str, Any]:
    return {"party_name": "Lenas Geburtstag", "instagram_account": "@lenas.party"}


def scene(name: str) -> list[int]:
    img = Image.open(MOCKUP_IMG / f"{name}.jpg").convert("RGB").resize((1080, 1440), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return list(buf.getvalue())


def upload_scene(page: Page, ext: str, name: str) -> None:
    meta = '{"vessel":"bottle"}' if ext == "beer" else '{"filter":"normal","facing":"user"}'
    status = page.evaluate(
        """async ([ext, data, meta]) => (await fetch(`/api/x/${ext}/upload`, {method: 'POST',
            headers: {'Content-Type': 'image/jpeg', 'X-VB-Meta': encodeURIComponent(meta)},
            body: new Uint8Array(data)})).status""",
        [ext, scene(name), meta],
    )
    assert status == 201


def other_beers(live: LiveServer, page: Page, n: int = 28) -> None:
    """Beers of other guests, for a counter that looks like a party (rows only)."""
    join_via_api(page, live)
    [other] = live.core.repos.users.list()
    for i in range(n):
        live.core.repos.photos.insert(
            public_id=f"otherbeer{i:04d}x",
            extension="beer",
            user_id=other.id,
            filename=f"other-{i}.jpg",
            thumb_filename=f"other-{i}-t.jpg",
            width=1080,
            height=1440,
            size=1,
            meta={"vessel": "cup"},
            created_at="2026-10-13T20:00:00.000+00:00",
        )


def snap(page: Page, name: str, view: str, settle_ms: int = 700) -> None:
    page.wait_for_timeout(settle_ms)
    out = Path(SCREENSHOT_DIR)
    out.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out / f"{BROWSER_NAME}_{name}-{view}.png"))


@pytest.mark.parametrize("view", ["phone", "small", "land", "desk"])
def test_guest_screens(make_page, live: LiveServer, view: str):
    other_beers(live, make_page(view))
    page = make_page(view)

    page.goto(live.url("/"))
    expect(page.get_by_test_id("gate")).to_be_visible()
    snap(page, "gate", view, 300)
    page.goto(live.entry("/x/beer/"))
    expect(page.get_by_test_id("join")).to_be_visible()
    settle_dialogs(page)
    snap(page, "join", view)
    accept_consent_in_browser(page)
    page.goto(live.url("/nowhere"))
    expect(page.get_by_test_id("notfound")).to_be_visible()
    snap(page, "notfound", view, 300)

    page.goto(live.url("/"))
    expect(page.get_by_test_id("my-photos-empty")).to_be_visible()
    expect(page.get_by_test_id("beer-count")).to_be_visible()
    snap(page, "start-empty", view)

    for ext, name in OWN:
        upload_scene(page, ext, name)
    me = live.core.repos.users.list()[0]  # newest first: this guest
    live.core.repos.users.set_instagram(me.id, "lena.k")
    reload(page)
    expect(page.locator("[data-testid=my-photos] [data-testid^=photo-]")).to_have_count(len(OWN))
    page.evaluate(
        "() => Promise.all([...document.images].map((i) => i.decode().catch(() => null)))"
    )
    snap(page, "start-photos", view, 900)

    page.get_by_test_id("guest-pass").click()
    expect(page.get_by_test_id("guest-sheet").get_by_role("dialog")).to_be_visible()
    settle_dialogs(page)
    snap(page, "du", view)
    page.keyboard.press("Escape")

    page.locator("[data-testid=my-photos] [data-testid^=photo-] button").nth(1).click()
    expect(page.get_by_test_id("photo-save")).to_be_enabled()
    settle_dialogs(page)
    snap(page, "viewer", view, 900)
    page.keyboard.press("Escape")

    live.core.services.upload_controls.set_user_paused(me.id, True, actor="admin")
    reload(page)
    expect(page.get_by_test_id("status-slot")).to_be_visible()
    page.evaluate(
        "() => Promise.all([...document.images].map((i) => i.decode().catch(() => null)))"
    )
    snap(page, "start-paused", view, 900)

    live.core.services.moderation.ban_user(me.id, actor="admin")
    reload(page)
    expect(page.get_by_test_id("banned")).to_be_visible()
    snap(page, "banned", view, 300)

    assert [e for e in page.js_errors if "404 (Not Found)" not in e] == []  # type: ignore[attr-defined]
