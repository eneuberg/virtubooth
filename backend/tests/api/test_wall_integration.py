"""The Live-Wall wired into the rest of the app: the join texts and the guest's
analysis opt-out, the corner QR code from the QR codes, the host's event name."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from virtubooth.app import create_app
from virtubooth.extensions.wall import make_extension
from virtubooth.services.identity import WALL_ANALYSIS_TEXT

from ..conftest import BASE_URL, ORIGIN, PARTY_TOKEN, fp, scan
from .wall_support import (
    FakeEnrichment,
    Stream,
    internal_id,
    live_admin,
    live_server,
    live_wall,
    put_config,
    upload,
    with_wall_page,
)


@pytest.fixture
def extensions(demo_extension):
    return [demo_extension, make_extension(enrichment=FakeEnrichment())]


@pytest.fixture
def web_dir(web_dir):
    return with_wall_page(web_dir)


def identify(client):
    r = client.post("/api/identify", json={"fp": fp()}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def join(client, **extra):
    r = client.post(
        "/api/join", json={"accept": True, "version": "1", "fp": fp(), **extra}, headers=ORIGIN
    )
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------- join texts, opt-out


def test_join_texts_name_the_analysis(client):
    scan(client)
    consent = identify(client)["consent"]
    assert consent["analysis"] is True
    assert consent["paragraphs"][-2] == WALL_ANALYSIS_TEXT
    assert consent["paragraphs"][-1].startswith("Wenn du das nicht möchtest")


def test_opt_out_at_join_and_later(client, core):
    scan(client)
    body = join(client, analysis_opt_out=True)
    assert body["user"]["analysis_opt_out"] is True
    pid = upload(client)
    photo_id = internal_id(core, pid)
    # an analysis the worker made meanwhile is dropped and queued again
    with core.db.tx() as c:
        c.execute(
            "INSERT INTO wall_analysis (photo_id, state, data, versions, rev) "
            "VALUES (?, 'done', '{\"boxes\": [1]}', '{\"faces\": \"1\"}', 7)",
            (photo_id,),
        )
        c.execute("INSERT INTO wall_facts VALUES (?, 'faces', 3)", (photo_id,))
    r = client.put("/api/me/analysis", json={"opt_out": False}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["user"]["analysis_opt_out"] is False
    row = core.db.one("SELECT state, data, versions, rev FROM wall_analysis WHERE photo_id=?",
                      (photo_id,))  # fmt: skip
    assert tuple(row) == ("pending", "{}", "{}", 8)
    assert core.db.one("SELECT COUNT(*) FROM wall_facts WHERE photo_id=?", (photo_id,))[0] == 0
    r = client.put("/api/me/analysis", json={"opt_out": True}, headers=ORIGIN)
    assert r.json()["user"]["analysis_opt_out"] is True
    assert identify(client)["user"]["analysis_opt_out"] is True


def test_opt_out_needs_a_guest(client):
    scan(client)
    r = client.put("/api/me/analysis", json={"opt_out": True}, headers=ORIGIN)
    assert r.status_code == 401


def test_join_texts_without_the_wall(settings, demo_extension):
    app = create_app(settings, extensions=[demo_extension])
    try:
        with TestClient(app, base_url=BASE_URL, follow_redirects=False) as c:
            scan(c)
            consent = identify(c)["consent"]
            assert consent["analysis"] is False
            assert WALL_ANALYSIS_TEXT not in consent["paragraphs"]
    finally:
        app.state.core.db.close()


# ------------------------------------------------------------ the QR corner


def test_qr_corner_follows_the_codes(admin, core):
    r = admin.put("/api/x/wall/admin/password", json={"password": "geheim-123"}, headers=ORIGIN)
    assert r.status_code == 200
    assert admin.get("/livewall/api/feed").json()["qr"] is None  # overlay.qr is off
    config = put_config(admin)["config"]
    put_config(admin, overlay=config["overlay"] | {"qr": True})
    first = core.repos.codes.list()[0]
    feed = admin.get("/livewall/api/feed").json()
    assert feed["qr"] == {"url": f"http://testserver/?t={PARTY_TOKEN}", "name": first.name}

    r = admin.post("/api/admin/codes", json={"target": "demo", "note": ""}, headers=ORIGIN)
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    put_config(admin, overlay=config["overlay"] | {"qr": True, "qr_code_id": code["id"]})
    qr = admin.get("/livewall/api/feed").json()["qr"]
    assert qr["name"] == code["name"] and qr["url"].startswith("http://testserver/x/demo/?t=")
    assert admin.delete(f"/api/admin/codes/{code['id']}", headers=ORIGIN).status_code == 200
    assert admin.get("/livewall/api/feed").json()["qr"] is None  # revoked: no fallback


@pytest.fixture
def live(app):
    with live_server(app) as server:
        yield server


def test_event_name_and_code_changes_reach_open_walls(live):
    admin = live_admin(live)
    try:
        r = admin.put("/api/x/wall/admin/password", json={"password": "geheim-123"},
                      headers=live.origin)  # fmt: skip
        assert r.status_code == 200
        config = admin.get("/api/x/wall/admin/config").json()["config"]
        config["overlay"]["qr"] = True
        assert admin.put("/api/x/wall/admin/config", json=config, headers=live.origin).is_success
        wall = live_wall(live)
        stream = Stream(wall, "/livewall/api/stream")
        try:
            stream.until("hello")
            r = admin.put("/api/admin/settings/event", json={"name": "Lenas 30."},
                          headers=live.origin)  # fmt: skip
            assert r.status_code == 200
            msg = stream.until("config")
            assert msg["data"]["event_name"] == "Lenas 30."
            # the event name changed for the qr data too: a path (no VB_PUBLIC_BASE_URL)
            assert msg["data"]["qr"]["url"] == f"/?t={PARTY_TOKEN}"
            assert wall.get("/livewall/api/feed").json()["event_name"] == "Lenas 30."
            r = admin.post("/api/admin/codes/1/token", json={"token": None}, headers=live.origin)
            assert r.status_code == 200, r.text
            msg = stream.until("config")
            assert msg["data"]["qr"]["url"] != f"/?t={PARTY_TOKEN}"
        finally:
            stream.close()
            wall.close()
    finally:
        admin.close()
