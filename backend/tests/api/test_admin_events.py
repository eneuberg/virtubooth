"""GET /api/admin/events against a real server (TestClient can't stream SSE):
wire format, session end, resuming with Last-Event-ID / ?since=, resync, and
the overflow fix (the stream ends instead of going silent)."""

from __future__ import annotations

import asyncio
import queue
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx2 as httpx
import pytest
import uvicorn
from fastapi import FastAPI
from starlette.requests import Request

from virtubooth.api.routers.admin import events as events_router
from virtubooth.core.events import EventBus
from virtubooth.runtime import Core

from ..conftest import ADMIN_PASSWORD, JPEG, PARTY_TOKEN, fp, jpeg


@dataclass
class Live:
    base_url: str
    core: Core


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def live(app: FastAPI) -> Iterator[Live]:
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
    yield Live(f"http://127.0.0.1:{port}", app.state.core)
    server.should_exit = True
    thread.join(5)


def admin_client(live: Live) -> httpx.Client:
    c = httpx.Client(base_url=live.base_url, timeout=10)
    r = c.post(
        "/api/admin/login", json={"password": ADMIN_PASSWORD}, headers={"Origin": live.base_url}
    )
    assert r.status_code == 200
    return c


def guest_photo(live: Live) -> str:
    with httpx.Client(base_url=live.base_url, timeout=10) as g:
        g.get(f"/?t={PARTY_TOKEN}")
        r = g.post(
            "/api/join",
            json={"accept": True, "version": "1", "fp": fp(5)},
            headers={"Origin": live.base_url},
        )
        assert r.status_code == 201, r.text
        r = g.post(
            "/api/x/demo/upload", content=jpeg(400, 300), headers=JPEG | {"Origin": live.base_url}
        )
        assert r.status_code == 201, r.text
        photo_id: str = r.json()["photo"]["id"]
        return photo_id


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

    def wait_for(self, predicate, timeout: float = 5.0) -> str | None:
        while True:
            line = self.lines.get(timeout=timeout)
            if line is None or predicate(line):
                return line

    def messages(self, n: int, timeout: float = 5.0) -> list[dict[str, str]]:
        """The next n messages (event/data/id fields), skipping comments and
        the `retry:` preamble."""
        out: list[dict[str, str]] = []
        current: dict[str, str] = {}
        while len(out) < n:
            line = self.lines.get(timeout=timeout)
            assert line is not None, f"stream ended after {out}"
            if line == "":
                if "event" in current or "data" in current:
                    out.append(current)
                current = {}
            elif not line.startswith(":"):
                key, _, value = line.partition(": ")
                current[key] = value
        return out

    def close(self) -> None:
        self._cm.__exit__(None, None, None)


def hide(admin: httpx.Client, live: Live, photo_id: str, how: str = "hide") -> None:
    r = admin.post(f"/api/admin/photos/{photo_id}/{how}", headers={"Origin": live.base_url})
    assert r.status_code == 200, r.text


def test_event_stream(live, monkeypatch):
    monkeypatch.setattr(events_router, "SESSION_RECHECK_SECONDS", 0.0)
    pid = guest_photo(live)
    with httpx.Client(base_url=live.base_url, timeout=10) as anonymous:
        r = anonymous.get("/api/admin/events")
        assert r.status_code == 401 and r.json()["error"] == "admin_required"
    admin, other = admin_client(live), admin_client(live)
    stream = Stream(admin, "/api/admin/events")
    try:
        assert stream.response.headers["content-type"].startswith("text/event-stream")
        assert stream.response.headers["cache-control"] == "no-store"
        assert stream.response.headers["x-accel-buffering"] == "no"
        assert stream.wait_for(lambda line: line.startswith("retry:")) == "retry: 3000"
        hide(other, live, pid)
        assert stream.wait_for(lambda line: line == "event: photo.hidden")
        data = stream.wait_for(lambda line: line.startswith("data:"))
        assert pid in data and '"hidden": true' in data
        event_id = stream.wait_for(lambda line: line.startswith("id:"))
        assert event_id == f"id: {live.core.bus.epoch}-{live.core.bus.last_id}"
        # once this session logs out, the next event ends its stream
        admin.post("/api/admin/logout", headers={"Origin": live.base_url})
        hide(other, live, pid, "unhide")
        assert stream.wait_for(lambda line: False) is None
    finally:
        stream.close()
        admin.close()
        other.close()


