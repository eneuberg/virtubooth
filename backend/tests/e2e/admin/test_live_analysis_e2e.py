"""The analysis on the Live screen: chips under each tile, updated through the event
stream when the worker finishes (`photo.analyzed`, no polling), the full analysis
with frames in the viewer, and „Analyse zeigen“ (remembered in the browser) to switch
it all off. The worker itself is off here: the test does what it does
(`jobs.claim/finish`, like test_ml_live_e2e.py)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

from virtubooth.extensions.wall.enrich import jobs
from virtubooth.extensions.wall.enrich.objects import DetectedObject

from ..conftest import LiveServer
from .conftest import Guest, card, errors, goto, wait_live

pytestmark = pytest.mark.e2e

FACE = {"kind": "face", "x": 0.55, "y": 0.2, "w": 0.2, "h": 0.25, "label": "lächelt", "score": 0.9}


def analyse(live: LiveServer, public_id: str) -> None:
    """What the worker does for a photo: claim it, store facts, frames and objects."""
    db = live.core.db
    pid = live.core.repos.photos.internal_id(public_id)
    assert pid is not None
    claimed = jobs.claim(db)
    assert claimed is not None and claimed.id == pid
    objs = [
        DetectedObject("bottle", "Flasche", 0.81, (0.1, 0.5, 0.2, 0.3)),
        DetectedObject("cup", "Becher", 0.66, (0.4, 0.6, 0.15, 0.2)),
    ]
    assert jobs.finish(db, pid, facts={"people": 2.0, "faces": 2.0, "smiles": 1.0},
                       data={"boxes": [FACE], "details": [{"label": "Gesichter", "value": "2"}]},
                       versions={"basic": "1"}, objects_found=objs,
                       objects_model="e2e@1")  # fmt: skip


def test_analysis_chips_frames_and_the_switch(
    desktop_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    page = desktop_page
    photo = guests().upload()
    goto(page, live, "/admin/live")
    wait_live(page)
    tile = card(page, photo)
    chips = tile.get_by_test_id("analysis-chips")
    expect(chips).to_have_attribute("data-state", "pending")
    expect(chips).to_have_text("Analyse wartet")
    seen: list[str] = []
    page.on("request", lambda r: seen.append(r.url) if "/photos/analysis" in r.url else None)

    # the worker finishes: the tile updates through the event stream, no reload
    analyse(live, photo)
    expect(chips).to_have_attribute("data-state", "done", timeout=8000)
    expect(chips.locator("[data-chip=people]")).to_have_text("2 Personen")
    expect(chips.locator("[data-chip=smiles]")).to_have_text("1 lächeln")
    expect(chips.locator("[data-chip=objects]")).to_have_text("Flasche, Becher")
    assert len(seen) == 1  # one refetch for the one photo the event named

    # open it: the frames lie on the photo, the object list says label, score, source
    tile.locator("figure button").first.click()
    viewer = page.get_by_test_id("lightbox")
    expect(viewer.get_by_test_id("analysis-state")).to_have_text("fertig")
    expect(viewer.get_by_test_id("analysis-box")).to_have_count(3)  # 2 objects + 1 face
    objects = viewer.get_by_test_id("analysis-object")
    expect(objects).to_have_count(2)
    expect(objects.first).to_contain_text("Flasche")
    expect(objects.first).to_contain_text("lokal")
    # pointing at an object lights its frame
    objects.first.hover()
    expect(viewer.locator("[data-testid=analysis-box][data-lit]")).to_have_attribute(
        "data-object", "0"
    )
    page.keyboard.press("Escape")
    expect(viewer).to_have_count(0)

    # „Analyse zeigen“ off: no chips, no frames, no analysis block; remembered
    page.get_by_test_id("analysis-toggle").click()
    expect(page.get_by_test_id("analysis-chips")).to_have_count(0)
    tile.locator("figure button").first.click()
    expect(viewer).to_be_visible()
    expect(viewer.get_by_test_id("analysis")).to_have_count(0)
    expect(viewer.get_by_test_id("analysis-box")).to_have_count(0)
    page.keyboard.press("Escape")
    page.reload()
    wait_live(page)
    expect(card(page, photo)).to_be_visible()
    expect(page.get_by_role("switch", name="Analyse zeigen")).not_to_be_checked()
    expect(page.get_by_test_id("analysis-chips")).to_have_count(0)
    page.get_by_test_id("analysis-toggle").click()
    expect(card(page, photo).get_by_test_id("analysis-chips")).to_contain_text("Flasche")
    assert errors(page) == []


def test_opt_out_marks_on_the_tile(
    admin_page: Page, live: LiveServer, guests: Callable[..., Guest]
) -> None:
    g = guests()
    photo = g.upload()
    with live.core.db.tx() as c:
        c.execute("UPDATE users SET analysis_opt_out=1, ai_opt_out=1 WHERE id=?", (g.id,))
    goto(admin_page, live, "/admin/live")
    wait_live(admin_page)
    chips = card(admin_page, photo).get_by_test_id("analysis-chips")
    expect(chips.locator("[data-chip=opt-out]")).to_have_text("Keine Auswertung (Gast)")
    expect(chips.locator("[data-chip=no-ai]")).to_have_text("Keine externe KI")
    assert errors(admin_page) == []
