"""The page's heartbeat (POST /api/here) in a real browser: a beat at load, one with
`visible: false` (keepalive) when the page is hidden, one again when it is shown,
and the guest's online time on the server."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, Request

from ..conftest import LiveServer, join_via_api
from .conftest import only_user

pytestmark = pytest.mark.e2e

# what a phone does when the guest switches apps: the page says it is hidden
SET_VISIBILITY = """(state) => {
    Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => state});
    document.dispatchEvent(new Event('visibilitychange'));
}"""


def beat(visible: bool) -> Callable[[Request], bool]:
    def match(request: Request) -> bool:
        if request.method != "POST" or not request.url.endswith("/api/here"):
            return False
        return json.loads(request.post_data or "{}") == {"visible": visible}

    return match


def eventually(check: Callable[[], bool], what: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out: {what}")
        time.sleep(0.05)


def test_the_page_reports_while_it_is_visible(page: Page, live: LiveServer):
    page.clock.install()  # the 15 s between two visible beats pass at once below
    join_via_api(page, live)

    with page.expect_request(beat(True)):
        page.reload()
    eventually(lambda: only_user(live).online_at is not None, "a visit is open")
    assert only_user(live).online_sessions >= 1

    with page.expect_request(beat(False)) as hidden:
        page.evaluate(SET_VISIBILITY, "hidden")
    assert hidden.value.headers.get("content-type") == "application/json"
    eventually(lambda: only_user(live).online_at is None, "the visit is closed")

    page.clock.fast_forward(16_000)
    with page.expect_request(beat(True)):
        page.evaluate(SET_VISIBILITY, "visible")
    eventually(lambda: only_user(live).online_at is not None, "a new visit is open")
    user = only_user(live)
    assert user.online_sessions >= 2
    assert page.js_errors == []  # type: ignore[attr-defined]
