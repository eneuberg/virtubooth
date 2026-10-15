"""The analysis on the Live screen: frames on each tile's thumbnail and chips under
it, updated through the event stream when the worker finishes (`photo.analyzed`, no
polling), the full analysis with frames in the viewer, and „Analyse zeigen“
(remembered in the browser, with the frames' legend) to switch it all off. The worker itself is off here: the test does what it does
(`jobs.claim/finish`, like test_ml_live_e2e.py)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

from virtubooth.extensions.wall.enrich import jobs
from virtubooth.extensions.wall.enrich.objects import DetectedObject

from ..conftest import LiveServer, shot
from .conftest import Guest, card, errors, goto, wait_live

pytestmark = pytest.mark.e2e

FACE = {"kind": "face", "x": 0.55, "y": 0.2, "w": 0.2, "h": 0.25, "label": "lächelt", "score": 0.9}
OBJECTS = [
    DetectedObject("bottle", "Flasche", 0.81, (0.1, 0.5, 0.4, 0.3)),
    DetectedObject("cup", "Becher", 0.66, (0.6, 0.6, 0.15, 0.2)),
]


def analyse(
    live: LiveServer,
    public_id: str,
    objs: list[DetectedObject] = OBJECTS,
    frames: list[dict] | None = None,
) -> None:
    """What the worker does for a photo: claim it, store facts, frames and objects."""
    db = live.core.db
    pid = live.core.repos.photos.internal_id(public_id)
    assert pid is not None
    claimed = jobs.claim(db)
    assert claimed is not None and claimed.id == pid
    assert jobs.finish(db, pid, facts={"people": 2.0, "faces": 2.0, "smiles": 1.0},
                       data={"boxes": [FACE] if frames is None else frames,
                             "details": [{"label": "Gesichter", "value": "2"}]},
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
    # the frames lie on the tile too: 2 objects + 1 face, the big bottle with its name
    frames = tile.get_by_test_id("tile-frame")
    expect(frames).to_have_count(3)
    expect(tile.locator("[data-testid=tile-frame][data-kind=face]")).to_have_count(1)
    expect(frames.first).to_have_text("Flasche")
    expect(tile.locator("[data-testid=tile-frame][data-kind=object]").last).to_have_text("")
    # a 3:4 photo fills the 3:4 tile: the frame sits where the box says
    pic = tile.locator("figure > div").first.bounding_box()
    bottle = frames.first.bounding_box()
    assert pic and bottle
    assert abs((bottle["x"] - pic["x"]) / pic["width"] - 0.1) < 0.02
    assert abs(bottle["width"] / pic["width"] - 0.4) < 0.02
    expect(page.get_by_test_id("analysis-legend")).to_contain_text("Objekte")

    # open it (the frames never catch the tap): the frames lie on the photo, the object list says label, score, source
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
    expect(page.get_by_test_id("tile-frame")).to_have_count(0)
    expect(page.get_by_test_id("analysis-legend")).to_have_count(0)
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
    expect(card(page, photo).get_by_test_id("tile-frame")).to_have_count(3)
    assert errors(page) == []


# a few different scenes for the screenshots (objects, faces, hands)
SCENES: list[tuple[list[DetectedObject], list[dict]]] = [
    (
        [DetectedObject("person", "Person", 0.92, (0.05, 0.08, 0.6, 0.9)),
         DetectedObject("bottle", "Flasche", 0.81, (0.55, 0.45, 0.2, 0.4))],
        [FACE | {"x": 0.2, "y": 0.12, "w": 0.22, "h": 0.17},
         {"kind": "hand", "x": 0.5, "y": 0.5, "w": 0.12, "h": 0.1, "label": "", "score": 0.8}],
    ),
    (
        [DetectedObject("cup", "Becher", 0.66, (0.3, 0.55, 0.18, 0.2)),
         DetectedObject("wine glass", "Weinglas", 0.7, (0.6, 0.35, 0.15, 0.3))],
        [FACE, FACE | {"x": 0.15, "y": 0.25, "w": 0.18, "h": 0.15}],
    ),
    ([DetectedObject("cake", "Kuchen", 0.88, (0.1, 0.6, 0.8, 0.35))], []),
]  # fmt: skip


@pytest.mark.parametrize("view", ["desktop", "phone"])
def test_frames_on_every_tile(
    request: pytest.FixtureRequest, live: LiveServer, guests: Callable[..., Guest], view: str
) -> None:
    """Every analysed tile carries its frames (from the one batch of summaries); the
    pending ones none. Screenshots of the grid for the review (VB_SCREENSHOT_DIR)."""
    page: Page = request.getfixturevalue("desktop_page" if view == "desktop" else "admin_page")
    g = guests()
    pending, *photos = [g.upload() for _ in range(7)]
    # the worker takes the newest first
    for i, photo in reversed(list(enumerate(photos))):
        objs, frames = SCENES[i % len(SCENES)]
        analyse(live, photo, objs, frames)
    goto(page, live, "/admin/live")
    wait_live(page)
    for i, photo in enumerate(photos):
        objs, frames = SCENES[i % len(SCENES)]
        expect(card(page, photo).get_by_test_id("tile-frame")).to_have_count(
            len(objs) + len(frames)
        )
    expect(card(page, pending).get_by_test_id("tile-frame")).to_have_count(0)
    expect(page.get_by_test_id("analysis-legend")).to_be_visible()
    page.evaluate(
        "() => Promise.all([...document.images].map((i) => i.decode().catch(() => null)))"
    )
    if view == "phone":  # the grid under the sticky header
        page.evaluate("""() => {
            const feed = document.querySelector('[data-testid=feed]');
            const head = document.querySelector('header').getBoundingClientRect().bottom;
            scrollTo(0, feed.getBoundingClientRect().top + scrollY - head - 8);
        }""")
    shot(page, f"live-frames-{view}", 600)
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
