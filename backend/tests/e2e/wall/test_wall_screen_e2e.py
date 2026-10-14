"""The Live-Wall screen (/livewall, W2) against a faked screen API (conftest.WallFake):
login and no-password screens, a spotlight photo with its caption, removals and live
config from the stream, the idle fullscreen button, and no JS/CSP errors.

`test_wall_screenshots` only runs with VB_SCREENSHOT_DIR set (1920×1080 shots of every
mode for the design review, one of them in the middle of a transition).
"""

from __future__ import annotations

import re
import time
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from ..conftest import BROWSER_NAME, LOADED, shot, wait_until_ready
from .conftest import PASSWORD, WallFake, css_var, js_errors, shots_dir, wall_photo

pytestmark = pytest.mark.e2e

# deterministic spotlight: the newest photo first, no change during a test
STILL = {
    "algorithm": "newest",
    "n": 12,
    "interval_s": 60,
    "transition": "crossfade",
    "transition_ms": 400,
}


def open_wall(page: Page, fake: WallFake) -> None:
    page.goto(fake.url(), wait_until=LOADED)
    wait_until_ready(page)


def shown_photo(page: Page) -> Any:
    return page.locator(".wall-stage .wall-slide").last


def test_no_password_screen(tv_page: Page, wall_fake: WallFake) -> None:
    wall_fake.session = "nopassword"
    open_wall(tv_page, wall_fake)
    screen = tv_page.get_by_test_id("wall-no-password")
    expect(screen).to_contain_text("Für die Live-Wall ist noch kein Passwort gesetzt.")
    expect(screen).to_contain_text("Im Admin unter „Live-Wall“ ein Passwort setzen")
    assert js_errors(tv_page, 409) == []


def test_login_then_spotlight_photo(tv_page: Page, wall_fake: WallFake) -> None:
    wall_fake.config["spotlight"] = dict(STILL)
    wall_fake.add(wall_photo(1, "Max"))
    wall_fake.add(wall_photo(2, "Lena", instagram="lena.knipst"))
    open_wall(tv_page, wall_fake)

    login = tv_page.get_by_test_id("wall-login")
    expect(login.get_by_role("heading")).to_have_text("Live-Wall")
    login.get_by_label("Passwort").fill("falsch")
    login.get_by_role("button", name="Live-Wall starten").click()
    expect(login.get_by_role("alert")).to_have_text("Das Passwort stimmt nicht.")

    login.get_by_label("Passwort").fill(PASSWORD)
    login.get_by_role("button", name="Live-Wall starten").click()
    slide = shown_photo(tv_page)
    expect(slide).to_have_attribute("data-photo", "ph0002")
    expect(slide.locator(".wall-caption")).to_contain_text("von Lena")
    expect(slide.locator(".wall-caption")).to_contain_text("@lena.knipst")
    expect(slide.locator(".wall-caption")).to_contain_text("vor 3 Min.")
    expect(slide.locator("img")).to_have_js_property("complete", True)
    corner = tv_page.get_by_test_id("wall-corner")
    expect(corner).to_contain_text("E2E Party")
    expect(corner).to_contain_text("2 Fotos")
    assert js_errors(tv_page, 401, 403) == []


def test_removing_the_shown_photo_takes_it_off_at_once(tv_page: Page, wall_fake: WallFake) -> None:
    wall_fake.session = "ok"
    wall_fake.config["spotlight"] = dict(STILL)
    wall_fake.add(wall_photo(1, "Max"))
    wall_fake.add(wall_photo(2, "Lena"))
    open_wall(tv_page, wall_fake)
    expect(shown_photo(tv_page)).to_have_attribute("data-photo", "ph0002")

    wall_fake.remove("ph0002")
    expect(tv_page.locator(".wall-slide[data-photo=ph0002]")).to_have_count(0, timeout=5000)
    expect(shown_photo(tv_page)).to_have_attribute("data-photo", "ph0001")
    expect(tv_page.get_by_test_id("wall-corner")).to_contain_text("1 Foto")

    # the last one goes too: the empty screen
    wall_fake.remove("ph0001")
    expect(tv_page.get_by_test_id("wall-empty")).to_contain_text("Noch keine Fotos.", timeout=5000)
    assert js_errors(tv_page) == []


def test_config_event_changes_the_look(tv_page: Page, wall_fake: WallFake) -> None:
    wall_fake.session = "ok"
    wall_fake.config["spotlight"] = dict(STILL)
    wall_fake.add(wall_photo(1, "Max"))
    open_wall(tv_page, wall_fake)
    expect(shown_photo(tv_page)).to_have_attribute("data-photo", "ph0001")
    assert css_var(tv_page, "--wall-primary") == "#a855f7"

    wall_fake.set_config(
        look={"primary": "#22c55e", "preset": "disco"}, overlay={"corner": "top-left"}
    )
    deadline = time.monotonic() + 5
    while css_var(tv_page, "--wall-primary") != "#22c55e":
        assert time.monotonic() < deadline, "--wall-primary did not change"
        tv_page.wait_for_timeout(100)
    expect(tv_page.get_by_test_id("wall-corner")).to_have_attribute("data-corner", "top-left")
    assert js_errors(tv_page) == []


