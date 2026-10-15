"""Helpers for the Live Wall tests (test_wall_*.py): a fake photo analysis, the
wall page in the stub build, and small API helpers.

Each test module loads the wall with

    @pytest.fixture
    def fake() -> FakeEnrichment: ...
    @pytest.fixture
    def extensions(demo_extension, fake): return [demo_extension, make_extension(enrichment=fake)]
    @pytest.fixture
    def web_dir(web_dir): return with_wall_page(web_dir)
"""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2 as httpx
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from virtubooth.core.clock import iso
from virtubooth.domain.models import User
from virtubooth.runtime import Core

from ..conftest import ADMIN_PASSWORD, JPEG, ORIGIN, PARTY_TOKEN, fp, jpeg

WALL_HTML = (
    '<!doctype html>\n<html lang="de"><head><meta charset="utf-8"><title>Live-Wall</title>'
    '</head><body><div id="root" data-testid="stub-wall"></div></body></html>\n'
)
WALL_PASSWORD = "geheim-123"


def with_wall_page(web_dir: Path) -> Path:
    (web_dir / "wall.html").write_text(WALL_HTML, encoding="utf-8")
    return web_dir


# ---------------------------------------------------------- fake analysis


@dataclass(frozen=True)
class FakeSummary:
    state: str
    facts: Mapping[str, float]


@dataclass
class FakeEnrichment:
    """Records the lifecycle calls; `analysed()` marks a photo as analysed
    (its summary and a change for the hub). The categories come from D1's
    engine over the database, not from here."""

    started: int = 0
    stopped: int = 0
    states: dict[int, FakeSummary] = field(default_factory=dict)
    rev: int = 0
    changes: list[tuple[int, int]] = field(default_factory=list)
    # analyzers switched on and able to run (FairFace "age" is off by default)
    active: set[str] = field(
        default_factory=lambda: {"basic", "faces", "emotion", "gestures", "objects", "tags"}
    )

    def active_analyzers(self) -> set[str]:
        return set(self.active)

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def analysed(self, photo_id: int, facts: Mapping[str, float], state: str = "done") -> None:
        self.rev += 1
        self.states[photo_id] = FakeSummary(state, dict(facts))
        self.changes.append((self.rev, photo_id))

    def summaries(self, photo_ids: Sequence[int]) -> dict[int, FakeSummary]:
        return {i: self.states[i] for i in photo_ids if i in self.states}

    def changes_since(self, rev: int, limit: int = 500) -> tuple[int, list[int]]:
        newer = [(r, pid) for r, pid in self.changes if r > rev][:limit]
        return (newer[-1][0] if newer else rev), [pid for _, pid in newer]


# ------------------------------------------------------------ API helpers


def upload(client: TestClient, ext: str = "demo") -> str:
    r = client.post(f"/api/x/{ext}/upload", content=jpeg(), headers=JPEG)
    assert r.status_code == 201, r.text
    photo_id: str = r.json()["photo"]["id"]
    return photo_id


def user_of(core: Core, client: TestClient) -> User:
    """The users row behind a guest client (via its signed uid cookie)."""
    public_id = core.signer.unsign("uid", client.cookies.get("vb_uid"))
    user = core.repos.users.get_by_public_id(public_id) if public_id else None
    assert user is not None
    return user


def internal_id(core: Core, public_id: str) -> int:
    pid = core.repos.photos.internal_id(public_id)
    assert pid is not None
    return pid


def age_photos(core: Core, seconds: int = 3600) -> None:
    """Every photo was taken `seconds` ago (past any wall delay)."""
    at = iso(datetime.now(UTC) - timedelta(seconds=seconds))
    with core.db.tx() as c:
        c.execute("UPDATE photos SET created_at=?", (at,))