def test_reconnect_with_last_event_id_replays_what_was_missed(live):
    pid = guest_photo(live)
    admin = admin_client(live)
    try:
        first = Stream(admin, "/api/admin/events")
        hide(admin, live, pid)
        (seen,) = first.messages(1)
        first.close()
        # while the browser is away
        hide(admin, live, pid, "unhide")
        hide(admin, live, pid)
        again = Stream(admin, "/api/admin/events", headers={"Last-Event-ID": seen["id"]})
        try:
            replayed = again.messages(2)
            assert [m["event"] for m in replayed] == ["photo.unhidden", "photo.hidden"]
            hide(admin, live, pid, "unhide")
            (live_msg,) = again.messages(1)
            assert live_msg["event"] == "photo.unhidden"
            ids = [int(m["id"].split("-")[1]) for m in (seen, *replayed, live_msg)]
            assert ids == sorted(ids) and len(set(ids)) == 4
        finally:
            again.close()
    finally:
        admin.close()


def test_first_fetch_and_stream_miss_nothing(live):
    """Bug: events between a page's first fetch and the stream's open were lost.
    The fetch's X-VB-Event-Id, passed as ?since=, replays them."""
    pid = guest_photo(live)
    admin = admin_client(live)
    try:
        r = admin.get("/api/admin/photos")
        cursor = r.headers["x-vb-event-id"]
        assert cursor.startswith(f"{live.core.bus.epoch}-")
        assert [p["hidden"] for p in r.json()["photos"]] == [False]
        hide(admin, live, pid)  # happens before the page opens its stream
        stream = Stream(admin, f"/api/admin/events?since={cursor}")
        try:
            (msg,) = stream.messages(1)
            assert msg["event"] == "photo.hidden" and pid in msg["data"]
        finally:
            stream.close()
    finally:
        admin.close()


def test_stale_cursor_starts_with_a_resync(live):
    admin = admin_client(live)
    try:
        stream = Stream(admin, "/api/admin/events", headers={"Last-Event-ID": "0badcafe-12"})
        try:
            (msg,) = stream.messages(1)
            assert msg == {"event": "stream.resync", "data": '{"reason": "restart"}'}
        finally:
            stream.close()
    finally:
        admin.close()


# --------------------------------------------- overflow (generator level)


def test_overflow_ends_the_stream_and_a_reconnect_catches_up(core):
    """Bug: an overflowed subscriber kept a live-looking stream that never
    delivered again. Now the stream ends; the reconnect replays the backlog."""
    token = core.services.admin_auth.login(ADMIN_PASSWORD, ip="10.0.0.1", user_agent="pytest")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/admin/events",
            "headers": [(b"cookie", f"vb_admin={token}".encode())],
        }
    )

    async def scenario():
        core.bus = EventBus(queue_size=3)
        core.bus.bind_loop(asyncio.get_running_loop())
        stream = events_router.admin_event_stream(request, core, None)
        retry = await anext(stream)  # subscribes
        assert retry.retry == 3000
        for i in range(5):  # a client that stopped reading
            core.bus.publish("photo.hidden", {"i": i})
        await asyncio.sleep(0.05)
        ended = False
        try:
            await asyncio.wait_for(anext(stream), 2)
        except StopAsyncIteration:
            ended = True
        # the browser reconnects with the last id it got (none here)
        cursor = core.bus.parse_cursor(f"{core.bus.epoch}-0")
        again = events_router.admin_event_stream(request, core, cursor)
        messages = [await anext(again) for _ in range(6)]
        await again.aclose()
        return ended, core.bus.subscriber_count, messages

    ended, subscribers, messages = asyncio.run(scenario())
    assert ended
    assert subscribers == 0
    assert messages[0].retry == 3000
    assert [m.event for m in messages[1:]] == ["photo.hidden"] * 5
    assert [m.raw_data for m in messages[1:]] == [f'{{"i": {i}}}' for i in range(5)]


def test_internal_events_never_reach_the_admin_stream(core):
    """`user.instagram` is for in-process listeners (the wall), not part of
    the AdminEvent contract: left out live and on replay."""
    token = core.services.admin_auth.login(ADMIN_PASSWORD, ip="10.0.0.1", user_agent="pytest")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/admin/events",
            "headers": [(b"cookie", f"vb_admin={token}".encode())],
        }
    )

    async def scenario():
        core.bus = EventBus()
        core.bus.bind_loop(asyncio.get_running_loop())
        core.bus.publish("user.instagram", {"id": 1, "instagram": "a"})
        core.bus.publish("photo.hidden", {"i": 0})
        cursor = core.bus.parse_cursor(f"{core.bus.epoch}-0")
        stream = events_router.admin_event_stream(request, core, cursor)
        replayed = [await anext(stream) for _ in range(2)]
        core.bus.publish("user.instagram", {"id": 1, "instagram": "b"})
        core.bus.publish("photo.hidden", {"i": 1})
        live = await asyncio.wait_for(anext(stream), 2)
        await stream.aclose()
        return [m.event for m in [*replayed, live]]

    assert asyncio.run(scenario()) == [None, "photo.hidden", "photo.hidden"]
