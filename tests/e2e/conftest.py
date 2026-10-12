"""Browser end-to-end fixtures: a real uvicorn server + Playwright Chromium
with a fake camera (Chromium's built-in test pattern, or a custom .y4m/.mjpeg
via VB_FAKE_VIDEO). Run with `uv run pytest -m e2e`.

    @pytest.mark.e2e
    def test_page(guest_page, live):
        guest_page.goto(live.url("/x/beer/"))
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from virtubooth.app import create_app
from virtubooth.config import Settings
from virtubooth.context import Core
from virtubooth.extension import Extension

from ..conftest import ADMIN_PASSWORD, PARTY_TOKEN, SECRET_KEY

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
        return s.getsockname()[1]


@pytest.fixture
def e2e_extensions() -> Sequence[Extension] | None:
    """Override to pick extensions; None = all discovered ones."""
    return None


@pytest.fixture
def live(tmp_path: Path, e2e_extensions: Sequence[Extension] | None) -> Iterator[LiveServer]:
    settings = Settings(
        party_token=PARTY_TOKEN,
        admin_password=ADMIN_PASSWORD,
        secret_key=SECRET_KEY,
        data_dir=tmp_path / "data",
        party_name="E2E Party",
    )
    app = create_app(settings, extensions=e2e_extensions)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
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
def browser() -> Iterator[Browser]:
    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
    fake_video = os.environ.get("VB_FAKE_VIDEO")
    if fake_video:
        args.append(f"--use-file-for-fake-video-capture={fake_video}")
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        yield b
        b.close()


@pytest.fixture
def context(browser: Browser, live: LiveServer) -> Iterator[BrowserContext]:
    ctx = browser.new_context(**MOBILE, permissions=["camera"])
    yield ctx
    ctx.close()


@pytest.fixture
def page(context: BrowserContext) -> Iterator[Page]:
    p = context.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda exc: errors.append(str(exc)))
    p.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    p.js_errors = errors  # type: ignore[attr-defined]
    yield p


def accept_consent_in_browser(page: Page, instagram: str = "") -> None:
    page.get_by_test_id("consent").wait_for()
    if instagram:
        page.fill("#vb-consent-insta", instagram)
    page.get_by_role("button", name="Alles klar").click()
    page.get_by_test_id("consent").wait_for(state="detached")


@pytest.fixture
def guest_page(page: Page, live: LiveServer) -> Page:
    """A page that scanned the QR code and accepted the consent banner on /."""
    page.goto(live.entry("/"))
    accept_consent_in_browser(page)
    return page


@pytest.fixture
def admin_page(context: BrowserContext, live: LiveServer) -> Page:
    """A page with an admin session (logged in via the API, not the UI)."""
    p = context.new_page()
    p.goto(live.url("/healthz"))
    status = p.evaluate(
        """async (pw) => (await fetch('/api/admin/login', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: pw})})).status""",
        ADMIN_PASSWORD,
    )
    assert status == 200
    return p
