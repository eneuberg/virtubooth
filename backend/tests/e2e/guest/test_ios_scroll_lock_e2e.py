"""React Aria's iOS code paths under the strict CSP (frontend/patches/react-aria@*.patch).

On iOS, React Aria's usePreventScroll used to inject a `<style>` (`* { overscroll-behavior:
contain }`) whenever a modal opened, and usePress one for `[data-react-aria-pressable]`.
`style-src 'self'` refuses both. The pnpm patch sets `<html data-vb-scroll-lock>` instead,
and app.css carries both rules.

React Aria takes that path for "iOS and WebKit": the platform from
`navigator.userAgentData` or `navigator.platform` (which a user agent string doesn't
change), the engine from the user agent. So the page here is an iPhone's Safari: its
user agent, platform and touch points, no userAgentData. Meant for WebKit (run_webkit.sh);
it holds in every engine.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from ..conftest import IPHONE, LiveServer, accept_consent_in_browser, settle_dialogs

pytestmark = pytest.mark.e2e

IPHONE_PLATFORM = """(() => {
  const define = (name, value) =>
    Object.defineProperty(Navigator.prototype, name, { configurable: true, get: () => value });
  define('platform', 'iPhone');
  define('maxTouchPoints', 5);
  define('userAgentData', undefined);
})();"""

STATE = """() => ({
  styles: document.querySelectorAll('style').length,
  lock: document.documentElement.hasAttribute('data-vb-scroll-lock'),
  overscroll: getComputedStyle(document.body).overscrollBehaviorY,
})"""


@pytest.fixture
def iphone(make_page) -> Page:  # type: ignore[no-untyped-def]
    page: Page = make_page("phone", user_agent=IPHONE["user_agent"])
    page.add_init_script(IPHONE_PLATFORM)
    return page


def test_sheets_lock_scrolling_without_injected_styles(iphone: Page, live: LiveServer):
    page = iphone
    page.goto(live.entry("/"))
    sheet = page.get_by_test_id("join")
    sheet.wait_for()
    settle_dialogs(page)
    assert page.evaluate("() => [navigator.platform, navigator.userAgent.includes('iPhone')]") == [
        "iPhone",
        True,
    ]
    # the join sheet is a modal: the lock is on, through the attribute and app.css
    state = page.evaluate(STATE)
    assert state["styles"] == 0, state
    assert state["lock"] is True, state
    assert state["overscroll"] == "contain", state
    accept_consent_in_browser(page)
    expect(page.get_by_test_id("start")).to_be_visible()
    state = page.evaluate(STATE)
    assert state["lock"] is False and state["overscroll"] != "contain", state

    # another sheet (the "Du" sheet), opened and closed
    page.get_by_test_id("guest-pass").click()
    expect(page.get_by_role("dialog")).to_be_visible()
    settle_dialogs(page)
    state = page.evaluate(STATE)
    assert state["styles"] == 0 and state["lock"] is True, state
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert page.evaluate(STATE)["lock"] is False
    assert page.evaluate("() => document.querySelectorAll('style').length") == 0
    assert page.js_errors == []  # type: ignore[attr-defined]
