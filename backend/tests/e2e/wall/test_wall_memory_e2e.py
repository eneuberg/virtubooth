"""Memory smoke test of the Live-Wall screen: the wall runs with fast intervals for a few
minutes (every mode, every transition, a steady stream of new and removed photos) and
the JS heap and the DOM stay bounded.

Chromium only (CDP: forced garbage collection, `Runtime.getHeapUsage`,
`Memory.getDOMCounters`). Two minutes by default; `VB_WALL_SOAK_S=600` runs it longer.
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest
from playwright.sync_api import CDPSession, Page

from ..conftest import LOADED, chromium_only, wait_until_ready
from .conftest import WallFake, js_errors, wall_photo

pytestmark = [pytest.mark.e2e, chromium_only]

# read at import: the root `clean_env` fixture removes every VB_* variable per test
SOAK_S = float(os.environ.get("VB_WALL_SOAK_S") or 120)
WARMUP_S = 25.0  # a bit more than one playlist round: every mode has run once
SAMPLE_S = 5.0
POOL = 60  # photos in the feed; every new one pushes the oldest out
GUESTS = ["Lena", "Max", "Funky Flamingo", "Ali", "Sophie", "Tom", "Mia", "Jonas"]
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
# GL transitions turn into a crossfade without WebGL (headless Chromium may lack it)
NEED_WEBGL = {"dither", "pixelate"}

# every transition the spotlight starts, recorded in the page (the stage's data-transition)
RECORD_TRANSITIONS = """
window.__wallTransitions = [];
new MutationObserver((records) => {
  for (const r of records) {
    const t = r.target.dataset && r.target.dataset.transition;
    if (t) window.__wallTransitions.push(t);
  }
}).observe(document, { subtree: true, attributes: true, attributeFilter: ['data-transition'] });
"""


def _sample(page: Page, cdp: CDPSession) -> dict[str, Any]:
    cdp.send("HeapProfiler.collectGarbage")
    heap = cdp.send("Runtime.getHeapUsage")
    counters = cdp.send("Memory.getDOMCounters")
    live: dict[str, Any] = page.evaluate(
        """() => ({
            elements: document.getElementsByTagName('*').length,
            images: document.images.length,
            canvases: document.getElementsByTagName('canvas').length,
            mode: document.querySelector('.wall-mode:not([data-leaving])')?.dataset.mode ?? '',
        })"""
    )
    return {
        "heap_mb": heap["usedSize"] / 1e6,
        "nodes": counters["nodes"],
        "listeners": counters["jsEventListeners"],
        **live,
    }


def _peak(samples: list[dict[str, Any]], key: str) -> float:
    return float(max(s[key] for s in samples))


def test_wall_memory_stays_bounded(tv_page: Page, wall_fake: WallFake) -> None:
    page = tv_page
    fake = wall_fake
    fake.session = "ok"
    fake.retry_ms = 2000  # a reconnect (and a feed refetch) every 2 s
    fake.event_name = "Soak-Party"
    seq = 0

    def new_photo() -> dict[str, Any]:
        nonlocal seq
        seq += 1
        return wall_photo(seq, GUESTS[seq % len(GUESTS)], minutes_ago=seq % 50)

    for _ in range(POOL):
        fake.add(new_photo())
    fake.categories = [
        {
            "id": f"cat{k}",
            "emoji": "🎉",
            "title": f"Kategorie {k}",
            "line": "Zum Testen",
            "winners": [
                {"photo": fake.photos[k * 3 + j], "value": 3 - j, "label": f"{3 - j} Dinge"}
                for j in range(1 + k % 3)
            ],
        }
        for k in range(4)
    ]
    fake.config["playlist"] = [
        {"mode": "spotlight", "enabled": True, "duration_s": 12},
        {"mode": "gallery", "enabled": True, "duration_s": 5},
        {"mode": "categories", "enabled": True, "duration_s": 5},
    ]
    fake.config["spotlight"] = {
        "algorithm": "fresh_first",
        "n": 12,
        "interval_s": 1,
        "transition": TRANSITIONS[0],
        "transition_ms": 600,
    }
    fake.config["gallery"] = {"speed": "fast", "rows": 4}
    fake.config["categories"] = {"per_category_s": 4, "disabled": []}
    fake.config["overlay"] = {**fake.config["overlay"], "qr": True}
    fake.qr = {"url": "/?t=soak", "name": "Eingang"}

    page.add_init_script(RECORD_TRANSITIONS)
    page.goto(fake.url(), wait_until=LOADED)
    wait_until_ready(page)
    page.locator(".wall-stage .wall-slide").first.wait_for()
    cdp = page.context.new_cdp_session(page)
    webgl = page.evaluate("() => !!document.createElement('canvas').getContext('webgl')")
    # GL transitions turn into a crossfade without WebGL
    cycle = [t for t in TRANSITIONS if webgl or t not in NEED_WEBGL]
    winners = {w["photo"]["id"] for c in fake.categories for w in c["winners"]}

    start = time.monotonic()
    turn = 0
    at = 0  # the configured transition: cycle[at % len(cycle)]
    runs = 0
    since = start  # when the configured transition was set
    skipped: set[str] = set()  # GL transitions the page could not run after all
    next_change = start
    next_sample = start + WARMUP_S
    warm: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    while (now := time.monotonic()) < start + SOAK_S:
        if now >= next_change:
            # every 1.5 s: a new photo, the oldest one (not a category winner) leaves
            turn += 1
            fake.add(new_photo(), live=True)
            fake.remove(next(p["id"] for p in reversed(fake.photos) if p["id"] not in winners))
            # the next transition once the configured one has run
            ran = page.evaluate("(n) => window.__wallTransitions.slice(n)", runs)
            runs += len(ran)
            wanted = cycle[at % len(cycle)]
            stuck = wanted in NEED_WEBGL and now - since > 30
            if stuck:
                skipped.add(wanted)
            if wanted in ran or stuck:
                at += 1
                since = now
                fake.set_config(spotlight={"transition": cycle[at % len(cycle)]})
            next_change = now + 1.5
        if now >= next_sample:
            sample = _sample(page, cdp)
            (warm if now < start + WARMUP_S + 22 else samples).append(sample)
            next_sample = now + SAMPLE_S
        page.wait_for_timeout(100)

    assert warm and samples, "the soak was too short to compare"
    end = samples[-5:]  # the last ~25 s: about one playlist round
    report = {
        key: (round(_peak(warm, key), 1), round(_peak(end, key), 1))
        for key in ("heap_mb", "nodes", "listeners", "elements", "images", "canvases")
    }
    print(f"\nwall soak {SOAK_S:.0f} s, peak warm-up vs end: {report}, GL skipped: {skipped}")

    # the heap and the DOM after a few hundred photos look like after the first round
    assert _peak(end, "heap_mb") <= _peak(warm, "heap_mb") * 1.3 + 4, report
    assert _peak(end, "nodes") <= _peak(warm, "nodes") * 1.3 + 400, report
    assert _peak(end, "listeners") <= _peak(warm, "listeners") * 1.3 + 50, report
    # what is in the document at any time: one or two modes, never a pile-up
    assert _peak(samples, "elements") < 600, report
    assert _peak(samples, "images") < 150, report
    assert _peak(samples, "canvases") <= 4, report

    seen = set(page.evaluate("() => window.__wallTransitions"))
    missing = set(cycle) - skipped - seen
    assert not missing, f"transitions never ran: {sorted(missing)}"
    assert {s["mode"] for s in warm + samples} >= {"spotlight", "gallery", "categories"}
    # a photo removed on the server while the wall still had it: its image is a 404
    gone = [e for e in js_errors(page) if not ("status of 404" in e and "/livewall/media/" in e)]
    assert gone == []