def set_wall_password(admin: TestClient, password: str = WALL_PASSWORD) -> dict[str, Any]:
    r = admin.put("/api/x/wall/admin/password", json={"password": password}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def wall_login(client: TestClient, password: str = WALL_PASSWORD) -> Any:
    return client.post("/livewall/api/session", json={"password": password}, headers=ORIGIN)


def put_config(admin: TestClient, **changes: Any) -> dict[str, Any]:
    config = admin.get("/api/x/wall/admin/config").json()["config"]
    config.update(changes)
    r = admin.put("/api/x/wall/admin/config", json=config, headers=ORIGIN)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def audit_actions(core: Core) -> list[tuple[str, str, dict[str, Any]]]:
    """(action, target, details) of the audit log, newest first."""
    return [(e.action, e.target, e.details) for e in core.repos.audit.list()]


def wait_until(check: Callable[[], Any], timeout: float = 5.0) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.02)


# --------------------------------------------- a real server (SSE streams)


@dataclass
class Live:
    base_url: str
    core: Core

    @property
    def origin(self) -> dict[str, str]:
        return {"Origin": self.base_url}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@contextmanager
def live_server(app: FastAPI) -> Iterator[Live]:
    """uvicorn in a thread (TestClient can't stream SSE)."""
    port = _free_port()
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
    try:
        yield Live(f"http://127.0.0.1:{port}", app.state.core)
    finally:
        server.should_exit = True
        thread.join(5)


class Stream:
    """Reads an SSE response line by line in a thread."""

    def __init__(self, client: httpx.Client, url: str, headers: dict[str, str] | None = None):
        self._cm = client.stream("GET", url, headers=headers or {})
        self.response = self._cm.__enter__()
        self.lines: queue.Queue[str | None] = queue.Queue()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        try:
            for line in self.response.iter_lines():
                self.lines.put(line)
        except httpx.HTTPError:
            pass
        self.lines.put(None)  # stream ended

    def next(self, timeout: float = 5.0) -> dict[str, Any] | None:
        """The next message ({event, data (parsed), id?, retry?}); None when the
        stream ended. Comments (`: ping`) are skipped."""
        current: dict[str, Any] = {}
        while True:
            line = self.lines.get(timeout=timeout)
            if line is None:
                return None
            if line == "":
                if current:
                    if "data" in current:
                        current["data"] = json.loads(current["data"])
                    return current
                continue
            if line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            current[key] = value

    def until(self, event: str, timeout: float = 5.0) -> dict[str, Any]:
        """Skip messages up to the next `event`."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                msg = self.next(max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                raise AssertionError(f"no {event} within {timeout} s") from None
            assert msg is not None, f"stream ended before {event}"
            if msg.get("event") == event:
                return msg

    def ended(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.next(max(0.1, deadline - time.monotonic())) is None:
                return True
        return False

    def close(self) -> None:
        self._cm.__exit__(None, None, None)


def live_admin(live: Live) -> httpx.Client:
    c = httpx.Client(base_url=live.base_url, timeout=10)
    r = c.post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=live.origin)
    assert r.status_code == 200, r.text
    return c


def live_wall(live: Live, password: str = WALL_PASSWORD) -> httpx.Client:
    c = httpx.Client(base_url=live.base_url, timeout=10)
    r = c.post("/livewall/api/session", json={"password": password}, headers=live.origin)
    assert r.status_code == 200, r.text
    return c


def live_guest(live: Live, n: int = 5) -> httpx.Client:
    g = httpx.Client(base_url=live.base_url, timeout=10)
    g.get(f"/?t={PARTY_TOKEN}")
    r = g.post("/api/join", json={"accept": True, "version": "1", "fp": fp(n)}, headers=live.origin)
    assert r.status_code == 201, r.text
    return g


def live_upload(live: Live, guest: httpx.Client) -> str:
    r = guest.post("/api/x/demo/upload", content=jpeg(400, 300), headers=JPEG | live.origin)
    assert r.status_code == 201, r.text
    photo_id: str = r.json()["photo"]["id"]
    return photo_id