def test_fullscreen_button_hides_when_idle(tv_page: Page, wall_fake: WallFake) -> None:
    wall_fake.session = "ok"
    wall_fake.config["spotlight"] = dict(STILL)
    wall_fake.add(wall_photo(1, "Max"))
    open_wall(tv_page, wall_fake)
    if not tv_page.evaluate("() => document.fullscreenEnabled === true"):
        pytest.skip(f"no Fullscreen API in headless {BROWSER_NAME}")
    button = tv_page.get_by_test_id("wall-fullscreen")
    tv_page.mouse.move(200, 200)
    tv_page.mouse.move(260, 240)
    expect(button).to_be_visible()
    expect(button).to_have_text("Vollbild")
    expect(button).to_be_hidden(timeout=6000)
    assert tv_page.evaluate("() => document.querySelector('.wall').hasAttribute('data-idle')")
    tv_page.mouse.move(300, 300)
    expect(button).to_be_visible()
    assert js_errors(tv_page) == []


def test_playlist_rotates_through_the_modes(tv_page: Page, wall_fake: WallFake) -> None:
    wall_fake.session = "ok"
    for n in range(1, 8):
        wall_fake.add(wall_photo(n, ["Lena", "Max", "Ali"][n % 3]))
    wall_fake.categories = [
        {
            "id": "volles_haus",
            "emoji": "👥",
            "title": "Volles Haus",
            "line": "Die meisten Leute auf einem Foto",
            "winners": [{"photo": wall_fake.photos[2], "value": 7, "label": "7 Personen"}],
        }
    ]
    # shorter than the admin allows (10 s): the screen does not check
    wall_fake.config["playlist"] = [
        {"mode": m, "enabled": True, "duration_s": 2}
        for m in ("spotlight", "gallery", "categories")
    ]
    open_wall(tv_page, wall_fake)
    # the mode that ends fades out (data-leaving) while the next one comes in
    mode = tv_page.locator(".wall-mode:not([data-leaving])")
    leaving = tv_page.locator(".wall-mode[data-leaving]")
    expect(mode).to_have_attribute("data-mode", "spotlight")
    expect(mode).to_have_attribute("data-mode", "gallery", timeout=6000)
    expect(leaving).to_have_attribute("data-mode", "spotlight")
    expect(leaving).to_have_count(0, timeout=3000)
    expect(tv_page.locator(".wall-tile img").first).to_have_attribute(
        "src", re.compile(r"/livewall/media/")
    )
    expect(mode).to_have_attribute("data-mode", "categories", timeout=6000)
    expect(tv_page.get_by_test_id("wall-category")).to_contain_text("Volles Haus")
    expect(tv_page.get_by_test_id("wall-category")).to_contain_text("7 Personen")
    expect(mode).to_have_attribute("data-mode", "spotlight", timeout=6000)
    assert js_errors(tv_page) == []


CORNERS = ("bottom-right", "bottom-left", "top-left", "top-right")


def _boxes_overlap(a: dict[str, float], b: dict[str, float]) -> bool:
    return (
        a["x"] < b["x"] + b["width"]
        and a["x"] + a["width"] > b["x"]
        and a["y"] < b["y"] + b["height"]
        and a["y"] + a["height"] > b["y"]
    )


@pytest.mark.parametrize("aspect", ["landscape", "portrait"])
def test_caption_stays_clear_of_the_corner(tv_page: Page, wall_fake: WallFake, aspect: str) -> None:
    """In every corner, with the QR code, a long event name and a long caption."""
    wall_fake.session = "ok"
    wall_fake.event_name = "Sommerfest der Abteilung 2026"
    wall_fake.qr = {"url": "/?t=abc", "name": "Eingang"}
    wall_fake.config["spotlight"] = dict(STILL)
    wall_fake.config["show_instagram"] = True
    wall_fake.config["overlay"] = {**wall_fake.config["overlay"], "qr": True}
    photo = wall_photo(1, "Funky Flamingo mit Sonnenbrille", instagram="flamingo.party.2026")
    if aspect == "landscape":
        photo |= {"width": 1600, "height": 900}
    wall_fake.add(photo)
    open_wall(tv_page, wall_fake)
    caption = tv_page.locator(".wall-stage .wall-slide .wall-caption").last
    corner = tv_page.get_by_test_id("wall-corner")
    expect(tv_page.get_by_test_id("wall-qr")).to_be_visible()
    for name in CORNERS:
        if name != "bottom-right":
            wall_fake.set_config(overlay={"corner": name})
        expect(corner).to_have_attribute("data-corner", name, timeout=5000)
        tv_page.wait_for_timeout(300)  # the card is fitted again after the config event
        cap, box = caption.bounding_box(), corner.bounding_box()
        assert cap and box
        assert not _boxes_overlap(cap, box), f"caption under the {name} corner: {cap} / {box}"
    assert js_errors(tv_page) == []


# ------------------------------------------------------------------ screenshots

