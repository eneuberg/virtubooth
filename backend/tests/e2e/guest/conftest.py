"""Fixtures and helpers of the guest e2e tests (GP): the join sheet, Start,
"Deine Bilder", the gate, and how the guest app survives blockers and bad networks.

    uv run pytest tests/e2e/guest -m e2e -q                       # Chromium
    VB_E2E_BROWSER=firefox uv run pytest tests/e2e/guest -m e2e -q
    VB_SCREENSHOT_DIR=dir uv run pytest tests/e2e/guest -m e2e -q  # + screenshots
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import Iterator
from typing import Any

import pytest
from PIL import Image
from playwright.sync_api import Browser, Page

from ..conftest import LiveServer, new_context, track_errors

# read at import: the shared clean_env fixture removes every VB_* before each test,
# which would turn the shared shot() helper into a no-op
SCREENSHOT_DIR = os.environ.get("VB_SCREENSHOT_DIR", "")

ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"
)
INSTAGRAM_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Mobile/15E148 Instagram 390.0.0.27.81 (iPhone14,7; iOS 18_5; de_DE; de; scale=3.00; 1170x2532)"
)
VIEWPORTS = {
    "phone": {"width": 390, "height": 844},
    "small": {"width": 360, "height": 640},
    "land": {"width": 844, "height": 390},
    "desk": {"width": 1440, "height": 900},
}


@pytest.fixture(autouse=True)
def keep_screenshot_dir(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    if SCREENSHOT_DIR:
        monkeypatch.setenv("VB_SCREENSHOT_DIR", SCREENSHOT_DIR)


@pytest.fixture
def e2e_settings() -> dict[str, Any]:
    # the account adds a line to the join text and the Start footer, like at a real party
    return {"instagram_account": "@e2e.party"}


@pytest.fixture
def make_page(browser: Browser, live: LiveServer) -> Iterator[Any]:
    """make_page("small" | "land" | "desk" | "phone", **context options) → a new
    guest device (own context) with error tracking."""
    contexts = []

    def make(view: str = "phone", **options: Any) -> Page:
        device = "desktop" if view == "desk" else "phone"
        opts: dict[str, Any] = {"viewport": VIEWPORTS[view], **options}
        ctx = new_context(browser, device, **opts)
        contexts.append(ctx)
        return track_errors(ctx.new_page())

    yield make
    for ctx in contexts:
        ctx.close()


# ---------------------------------------------------------------- helpers


def jpeg(color: tuple[int, int, int] = (200, 120, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1080, 1440), color).save(buf, "JPEG", quality=80)
    return buf.getvalue()


def upload(
    page: Page, ext: str = "beer", color: tuple[int, int, int] = (200, 120, 40)
) -> dict[str, Any]:
    """Upload a photo as the page's guest, through the real API. Returns the JSON."""
    meta = {"vessel": "bottle"} if ext == "beer" else {"filter": "normal", "facing": "user"}
    answer: dict[str, Any] = page.evaluate(
        """async ([ext, data, meta]) => {
            const res = await fetch(`/api/x/${ext}/upload`, {method: 'POST',
                headers: {'Content-Type': 'image/jpeg', 'X-VB-Meta': encodeURIComponent(meta)},
                body: new Uint8Array(data)});
            return {status: res.status, ...(await res.json())};
        }""",
        [ext, list(jpeg(color)), json.dumps(meta)],
    )
    assert answer["status"] == 201, answer
    return answer


def only_user(live: LiveServer) -> Any:
    [user] = live.core.repos.users.list()
    return user


def no_horizontal_scroll(page: Page) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"))


def errors_besides(page: Page, *needles: str) -> list[str]:
    """Console errors minus the lines a test caused on purpose (failed requests)."""
    errors: list[str] = page.js_errors  # type: ignore[attr-defined]
    return [e for e in errors if not any(n in e for n in needles)]
