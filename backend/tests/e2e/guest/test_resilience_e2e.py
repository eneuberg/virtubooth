"""How the guest app survives content blockers, dead networks and busy servers:
a blocked device-trait chunk, a blocked entry module (boot-check.js), a blocked or
offline /api/identify, a 429 with Retry-After, the ?debug=1 log, and lazy chunks
that fail because the page leaves or a deploy removed them. Ported from
the pre-overhaul test_core_e2e.py and test_core_ui_e2e.py (same behaviours, new markup)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

from ..conftest import (
    LOADED,
    WEB_DIR,
    LiveServer,
    accept_consent_in_browser,
    join_via_api,
    settle_dialogs,
    shot,
    track_errors,
)
from .conftest import errors_besides, only_user, reload

pytestmark = pytest.mark.e2e

# console lines of requests a test made fail on purpose
NOISE = ("Failed to load resource", "ERR_", "NetworkError", "net::", "/api/", "blocked")


def built_file(source: str) -> str:
    """The hashed file the build made of a source module or HTML entry."""
    manifest: dict[str, Any] = json.loads((WEB_DIR / ".vite" / "manifest.json").read_text())
    return str(manifest[source]["file"])


def test_blocked_device_trait_chunk_does_not_break_joining(page: Page, live: LiveServer):
    """Blockers drop URLs that look like tracking. The optional trait chunk failing
    must not stop the page, nor reload it: joining works with the coarse fallback."""
    chunk = built_file("src/sdk/traits.ts")
    page.route(f"**/{chunk}", lambda route: route.abort("blockedbyclient"))
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    expect(page.get_by_test_id("start")).to_be_visible()
    user = only_user(live)
    assert user.fp_components.get("fallback") is True
    assert user.fp_hash and len(user.fp_hash) == 64
    # no "reload after a deploy" for an optional chunk
    assert page.evaluate("() => sessionStorage.getItem('vb_chunk_reload')") is None
    assert errors_besides(page, *NOISE) == []


def test_blocked_entry_module_shows_a_hint_instead_of_nothing(page: Page, live: LiveServer):
    entry = built_file("index.html")
    page.route(f"**/{entry}", lambda route: route.abort("blockedbyclient"))
    page.goto(live.entry("/"))
    hint = page.get_by_test_id("load-failed")
    expect(hint).to_be_visible(timeout=10_000)
    expect(hint).to_contain_text("Blocker")
    expect(hint.get_by_role("button", name="Seite neu laden")).to_be_focused()
    shot(page, "boot_check")


def test_blocked_identify_offers_a_reload(page: Page, live: LiveServer):
    """A blocker (or a dead network) drops /api/identify. The page can't tell which,
    so it says neither "offline" nor nothing at all."""
    page.route("**/api/identify", lambda route: route.abort("blockedbyclient"))
    page.goto(live.entry("/"))
    fatal = page.get_by_test_id("fatal")
    expect(fatal).to_be_visible()
    expect(fatal).to_contain_text("Keine Antwort")
    expect(fatal).to_contain_text("Blocker")
    expect(fatal).not_to_contain_text("Keine Verbindung")
    again = fatal.get_by_role("button", name="Seite neu laden")
    expect(again).to_be_focused()
    shot(page, "identify_blocked")
    page.unroute("**/api/identify")
    again.click()
    accept_consent_in_browser(page)
    expect(page.get_by_test_id("start")).to_be_visible()
    expect(page.get_by_test_id("fatal")).to_have_count(0)
    assert errors_besides(page, *NOISE) == []


def test_offline_phone_is_told_so(page: Page, live: LiveServer):
    page.add_init_script(
        "Object.defineProperty(Navigator.prototype, 'onLine', { configurable: true, get: () => false });"
    )
    page.route("**/api/identify", lambda route: route.abort("internetdisconnected"))
    page.goto(live.entry("/"))
    fatal = page.get_by_test_id("fatal")
    expect(fatal).to_contain_text("Keine Verbindung")
    expect(fatal.get_by_role("button", name="Seite neu laden")).to_be_visible()


def test_offline_while_on_start_shows_in_the_status_slot(guest_page: Page):
    page = guest_page
    # fonts in first: a download cut by going offline is logged as an error (Firefox)
    expect(page.get_by_test_id("beer-count")).to_be_visible()
    page.evaluate("() => document.fonts.ready.then(() => null)")
    page.context.set_offline(True)
    page.evaluate("() => window.dispatchEvent(new Event('offline'))")
    slot = page.get_by_test_id("status-slot")
    expect(slot).to_have_attribute("data-kind", "offline")
    expect(slot).to_contain_text("Offline")
    page.context.set_offline(False)
    page.evaluate("() => window.dispatchEvent(new Event('online'))")
    expect(slot).to_have_count(0)
    assert errors_besides(guest_page, *NOISE) == []


def test_busy_server_says_when_to_try_again(page: Page, live: LiveServer):
    page.route(
        "**/api/extensions",
        lambda route: route.fulfill(
            status=429,
            headers={"Retry-After": "12"},
            content_type="application/json",
            body='{"error": "rate_limited", "message": "Langsam! Zu viele Anfragen. Warte kurz."}',
        ),
    )
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    note = page.get_by_test_id("activities-error")
    expect(note).to_contain_text("Langsam! Zu viele Anfragen. Warte kurz (in 12 s nochmal).")
    page.unroute("**/api/extensions")
    note.get_by_role("button", name="Erneut laden").click()
    expect(page.get_by_test_id("tile-beer")).to_be_visible()
    expect(page.get_by_test_id("activities-error")).to_have_count(0)
    assert errors_besides(page, *NOISE, "429") == []


def test_debug_log_lets_taps_through_and_folds(page: Page, live: LiveServer):
    page.goto(live.entry("/?debug=1"))
    log = page.locator(".vb-debug-log")
    expect(log).to_be_visible()
    expect(log).to_contain_text("debug on")
    expect(log).to_contain_text("identify")
    expect(page.get_by_test_id("join")).to_be_visible()
    settle_dialogs(page)
    box = log.bounding_box()
    assert box is not None and box["y"] < 10  # at the top, away from shutters and buttons
    under = page.evaluate(
        "([x, y]) => !!document.elementFromPoint(x, y).closest('[data-testid=debug]')",
        [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
    )
    assert under is False, "the log catches taps"
    shot(page, "join_with_debug_log")
    accept_consent_in_browser(page)
    toggle = page.get_by_test_id("debug-toggle")
    toggle.click()
    expect(log).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    reload(page)
    expect(page.get_by_test_id("debug-toggle")).to_be_visible()
    expect(page.locator(".vb-debug-log")).to_be_hidden()  # stays folded for the tab
    page.get_by_test_id("debug-toggle").click()
    expect(page.locator(".vb-debug-log")).to_be_visible()
    assert page.js_errors == []  # type: ignore[attr-defined]


CARDS = ("src/extensions/beer/BeerCard.tsx", "src/extensions/booth/BoothCard.tsx")
# the HTML of "/" once another build is deployed
NEW_BUILD = '<!doctype html><script type="module" crossorigin src="/assets/e-new.js"></script>'


def fresh_tab(page: Page, live: LiveServer) -> tuple[Page, list[str]]:
    """A new tab of a joined guest (nothing of an earlier page still loading) and the
    URLs of the documents it loads."""
    join_via_api(page, live)
    page.close()
    tab = track_errors(page.context.new_page())
    documents: list[str] = []
    tab.on("request", lambda r: documents.append(r.url) if r.is_navigation_request() else None)
    return tab, documents


def test_leaving_start_while_its_cards_load_goes_where_asked(page: Page, live: LiveServer):
    """Firefox and WebKit abort the lazy modules of a page that starts to leave, and
    Vite reports that like a chunk a deploy removed (vite:preloadError). A reload then
    would cancel the navigation: the guest would stay on Start (lib/boot.ts)."""
    tab, documents = fresh_tab(page, live)
    beer, booth = (f"**/{built_file(source)}" for source in CARDS)
    held: list[Route] = []  # never answered: the cards are still loading when Start leaves
    tab.route(beer, lambda route: held.append(route))
    tab.route(booth, lambda route: held.append(route))
    with tab.expect_request(beer), tab.expect_request(booth):
        tab.goto(live.url("/"), wait_until=LOADED)
    # the rest of Start is in (an aborted fetch or font is an error of its own)
    expect(tab.get_by_test_id("my-photos")).not_to_have_attribute("data-state", "loading")
    tab.evaluate("() => document.fonts.ready.then(() => null)")
    tab.goto(live.url("/x/beer/"), wait_until=LOADED)
    expect(tab.get_by_test_id("beer-app")).to_be_visible()
    assert tab.url == live.url("/x/beer/")
    assert documents == [live.url("/"), live.url("/x/beer/")]  # Start never reloaded
    tab.unroute_all(behavior="ignoreErrors")
    assert tab.js_errors == []  # type: ignore[attr-defined]


def test_a_new_deploy_reloads_the_page_once(page: Page, live: LiveServer):
    """The tab runs the old build, the deploy removed its chunks: the app finds another
    entry script in the page's HTML and reloads once. A chunk that still fails after
    that shows the error instead of reloading again."""
    tab, documents = fresh_tab(page, live)
    tab.route(f"**/{built_file(CARDS[0])}", lambda route: route.fulfill(status=404))

    def html(route: Route) -> None:
        if route.request.is_navigation_request():
            route.continue_()
        else:  # the app's check after the failed chunk
            route.fulfill(content_type="text/html", body=NEW_BUILD)

    tab.route(live.url("/"), html)
    loaded: list[str] = []
    tab.on("domcontentloaded", lambda p: loaded.append(p.url))
    tab.goto(live.url("/"), wait_until=LOADED)
    for _ in range(100):  # the reloaded page (at most 5 s)
        if len(loaded) > 1:
            break
        tab.wait_for_timeout(50)
    expect(tab.get_by_test_id("fatal")).to_be_visible()
    tab.wait_for_timeout(500)  # its own check finds the new build too: no second reload
    assert documents == [live.url("/"), live.url("/")]
    assert tab.evaluate("() => sessionStorage.getItem('vb_chunk_reload')") == "1"
    # no check of the console: both pages log the failed chunk (Firefox: a bare JSHandle)
