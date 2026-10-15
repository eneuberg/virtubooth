"""Nothing covers the top right of the live wall (the "white box" report).

On a TV, a blank white box (about 450×420 at the reported 2000×1127) sat at the top
right of the spotlight, touching the top and right edges, with the QR corner at the
bottom right. It was Bitwarden's "save login" bar (a fixed 430×400 iframe host at
top: 10px, right: 0 on <body>), opened by the wall's password login, plus Bitwarden's
shield button left where the password field had been (the field went while focused;
the login blurs it now). The live wall hides what extensions add to <body> (wall.css,
`data-wall-live`). Not the wall's own drawing (shader canvas, confetti, fullscreen
button, preloader, leaving mode): `test_corner_stays_clear_after_every_transition`
checks those after each transition, at the reported size with the QR bottom right.
"""

from __future__ import annotations

import io
import time
from typing import Any

import pytest
from PIL import Image
from playwright.sync_api import Browser, BrowserContext, Page, expect

from ..conftest import LOADED, shot, track_errors, wait_until_ready
from .conftest import PASSWORD, WallFake, js_errors, wall_photo

pytestmark = pytest.mark.e2e

TV_REPORT = {"viewport": {"width": 2000, "height": 1127}}
W, H = 2000, 1127
# the box of the report: the top right 450×420
ZONE = {"x": W - 450, "y": 0, "width": 450, "height": 420}

TRANSITIONS = [
    "crossfade",
    "kenburns",
    "spring",
    "dither",
    "pixelate",
    "glitch",
    "polaroid",
    "slot",
    "jelly",
    "stamp",
    "confetti",
]

# Points in the overscan margin of the zone (outside .wall-safe): only the background
# may be there. What sits on top of each point, and every canvas of the page.
PROBE = """([w, h]) => {
  const pad = parseFloat(getComputedStyle(document.querySelector('.wall-safe')).top);
  const points = [[w - 3, 3], [w - 225, 3], [w - 447, 3], [w - 3, 210], [w - 3, 417],
                  [w - pad / 2, 300], [w - 300, pad / 2]];
  const top = points.map(([x, y]) => {
    const el = document.elementFromPoint(x, y);
    return el ? el.tagName.toLowerCase() + '.' + (el.getAttribute('class') || '') : 'none';
  });
  const canvases = [...document.querySelectorAll('canvas')].map((c) => c.className);
  const leftovers = document.querySelectorAll(
    '.wall-gl, .wall-confetti, .wall-glitch, .wall-slot').length;
  return { top, canvases, leftovers, slides: document.querySelectorAll('.wall-slide').length };
}"""

# A stand-in for Bitwarden's "save login" bar: a host element on <body> with a closed
# shadow root, inside it a fixed 430×400 box at the top right (white: as it showed up).
FAKE_EXTENSION_BAR = """() => {
  const host = document.createElement('bit-notification-bar-root');
  const root = host.attachShadow({ mode: 'closed' });
  const bar = document.createElement('div');
  bar.style.setProperty('position', 'fixed', 'important');
  bar.style.setProperty('top', '10px', 'important');
  bar.style.setProperty('right', '0px', 'important');
  bar.style.setProperty('width', '430px', 'important');
  bar.style.setProperty('height', '400px', 'important');
  bar.style.setProperty('z-index', '2147483647', 'important');
  bar.style.setProperty('background', '#ffffff', 'important');
  root.append(bar);
  document.body.append(host);
}"""


def white_share(page: Page, clip: dict[str, float] = ZONE) -> float:
    """Share of (almost) white pixels in `clip`."""
    errors: list[str] = page.js_errors  # type: ignore[attr-defined]
    seen = len(errors)
    png = page.screenshot(clip=clip)
    # WebKit's screenshot injects a <style>, which the CSP refuses: not the page's fault
    errors[seen:] = [e for e in errors[seen:] if not e.startswith("Refused to apply a stylesheet")]
    img = Image.open(io.BytesIO(png)).convert("RGB").resize((90, 84))
    pixels = list(img.get_flattened_data())
    return sum(1 for r, g, b in pixels if min(r, g, b) > 235) / len(pixels)


