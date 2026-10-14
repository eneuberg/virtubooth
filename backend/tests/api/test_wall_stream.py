"""GET /livewall/api/stream against a real server: hello, photo events with the
delay, analysis updates, config, `bye` on logout, resuming."""

from __future__ import annotations

import re
import time

import httpx2 as httpx
import pytest

from virtubooth.extensions.wall import hub as hub_module
from virtubooth.extensions.wall import make_extension, screen_api

from .wall_support import (
    FakeEnrichment,
    Stream,
    internal_id,
    live_admin,
    live_guest,
    live_server,
    live_upload,
    live_wall,
    with_wall_page,
)


@pytest.fixture
def fake():
    return FakeEnrichment()


@pytest.fixture
def extensions(demo_extension, fake):
    return [demo_extension, make_extension(enrichment=fake)]


@pytest.fixture
def web_dir(web_dir):
    return with_wall_page(web_dir)


@pytest.fixture
def live(app, monkeypatch):
    monkeypatch.setattr(hub_module, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(hub_module, "CATEGORIES_DEBOUNCE_SECONDS", 0.2)
    with live_server(app) as server:
        yield server


@pytest.fixture
def admin_c(live):
    c = live_admin(live)
    r = c.put("/api/x/wall/admin/password", json={"password": "geheim-123"}, headers=live.origin)
    assert r.status_code == 200, r.text
    yield c
    c.close()


def put_config(live, admin, **changes):
    config = admin.get("/api/x/wall/admin/config").json()["config"]
    r = admin.put("/api/x/wall/admin/config", json=config | changes, headers=live.origin)
    assert r.status_code == 200, r.text
    return r.json()


def test_hello_and_photo_events(live, admin_c, fake):
    put_config(live, admin_c, delay_s=0)
    wall = live_wall(live)
    stream = Stream(wall, "/livewall/api/stream")
    try:
        assert stream.response.status_code == 200
        assert stream.response.headers["content-type"].startswith("text/event-stream")
        assert stream.next() == {"retry": "3000"}
        hello = stream.next()
        assert hello is not None and hello["event"] == "hello" and "id" not in hello
        assert hello["data"]["config_rev"] == 1 and hello["data"]["server_time"]
        guest = live_guest(live)
        pid = live_upload(live, guest)
        added = stream.until("photo.add")
        assert added["data"]["photo"]["id"] == pid and re.fullmatch(r"[0-9a-f]{8}-\d+", added["id"])
        assert added["data"]["photo"]["urls"]["m"] == f"/livewall/media/{pid}?s=m"
        admin_c.post(f"/api/admin/photos/{pid}/hide", headers=live.origin)
        assert stream.until("photo.remove")["data"] == {"ids": [pid]}
        admin_c.post(f"/api/admin/photos/{pid}/unhide", headers=live.origin)
        assert stream.until("photo.add")["data"]["photo"]["id"] == pid
        admin_c.delete(f"/api/admin/photos/{pid}", headers=live.origin)
        assert stream.until("photo.remove")["data"] == {"ids": [pid]}
        # the analysis finished: an update, then (debounced) the categories
        second = live_upload(live, guest)
        stream.until("photo.add")
        fake.analysed(internal_id(live.core, second), {"people": 2, "sharpness": 3.5})
        updated = stream.until("photo.update")["data"]["photo"]
        assert updated["id"] == second and updated["analysis"] == "done"
        assert updated["facts"] == {"people": 2}
        assert stream.until("categories.changed")["data"] == {}
        guest.close()
    finally:
        stream.close()
        wall.close()


def test_new_photos_wait_for_the_delay(live, admin_c):
    put_config(live, admin_c, delay_s=1)
    wall = live_wall(live)
    stream = Stream(wall, "/livewall/api/stream")
    try:
        stream.until("hello")
        guest = live_guest(live)
        started = time.monotonic()
        pid = live_upload(live, guest)
        added = stream.until("photo.add", timeout=5)
        assert added["data"]["photo"]["id"] == pid
        assert time.monotonic() - started >= 0.9
        # hidden while waiting: never added
        put_config(live, admin_c, delay_s=2)
        stream.until("config")
        other = live_upload(live, guest)
        admin_c.post(f"/api/admin/photos/{other}/hide", headers=live.origin)
        assert stream.until("photo.remove")["data"] == {"ids": [other]}
        with pytest.raises(AssertionError):
            stream.until("photo.add", timeout=3)
        guest.close()
    finally:
        stream.close()
        wall.close()


def test_config_event(live, admin_c):
    wall = live_wall(live)
    stream = Stream(wall, "/livewall/api/stream")
    try:
        stream.until("hello")
        put_config(live, admin_c, show_instagram=True)
        msg = stream.until("config")
        assert msg["data"]["config"]["show_instagram"] is True
        assert msg["data"]["config"]["rev"] == 1
        assert msg["data"]["event_name"] == "Testparty"
    finally:
        stream.close()
        wall.close()


@pytest.mark.parametrize(
    ("how", "reason"), [("password", "password"), ("clear", "password"), ("logout", "logout")]
)
def test_bye_ends_the_stream(live, admin_c, how, reason):
    wall = live_wall(live)
    watching_admin = Stream(admin_c, "/livewall/api/stream")
    stream = Stream(wall, "/livewall/api/stream")
    try:
        stream.until("hello")
        watching_admin.until("hello")
        if how == "password":
            r = admin_c.put(
                "/api/x/wall/admin/password", json={"password": "anderes-pw"}, headers=live.origin
            )
        elif how == "clear":
            r = admin_c.delete("/api/x/wall/admin/password", headers=live.origin)
        else:
            r = admin_c.post("/api/x/wall/admin/logout", headers=live.origin)
        assert r.status_code == 200, r.text
        assert stream.until("bye")["data"] == {"reason": reason}
        assert stream.ended()
        # the reconnect is refused
        r = wall.get("/livewall/api/stream")
        assert r.status_code == 401 and r.json()["error"] == "wall_login_required"
        # an admin watching the wall is not logged out
        put_config(live, admin_c, delay_s=5)
        assert watching_admin.until("config")
    finally:
        stream.close()
        watching_admin.close()
        wall.close()


def test_stream_rechecks_the_session(live, admin_c, monkeypatch):
    monkeypatch.setattr(screen_api, "RECHECK_SECONDS", 0.0)
    viewer = live_admin(live)
    stream = Stream(viewer, "/livewall/api/stream")
    try:
        stream.until("hello")
        viewer.post("/api/admin/logout", headers=live.origin)
        put_config(live, admin_c, delay_s=3)  # wakes the stream
        assert stream.ended()
    finally:
        stream.close()
        viewer.close()


def test_resume_with_last_event_id(live, admin_c):
    put_config(live, admin_c, delay_s=0)
    wall = live_wall(live)
    feed = wall.get("/livewall/api/feed").json()
    guest = live_guest(live)
    pid = live_upload(live, guest)  # before the stream opens
    stream = Stream(wall, f"/livewall/api/stream?since={feed['cursor']}")
    try:
        added = stream.until("photo.add")
        assert added["data"]["photo"]["id"] == pid
        last = added["id"]
    finally:
        stream.close()
    admin_c.post(f"/api/admin/photos/{pid}/hide", headers=live.origin)
    again = Stream(wall, "/livewall/api/stream", headers={"Last-Event-ID": last})
    try:
        assert again.until("photo.remove")["data"] == {"ids": [pid]}
    finally:
        again.close()
    stale = Stream(wall, "/livewall/api/stream", headers={"Last-Event-ID": "0badcafe-3"})
    try:
        assert stale.until("stream.resync")["data"] == {}
    finally:
        stale.close()
        guest.close()
        wall.close()


def test_open_walls_are_counted(live, admin_c):
    assert admin_c.get("/api/x/wall/admin/config").json()["open_walls"] == 0
    wall = live_wall(live)
    stream = Stream(wall, "/livewall/api/stream")
    try:
        stream.until("hello")
        assert admin_c.get("/api/x/wall/admin/config").json()["open_walls"] == 1
    finally:
        stream.close()
        wall.close()


def test_without_auth(live):
    with httpx.Client(base_url=live.base_url, timeout=5) as anonymous:
        r = anonymous.get("/livewall/api/stream")
        assert r.status_code == 401 and r.json()["error"] == "wall_login_required"


def test_one_wall_cookie_keeps_at_most_four_streams(live, admin_c):
    """WALL-03: a fifth stream of the same cookie closes the oldest; another
    wall (its own cookie) is not affected."""
    wall, other = live_wall(live), live_wall(live)
    streams = [Stream(wall, "/livewall/api/stream") for _ in range(4)]
    theirs = Stream(other, "/livewall/api/stream")
    try:
        for s in [*streams, theirs]:
            s.until("hello")
        streams.append(Stream(wall, "/livewall/api/stream"))
        streams[-1].until("hello")
        while (message := streams[0].next()) is not None:
            assert message.get("event") != "photo.add"
        assert admin_c.get("/api/x/wall/admin/config").json()["open_walls"] == 5
    finally:
        for s in [*streams, theirs]:
            s.close()
        wall.close()
        other.close()