CATEGORY_NAMES = [
    ("volles_haus", "👥", "Volles Haus", "Die meisten Leute auf einem Foto", "7 Personen"),
    ("grinsekatzen", "😁", "Grinsekatzen", "Die meisten Lächeln auf einem Bild", "5 Lächeln"),
    ("prost", "🥂", "Prost!", "Die meisten Gläser im Bild", "4 Gläser"),
]
GUESTS = ["Lena", "Max", "Funky Flamingo", "Ali", "Sophie", "Tom", "Mia", "Jonas"]


def _seed_party(fake: WallFake) -> None:
    fake.session = "ok"
    fake.hold_stream = True  # quiet stream: no reconnects, no offline hint in the shots
    fake.event_name = "Sommerfest 2026"
    for n in range(1, 15):
        author = GUESTS[n % len(GUESTS)]
        fake.add(
            wall_photo(
                n,
                author,
                instagram="lena.knipst" if author == "Lena" else None,
                minutes_ago=30 - 2 * n,
            )
        )
    by_id = {p["id"]: p for p in fake.photos}
    fake.categories = [
        {
            "id": cid,
            "emoji": emoji,
            "title": title,
            "line": line,
            "winners": [
                {"photo": by_id[f"ph{(i * 3 + k + 2):04d}"], "value": 7 - k, "label": label}
                for k in range(min(i + 1, 3))
            ],
        }
        for i, (cid, emoji, title, line, label) in enumerate(CATEGORY_NAMES)
    ]


def _only(mode: str) -> list[dict[str, Any]]:
    return [
        {"mode": m, "enabled": m == mode, "duration_s": 600}
        for m in ("spotlight", "gallery", "categories")
    ]


def _wait_transition(page: Page, kind: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while (
        page.evaluate("() => document.querySelector('.wall-stage')?.dataset.transition ?? ''")
        != kind
    ):
        assert time.monotonic() < deadline, f"no {kind} transition"
        page.wait_for_timeout(30)


def _wait_settled(page: Page, timeout: float = 15.0) -> None:
    """A slide is shown and no transition runs."""
    deadline = time.monotonic() + timeout
    script = """() => { const s = document.querySelector('.wall-stage');
        return !!s && s.children.length === 1 && !s.dataset.transition; }"""
    while not page.evaluate(script):
        assert time.monotonic() < deadline, "the spotlight never settled"
        page.wait_for_timeout(30)


@pytest.mark.skipif(shots_dir() is None, reason="set VB_SCREENSHOT_DIR=dir")
def test_wall_screenshots(tv_page: Page, wall_fake: WallFake) -> None:
    page = tv_page
    # login screen
    wall_fake.session = "login"
    open_wall(page, wall_fake)
    page.get_by_test_id("wall-login").wait_for()
    shot(page, "wall_login", 1200)

    # empty wall
    wall_fake.session = "ok"
    wall_fake.hold_stream = True
    page.reload(wait_until=LOADED)
    page.get_by_test_id("wall-empty").wait_for()
    shot(page, "wall_empty", 1200)

    _seed_party(wall_fake)
    # spotlight: settled, then mid-transition for a few kinds (each with another background)
    looks = {
        "polaroid": "blobs",
        "pixelate": "aurora",
        "glitch": "disco",
        "confetti": "confetti",
        "stamp": "blobs",
    }
    for kind, preset in looks.items():
        wall_fake.config["playlist"] = _only("spotlight")
        wall_fake.config["spotlight"] = {
            "algorithm": "shuffle",
            "n": 12,
            "interval_s": 8 if kind == "polaroid" else 3,  # time for a settled shot
            "transition": kind,
            "transition_ms": 2400,
        }
        wall_fake.config["look"] = {**wall_fake.config["look"], "preset": preset}
        page.reload(wait_until=LOADED)
        page.locator(".wall-stage .wall-slide").first.wait_for()
        if kind == "polaroid":
            _wait_settled(page)
            shot(page, f"wall_spotlight_{kind}_settled", 300)
        page.wait_for_timeout(500)
        _wait_transition(page, kind)
        page.wait_for_timeout(700 if kind != "stamp" else 900)
        shot(page, f"wall_spotlight_{kind}_midway", 0)

    # gallery
    wall_fake.config["playlist"] = _only("gallery")
    wall_fake.config["look"] = {**wall_fake.config["look"], "preset": "blobs"}
    page.reload(wait_until=LOADED)
    page.get_by_test_id("wall-gallery").wait_for()
    shot(page, "wall_gallery_1", 1500)
    shot(page, "wall_gallery_2", 3000)

    # categories
    wall_fake.config["playlist"] = _only("categories")
    wall_fake.config["categories"] = {"per_category_s": 4, "disabled": []}
    page.reload(wait_until=LOADED)
    page.get_by_test_id("wall-category").first.wait_for()
    shot(page, "wall_categories_1", 1600)
    card = page.get_by_test_id("wall-category")
    first = card.get_attribute("data-category")
    expect(card).not_to_have_attribute("data-category", first or "", timeout=8000)
    shot(page, "wall_categories_2_entering", 200)
    shot(page, "wall_categories_3", 1500)
    assert js_errors(page, 401) == []