def seed(fake: WallFake, transition: str = "crossfade", interval_s: int = 60) -> None:
    fake.hold_stream = True
    fake.event_name = "Sommerfest 2026"
    fake.qr = {"url": "/?t=abcdefghijklmnopqrstuvwx", "name": "Eingang"}
    fake.config["overlay"] = {**fake.config["overlay"], "qr": True, "corner": "bottom-right"}
    fake.config["playlist"] = [
        {"mode": m, "enabled": m == "spotlight", "duration_s": 600}
        for m in ("spotlight", "gallery", "categories")
    ]
    fake.config["spotlight"] = {
        "algorithm": "shuffle",
        "n": 12,
        "interval_s": interval_s,
        "transition": transition,
        "transition_ms": 900,
    }
    for n in range(1, 7):
        photo = wall_photo(n, "Lena")
        if n % 2:  # landscape cards reach furthest to the right
            photo |= {"width": 1600, "height": 900}
        fake.add(photo)


@pytest.fixture
def report_tv(browser: Browser, wall_fake: WallFake) -> Any:
    ctx: BrowserContext = browser.new_context(**TV_REPORT)
    wall_fake.install(ctx)
    yield track_errors(ctx.new_page())
    ctx.close()


def _transition(page: Page) -> str:
    value: str = page.evaluate(
        "() => document.querySelector('.wall-stage')?.dataset.transition ?? ''"
    )
    return value


@pytest.mark.parametrize("kind", TRANSITIONS)
def test_corner_stays_clear_after_every_transition(
    report_tv: Page, wall_fake: WallFake, kind: str
) -> None:
    """After a transition from one photo to the next nothing is left over: no shader or
    confetti canvas, no glitch or slot layer, one slide, and the overscan margin at the
    top right shows the background only (no box, canvas or button over it)."""
    page = report_tv
    wall_fake.session = "ok"
    seed(wall_fake, kind, interval_s=3)
    page.goto(wall_fake.url(), wait_until=LOADED)
    wait_until_ready(page)
    expect(page.get_by_test_id("wall-qr")).to_be_visible()
    # the first photo comes in, then the next one with `kind` (old → new)
    page.locator(".wall-stage .wall-slide").first.wait_for()
    first = page.locator(".wall-stage .wall-slide").first.get_attribute("data-photo")
    deadline = time.monotonic() + 15
    while not (page.locator(".wall-stage .wall-slide").count() == 2 and _transition(page) == kind):
        assert time.monotonic() < deadline, f"no {kind} transition to a second photo"
        page.wait_for_timeout(30)
    expect(page.locator(".wall-stage .wall-slide")).to_have_count(1, timeout=5000)
    expect(page.locator(".wall-stage .wall-slide")).not_to_have_attribute("data-photo", first or "")
    # confetti keeps falling a moment after the transition (≤ 2.6 s), then goes
    expect(page.locator(".wall-gl, .wall-confetti, .wall-glitch, .wall-slot")).to_have_count(
        0, timeout=4000
    )
    probe = page.evaluate(PROBE, [W, H])
    assert all(t.startswith("canvas.wall-bg-canvas") for t in probe["top"]), probe
    assert sorted(probe["canvases"]) == ["wall-bg-canvas", "wall-qr-code"], probe
    assert white_share(page) < 0.05
    assert js_errors(page) == []


def test_extension_ui_stays_off_the_live_wall(report_tv: Page, wall_fake: WallFake) -> None:
    """The login blurs its field before the wall goes live (so a password manager's
    button on it closes), and the live wall hides what extensions add to <body>."""
    page = report_tv
    seed(wall_fake)
    page.goto(wall_fake.url(), wait_until=LOADED)
    wait_until_ready(page)
    login = page.get_by_test_id("wall-login")
    field = login.get_by_label("Passwort")
    field.fill(PASSWORD)
    page.evaluate(
        """() => { window.__focusout = 0;
        document.querySelector('input[type=password]')
          .addEventListener('focusout', () => { window.__focusout += 1; }); }"""
    )
    # an extension's box on the login screen is left alone (no fight with the
    # password manager while the field is there)
    page.evaluate(FAKE_EXTENSION_BAR)
    assert white_share(page) > 0.8
    field.press("Enter")  # Enter in the field: it keeps the focus until the wall goes live
    page.locator(".wall-stage .wall-slide").first.wait_for()
    assert page.evaluate("() => window.__focusout") == 1
    assert page.evaluate("() => document.activeElement === document.body")

    # live: the extension's box is hidden, a new one too
    page.evaluate(FAKE_EXTENSION_BAR)
    shot(page, "wall_corner_extension_bar", 300)
    displays = page.evaluate(
        """() => [...document.querySelectorAll('bit-notification-bar-root')]
          .map((el) => getComputedStyle(el).display)"""
    )
    assert displays == ["none", "none"]
    assert white_share(page) < 0.05
    assert js_errors(page, 401) == []
