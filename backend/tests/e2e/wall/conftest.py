"""Fixtures of the Live-Wall screen e2e tests (W2).

The backend on this branch has no wall yet, so `WallFake` answers everything under
/livewall with `page.route`: the page is the BUILT `wall.html` with the real CSP header,
the screen API (session, feed, categories, stream, media) comes from the fake's state.
Assets (/assets/…, fonts, /boot-check.js) come from the live server.

The stream is one `text/event-stream` answer per request: `retry`, `hello`, then the
events queued since the last stream request. The browser reconnects after `retry_ms`
(and the wall refetches /feed then), so the fake's feed always matches its events.
`hold_stream = True` leaves stream requests unanswered (a quiet, never failing stream).
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Iterator
from copy import deepcopy
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image, ImageDraw
from playwright.sync_api import Browser, BrowserContext, Page, Route

from virtubooth.core.security import SECURITY_HEADERS
from virtubooth.settings import REPO_ROOT

from ..conftest import WEB_DIR, LiveServer, track_errors

PASSWORD = "wall-geheim"
TV = {"viewport": {"width": 1920, "height": 1080}}
MOCKUPS = REPO_ROOT / "docs" / "overhaul" / "design" / "mockups" / "img"

DEFAULT_CONFIG: dict[str, Any] = {
    "rev": 1,
    "updated_at": None,
    "by": None,
    "playlist": [
        {"mode": "spotlight", "enabled": True, "duration_s": 120},
        {"mode": "gallery", "enabled": True, "duration_s": 45},
        {"mode": "categories", "enabled": True, "duration_s": 60},
    ],
    "spotlight": {
        "algorithm": "fresh_first",
        "n": 12,
        "interval_s": 8,
        "transition": "random",
        "transition_ms": 1200,
    },
    "gallery": {"speed": "medium", "rows": 3},
    "categories": {"per_category_s": 10, "disabled": []},
    "sources": [],
    "delay_s": 20,
    "show_instagram": False,
    "look": {
        "preset": "blobs",
        "primary": "#a855f7",
        "secondary": "#ff4fa3",
        "background": "#2b2b31",
        "fps": 30,
        "calm": False,
    },
    "overlay": {"event_name": True, "counter": True, "qr": False, "corner": "bottom-right"},
}

PALETTE = [
    (255, 79, 163),
    (168, 85, 247),
    (56, 189, 248),
    (250, 204, 21),
    (52, 211, 153),
    (251, 113, 133),
]


@cache
def fixture_jpeg(n: int, size: tuple[int, int] = (720, 960)) -> bytes:
    """A colourful test photo: a mockup scene when the repo has them, else drawn shapes."""
    scenes = sorted(MOCKUPS.glob("*.jpg")) if MOCKUPS.is_dir() else []
    if scenes:
        img = Image.open(scenes[n % len(scenes)]).convert("RGB")
        img = img.resize(size, Image.Resampling.LANCZOS)
    else:
        w, h = size
        img = Image.new("RGB", size, PALETTE[n % len(PALETTE)])
        draw = ImageDraw.Draw(img)
        for i in range(6):
            c = PALETTE[(n + i + 1) % len(PALETTE)]
            r = w // (3 + i % 3)
            x, y = (w * (i * 37 % 100)) // 100, (h * (i * 61 % 100)) // 100
            draw.ellipse((x - r, y - r, x + r, y + r), fill=c)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def wall_photo(
    n: int, author: str = "Lena", instagram: str | None = None, minutes_ago: int = 3
) -> dict[str, Any]:
    pid = f"ph{n:04d}"
    return {
        "id": pid,
        "source": "booth",
        "seq": n,
        "taken_at": f"__minutes_ago__{minutes_ago}",
        "width": 720,
        "height": 960,
        "author": author,
        "instagram": instagram,
        "author_key": author.lower(),
        "urls": {
            "s": f"/livewall/media/{pid}?s=s",
            "m": f"/livewall/media/{pid}?s=m",
            "l": f"/livewall/media/{pid}?s=l",
        },
        "facts": {"people": 2, "faces": 2},
        "analysis": "done",
    }


def _now_iso(minutes_ago: int = 0) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def _resolve_times(value: Any) -> Any:
    """`__minutes_ago__N` placeholders → ISO times relative to now (feeds are built late)."""
    if isinstance(value, dict):
        return {k: _resolve_times(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_times(v) for v in value]
    if isinstance(value, str) and value.startswith("__minutes_ago__"):
        return _now_iso(int(value.removeprefix("__minutes_ago__")))
    return value


class WallFake:
    """The screen API of PLAN-WALL §4.2, answered from this object's state."""

    def __init__(self, live: LiveServer) -> None:
        self.live = live
        self.session = "login"  # "ok" | "login" | "nopassword"
        self.config: dict[str, Any] = deepcopy(DEFAULT_CONFIG)
        self.event_name = "E2E Party"
        self.qr: dict[str, str] | None = None  # the corner's QR code (`overlay.qr` on)
        self.photos: list[dict[str, Any]] = []  # newest first
        self.categories: list[dict[str, Any]] = []
        self.pending: list[tuple[str, dict[str, Any]]] = []
        self.event_id = 0
        self.retry_ms = 300
        self.hold_stream = False
        self.requests: list[str] = []
        self.held: list[Route] = []
        html = (WEB_DIR / "wall.html").read_text(encoding="utf-8")
        self.html = html
        # the theme's style layer on <html data-vb-style> (the real server writes it,
        # by default "goofy"); None: the plain page, the calm base most tests measure
        self.style: str | None = None

    # ------------------------------------------------------------- test API

    def url(self) -> str:
        return self.live.url("/livewall")

    def add(self, photo: dict[str, Any], live: bool = False) -> None:
        self.photos.insert(0, photo)
        if live:
            self.emit("photo.add", {"photo": photo})

    def remove(self, *ids: str) -> None:
        self.photos = [p for p in self.photos if p["id"] not in ids]
        self.emit("photo.remove", {"ids": list(ids)})

    def set_config(self, **changes: Any) -> None:
        """Top-level keys; dicts are merged one level deep. Emits a `config` event."""
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(self.config.get(key), dict):
                self.config[key] = {**self.config[key], **value}
            else:
                self.config[key] = value
        self.config["rev"] += 1
        self.emit(
            "config",
            {"config": deepcopy(self.config), "event_name": self.event_name, "qr": self._qr()},
        )

    def _qr(self) -> dict[str, str] | None:
        return self.qr if self.config["overlay"].get("qr") else None

    def emit(self, event: str, data: dict[str, Any]) -> None:
        self.pending.append((event, data))

    def install(self, context: BrowserContext) -> None:
        context.route(re.compile(r"^https?://[^/]+/livewall(?:[/?]|$)"), self._handle)

    # ------------------------------------------------------------- answers

    def _json(self, route: Route, status: int, body: Any) -> None:
        route.fulfill(
            status=status,
            headers={"Content-Type": "application/json", "Cache-Control": "no-store"},
            body=json.dumps(_resolve_times(body)),
        )

    def _error(self, route: Route, status: int, code: str, message: str) -> None:
        self._json(route, status, {"error": code, "message": message})

    def _auth(self, route: Route) -> bool:
        if self.session == "ok":
            return True
        self._error(route, 401, "wall_login_required", "Bitte zuerst anmelden.")
        return False

    def _feed(self) -> dict[str, Any]:
        return {
            "config": self.config,
            "event_name": self.event_name,
            "qr": self._qr(),
            "total": len(self.photos),
            "photos": self.photos,
            "cursor": self.event_id,
            "server_time": _now_iso(),
        }

    def _stream_body(self) -> str:
        parts = [f"retry: {self.retry_ms}\n\n"]
        hello = {"config_rev": self.config["rev"], "server_time": _now_iso()}
        parts.append(f"event: hello\ndata: {json.dumps(hello)}\n\n")
        for event, data in self.pending:
            self.event_id += 1
            parts.append(
                f"id: {self.event_id}\nevent: {event}\ndata: {json.dumps(_resolve_times(data))}\n\n"
            )
        self.pending = []
        return "".join(parts)

    def _handle(self, route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        self.requests.append(f"{request.method} {path}")
        if path.startswith("/livewall/media/"):
            pid = path.rsplit("/", 1)[-1]
            match = next((p for p in self.photos if p["id"] == pid), None)
            if match is None or self.session != "ok":
                route.fulfill(status=404, body="")
                return
            size = (parse_qs(parsed.query).get("s") or ["m"])[0]
            dims = {"s": (300, 400), "m": (720, 960), "l": (1080, 1440)}.get(size, (720, 960))
            route.fulfill(
                status=200,
                headers={"Content-Type": "image/jpeg", "Cache-Control": "private, max-age=86400"},
                body=fixture_jpeg(match["seq"], dims),
            )
            return
        if path == "/livewall/api/session":
            if request.method == "POST":
                body = json.loads(request.post_data or "{}")
                if self.session == "nopassword":
                    self._error(
                        route,
                        409,
                        "wall_no_password",
                        "Für die Live-Wall ist kein Passwort gesetzt.",
                    )
                elif body.get("password") != PASSWORD:
                    self._error(route, 403, "wrong_password", "Das Passwort stimmt nicht.")
                else:
                    self.session = "ok"
                    self._json(route, 200, {"ok": True, "via": "password"})
                return
            if self.session == "ok":
                self._json(route, 200, {"ok": True, "via": "password"})
            elif self.session == "nopassword":
                self._error(
                    route, 409, "wall_no_password", "Für die Live-Wall ist kein Passwort gesetzt."
                )
            else:
                self._error(route, 401, "wall_login_required", "Bitte zuerst anmelden.")
            return
        if path == "/livewall/api/feed":
            if self._auth(route):
                self._json(route, 200, self._feed())
            return
        if path == "/livewall/api/categories":
            if self._auth(route):
                self._json(route, 200, {"categories": self.categories})
            return
        if path == "/livewall/api/stream":
            if self.session != "ok":
                self._error(route, 401, "wall_login_required", "Bitte zuerst anmelden.")
                return
            if self.hold_stream:
                self.held.append(route)  # never answered: a quiet stream
                return
            route.fulfill(
                status=200,
                headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store"},
                body=self._stream_body(),
            )
            return
        if path.startswith("/livewall/api/"):
            self._error(route, 404, "not_found", "Gibt es nicht.")
            return
        # the page: the built wall.html with the server's security headers
        route.fulfill(
            status=200,
            headers={
                **SECURITY_HEADERS,
                "Content-Type": "text/html; charset=utf-8",
                "Cache-Control": "private, no-cache",
            },
            body=self.html
            if self.style is None
            else self.html.replace("<html", f'<html data-vb-style="{self.style}"', 1),
        )


@pytest.fixture
def wall_fake(live: LiveServer) -> WallFake:
    if not (WEB_DIR / "wall.html").is_file():
        pytest.skip(f"no wall.html in {WEB_DIR}: rebuild the frontend")
    return WallFake(live)


@pytest.fixture
def tv_context(browser: Browser, wall_fake: WallFake) -> Iterator[BrowserContext]:
    ctx = browser.new_context(**TV)
    wall_fake.install(ctx)
    yield ctx
    ctx.close()


@pytest.fixture
def tv_page(tv_context: BrowserContext) -> Page:
    return track_errors(tv_context.new_page())


def js_errors(page: Page, *answers: int) -> list[str]:
    """page.js_errors without the console lines browsers log for expected API answers
    (`answers`: HTTP statuses of /livewall/api/ requests, e.g. 401 before the login)."""
    errors: list[str] = page.js_errors  # type: ignore[attr-defined]
    return [
        e
        for e in errors
        if not (
            "Failed to load resource" in e
            and "/livewall/api/" in e
            and any(f"status of {code}" in e for code in answers)
        )
    ]


def css_var(page: Page, name: str) -> str:
    value: str = page.evaluate(
        "(n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim()", name
    )
    return value


def shots_dir() -> Path | None:
    from ..conftest import SCREENSHOT_DIR

    return Path(SCREENSHOT_DIR) if SCREENSHOT_DIR else None
