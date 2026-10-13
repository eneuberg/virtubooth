"""Browser end-to-end fixtures: a real uvicorn server serving the BUILT
frontend (frontend/dist, so the real CSP applies) + Playwright with a fake
camera. Run with `uv run pytest -m e2e` (from backend/) after building the
frontend (`pnpm build` in frontend/). Without frontend/dist every e2e test is
skipped with a message; `VB_E2E_WEB_DIR=<dir>` serves another build (e.g.
tests/fixtures/web, the stub, to check the harness itself).

Browsers: Chromium (default), `VB_E2E_BROWSER=firefox`, or WebKit via
tests/e2e/run_webkit.sh (inside the Playwright Docker image).

Cameras: the fake devices of Chromium and Firefox are one camera (Firefox's
claims to face the back), so phone contexts get PHONE_CAMERAS: a front and a
back camera that report the side that was asked for (WebKit's mock has both).
`new_context(browser, "desktop")` is a 1280x800 PC without touch and with one
16:9 webcam (WEBCAM) showing a test card, so crops can be checked.

Every test should assert `page.js_errors == []`: CSP violations, React errors
and failed loads show up there.

    @pytest.mark.e2e
    def test_page(guest_page, live):
        guest_page.goto(live.url("/x/beer/"))

The old DOM-based tests are in tests/e2e_legacy/ (not collected) for wave 2
to port; their helpers that depend on the old markup are marked LEGACY below.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from virtubooth.app import create_app
from virtubooth.extensions.sdk import Extension
from virtubooth.runtime import Core
from virtubooth.settings import DEFAULT_WEB_DIR, Settings

from ..conftest import ADMIN_PASSWORD, PARTY_TOKEN, SECRET_KEY

BROWSER_NAME = os.environ.get("VB_E2E_BROWSER", "chromium")
WEB_DIR = Path(os.environ.get("VB_E2E_WEB_DIR") or DEFAULT_WEB_DIR).resolve()

# for tests that need Chromium-only test tooling (CDP sessions)
chromium_only = pytest.mark.skipif(
    BROWSER_NAME != "chromium", reason="needs Chromium-only test tooling"
)
# reading the clipboard back: Chromium via a permission, Firefox via a testing pref, WebKit can't
needs_clipboard = pytest.mark.skipif(
    BROWSER_NAME == "webkit", reason="WebKit can't read the clipboard in tests"
)
# Firefox's own camera permission prefs
firefox_only = pytest.mark.skipif(BROWSER_NAME != "firefox", reason="Firefox-only check")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """No build, no e2e: skip before any browser starts."""
    if (WEB_DIR / "index.html").is_file():
        return
    skip = pytest.mark.skip(
        reason=f"no frontend build at {WEB_DIR}: run `pnpm build` in frontend/ first "
        "(or set VB_E2E_WEB_DIR)"
    )
    for item in items:
        if item.get_closest_marker("e2e") is not None:
            item.add_marker(skip)


FIREFOX_PREFS = {
    "media.navigator.streams.fake": True,
    "media.navigator.permission.disabled": True,
    "dom.events.testing.asyncClipboard": True,  # navigator.clipboard.readText() without the paste prompt
}

MOBILE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 2,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"
    ),
}


FIREFOX = {
    "viewport": {"width": 390, "height": 844},
    "has_touch": True,
}

IPHONE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
    ),
}

# the host's PC: mouse + keyboard, no touch, the browser's own desktop user agent
DESKTOP = {"viewport": {"width": 1280, "height": 800}}

# A phone has a front and a back camera that say where they point. The fake
# devices have one camera that says nothing (Chromium) or "environment"
# (Firefox): report the side the page asked for and list a second camera.
PHONE_CAMERAS = """(() => {
  const md = window.MediaDevices && MediaDevices.prototype;
  if (!md || !md.getUserMedia) return;
  const gum = md.getUserMedia, enumerate = md.enumerateDevices, settings = MediaStreamTrack.prototype.getSettings;
  const facing = new WeakMap();
  const asked = (c) => {
    let f = c && typeof c.video === 'object' ? c.video.facingMode : undefined;
    if (f && typeof f === 'object') f = f.exact || f.ideal;
    return f === 'environment' ? 'environment' : 'user';
  };
  const define = (obj, name, value) => Object.defineProperty(obj, name, { configurable: true, writable: true, value });
  define(md, 'getUserMedia', async function (c) {
    const stream = await gum.call(this, c);
    for (const track of stream.getVideoTracks()) facing.set(track, asked(c));
    return stream;
  });
  define(md, 'enumerateDevices', async function () {
    const list = await enumerate.call(this);
    const cams = list.filter((d) => d.kind === 'videoinput');
    if (cams.length !== 1) return list;
    const back = { kind: 'videoinput', deviceId: 'back', groupId: 'back', label: cams[0].label && 'Back Camera' };
    return [...list, { ...back, toJSON: () => back }];
  });
  define(MediaStreamTrack.prototype, 'getSettings', function () {
    const s = settings.call(this);
    if (facing.has(this)) s.facingMode = facing.get(this);
    return s;
  });
})();"""

# Laptop webcam: the only camera, 1280x720 landscape, no facing mode, refuses
# a hard (exact) request for the back camera. The page still goes through the
# browser's getUserMedia (permission, constraints), then gets a test card: red
# outside the centred 3:4 region a portrait photo may keep (x 370..910, plus
# 4 px for rounding), blue inside, a 140 px yellow square in that region's
# top-left corner (x 400, y 40: shows which way the picture is mirrored).
# window.__cameraRequests lists the constraints the page asked for.
WEBCAM = """(() => {
  const md = window.MediaDevices && MediaDevices.prototype;
  if (!md || !md.getUserMedia) return;
  const gum = md.getUserMedia, enumerate = md.enumerateDevices;
  const define = (obj, name, value) => Object.defineProperty(obj, name, { configurable: true, writable: true, value });
  function testCard() {
    const c = document.createElement('canvas');
    c.width = 1280;
    c.height = 720;
    const ctx = c.getContext('2d');
    let n = 0;
    const paint = () => {
      ctx.fillStyle = '#ff0000';
      ctx.fillRect(0, 0, 1280, 720);
      ctx.fillStyle = '#1e46dc';
      ctx.fillRect(366, 0, 548, 720);
      ctx.fillStyle = '#ffdc00';
      ctx.fillRect(400, 40, 140, 140);
      ctx.fillStyle = (n++ % 2) ? '#1e46dc' : '#1f47dd';  // a changing pixel keeps frames coming
      ctx.fillRect(640, 700, 2, 2);
    };
    paint();
    setInterval(paint, 50);
    return c.captureStream(30);
  }
  window.__cameraRequests = [];
  define(md, 'getUserMedia', async function (c) {
    window.__cameraRequests.push(JSON.parse(JSON.stringify(c || {})));
    const facing = c && c.video && c.video.facingMode;
    if (facing && facing.exact && facing.exact !== 'user') {
      throw new DOMException('no back camera', 'OverconstrainedError');
    }
    const real = await gum.call(this, c);
    if (!c || !c.video) return real;
    real.getVideoTracks().forEach((t) => t.stop());
    return testCard();
  });
  define(md, 'enumerateDevices', async function () {
    const list = await enumerate.call(this);
    const cam = list.find((d) => d.kind === 'videoinput');
    return list.filter((d) => d.kind !== 'videoinput' || d === cam);
  });
})();"""


@dataclass
class LiveServer:
    base_url: str
    core: Core

    def url(self, path: str = "/") -> str:
        return self.base_url + path

    def entry(self, path: str = "/") -> str:
        """URL as printed on the QR code."""
        sep = "&" if "?" in path else "?"
        return f"{self.base_url}{path}{sep}t={PARTY_TOKEN}"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def e2e_extensions() -> Sequence[Extension] | None:
    """Override to pick extensions; None = all discovered ones."""
    return None


@pytest.fixture
def e2e_settings() -> dict[str, Any]:
    """Override to change Settings fields of the live server, e.g. {"instagram_account": "@x"}."""
    return {}


@pytest.fixture
def live(
    tmp_path: Path, e2e_extensions: Sequence[Extension] | None, e2e_settings: dict[str, Any]
) -> Iterator[LiveServer]:
    settings = Settings(
        _env_file=None,
        **{
            "party_token": PARTY_TOKEN,
            "admin_password": ADMIN_PASSWORD,
            "secret_key": SECRET_KEY,
            "data_dir": tmp_path / "data",
            "web_dir": WEB_DIR,
            "party_name": "E2E Party",
            **e2e_settings,
        },
    )
    app = create_app(settings, extensions=e2e_extensions)
    port = _free_port()
    # like `virtubooth serve`: open event streams don't hold the shutdown
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=1
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.02)
    yield LiveServer(f"http://127.0.0.1:{port}", app.state.core)
    server.should_exit = True
    thread.join(5)
    app.state.core.db.close()


@pytest.fixture(scope="session")
def playwright() -> Iterator[Playwright]:
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright: Playwright) -> Iterator[Browser]:
    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
    fake_video = os.environ.get("VB_FAKE_VIDEO")
    if fake_video:
        args.append(f"--use-file-for-fake-video-capture={fake_video}")
    if BROWSER_NAME == "webkit":
        b = playwright.webkit.launch()
    elif BROWSER_NAME == "firefox":
        b = playwright.firefox.launch(firefox_user_prefs=FIREFOX_PREFS)
    else:
        b = playwright.chromium.launch(args=args)
    yield b
    b.close()


def new_context(browser: Browser, device: str = "phone", **options: Any) -> BrowserContext:
    """A context like a guest's device: "phone" (390x844 touch, front + back
    camera) or "desktop" (DESKTOP + WEBCAM). `options` go to new_context()."""
    if device == "desktop":
        opts: dict[str, Any] = dict(DESKTOP)
    else:
        opts = dict({"webkit": IPHONE, "firefox": FIREFOX}.get(BROWSER_NAME, MOBILE))
    opts.update(options)
    if BROWSER_NAME == "firefox":
        opts.pop("is_mobile", None)  # no mobile emulation; camera access comes from FIREFOX_PREFS
    else:
        opts.setdefault("permissions", ["camera"])
    ctx = browser.new_context(**opts)
    if device == "desktop":
        ctx.add_init_script(WEBCAM)
    elif BROWSER_NAME != "webkit":  # WebKit's mock camera has a front and a back camera
        ctx.add_init_script(PHONE_CAMERAS)
    return ctx


def allow_clipboard(context: BrowserContext) -> None:
    """Let the page read the clipboard back (see needs_clipboard)."""
    if BROWSER_NAME == "chromium":
        context.grant_permissions(["clipboard-read", "clipboard-write"])


def track_errors(page: Page) -> Page:
    """page.js_errors: uncaught exceptions and console errors."""
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: (
            errors.append(f"{msg.text} @ {msg.location.get('url', '')}")
            if msg.type == "error"
            else None
        ),
    )
    page.js_errors = errors  # type: ignore[attr-defined]
    return page


def wait_until_ready(page: Page, timeout: float = 10.0) -> None:
    """Wait for `window.__vbReady` (set once the app booted). Polls with
    evaluate(): a string wait_for_function would need eval, which the CSP blocks."""
    deadline = time.monotonic() + timeout
    while not page.evaluate("() => window.__vbReady === true"):
        if time.monotonic() > deadline:
            raise AssertionError("the app did not boot (window.__vbReady never set)")
        page.wait_for_timeout(50)


@pytest.fixture
def context(browser: Browser, live: LiveServer) -> Iterator[BrowserContext]:
    ctx = new_context(browser)
    yield ctx
    ctx.close()


@pytest.fixture
def page(context: BrowserContext) -> Iterator[Page]:
    yield track_errors(context.new_page())


def shot(page: Page, name: str, settle_ms: int = 300) -> None:
    """Screenshot into $VB_SCREENSHOT_DIR (nothing when unset)."""
    out = os.environ.get("VB_SCREENSHOT_DIR")
    if not out:
        return
    page.wait_for_timeout(settle_ms)
    Path(out).mkdir(parents=True, exist_ok=True)
    seen = len(getattr(page, "js_errors", []))
    page.screenshot(path=str(Path(out) / f"{BROWSER_NAME}_{name}.png"))
    # WebKit's screenshot injects a <style>, which our CSP refuses: not the page's fault
    errors = getattr(page, "js_errors", None)
    if errors is not None:
        errors[seen:] = [
            e for e in errors[seen:] if not e.startswith("Refused to apply a stylesheet")
        ]


@pytest.fixture
def admin_page(context: BrowserContext, live: LiveServer) -> Page:
    """A page with an admin session (logged in via the API, not the UI)."""
    p = track_errors(context.new_page())
    p.goto(
        live.url("/admin/login")
    )  # a real page: WebKit styles JSON views inline, which the CSP blocks
    status = p.evaluate(
        """async (pw) => (await fetch('/api/admin/login', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: pw})})).status""",
        ADMIN_PASSWORD,
    )
    assert status == 200
    return p


# ------------------------------------------------- LEGACY (old markup)
# TODO(wave 2, GP): port to the new join sheet; kept so ported tests have a start.


def settle_dialogs(page: Page) -> None:
    """LEGACY: wait until the open dialogs' entry animations are done (old `.vb-scrim`)."""
    page.evaluate(
        """() => Promise.all(document.getAnimations()
            .filter((a) => a.effect && a.effect.target && a.effect.target.closest && a.effect.target.closest('.vb-scrim'))
            .map((a) => a.finished.catch(() => null)))"""
    )


def accept_consent_in_browser(page: Page, instagram: str = "") -> None:
    """LEGACY selectors: `join` test id, `#vb-join-insta`, the "Alles klar" button."""
    page.get_by_test_id("join").wait_for()
    if instagram:
        page.fill("#vb-join-insta", instagram)
    page.get_by_role("button", name="Alles klar").click()
    page.get_by_test_id("join").wait_for(state="detached")


@pytest.fixture
def guest_page(page: Page, live: LiveServer) -> Page:
    """A page that scanned the QR code and accepted the join dialog on /."""
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    return page
