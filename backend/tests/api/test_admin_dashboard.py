"""The dashboard: the join stop („Anmeldung stoppen“), the visitor id behind
"Gescannt", the throttled last-seen times behind "Aktiv jetzt", and the live
overview (`GET /api/admin/overview`). Auth for these routes is in the route
table of test_admin_api.py."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from virtubooth.core.clock import iso
from virtubooth.db.database import Database
from virtubooth.services.presence import THROTTLE_SECONDS
from virtubooth.tools.export import SCRUBBED_TABLES, take_snapshot

from ..conftest import JPEG, ORIGIN, PARTY_TOKEN, accept_consent, fp, jpeg, scan
from ..unit.test_core_db_migration import make_v1_db
from .test_admin_upload_controls import _collect_events

CLOSED_MSG = "Gerade kann niemand neu beitreten. Versuch es gleich noch mal."


def post(client, path, json=None, status=200):
    r = client.post(path, json=json, headers=ORIGIN)
    assert r.status_code == status, r.text
    return r.json()


def identify(client) -> dict:
    return post(client, "/api/identify", {})


def join(client, n=1):
    return client.post(
        "/api/join",
        json={"accept": True, "version": "1", "instagram": None, "fp": fp(n)},
        headers=ORIGIN,
    )


def upload(client, ext="demo"):
    return client.post(f"/api/x/{ext}/upload", content=jpeg(400, 400), headers=JPEG)


def join_stop(admin, enabled):
    return post(admin, "/api/admin/join-stop", {"enabled": enabled})


def overview(admin) -> dict:
    r = admin.get("/api/admin/overview")
    assert r.status_code == 200, r.text
    return r.json()


def visitor_of(core, client) -> str:
    vid = core.signer.unsign("vid", client.cookies.get("vb_vid"))
    assert vid
    return vid


def user_id_of(core, client) -> int:
    public_id = core.signer.unsign("uid", client.cookies.get("vb_uid"))
    user = core.repos.users.get_by_public_id(public_id)
    assert user is not None
    return user.id


def set_cookie_header(response, name):
    return next(h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}="))


# ------------------------------------------------------------- join stop


def test_join_stop_turns_new_devices_away_and_keeps_joined_guests(admin, guest, make_client, core):
    joined = guest()
    newcomer = make_client()
    scan(newcomer)

    state = join_stop(admin, True)
    assert state["enabled"] is True and state["changed"] is True and state["since"]
    assert admin.get("/api/admin/join-stop").json()["enabled"] is True

    # unknown device: the join sheet learns it up front, a join is refused
    answer = identify(newcomer)
    assert answer["state"] == "needs_consent" and answer["join_closed"] is True
    r = join(newcomer, 2)
    assert r.status_code == 403
    assert r.json() == {"error": "join_closed", "message": CLOSED_MSG}
    assert core.repos.users.list() and len(core.repos.users.list()) == 1

    # the joined guest carries on: identify, a second tab's join, uploads
    assert identify(joined)["state"] == "ok"
    assert join(joined).status_code == 200
    assert upload(joined).status_code == 201

    # the same again: no change, no second audit entry
    assert join_stop(admin, True)["changed"] is False
    state = join_stop(admin, False)
    assert state["enabled"] is False and state["since"] is None and state["changed"] is True
    assert identify(newcomer)["join_closed"] is False
    assert join(newcomer, 2).status_code == 201

    actions = [e.action for e in core.repos.audit.list()]
    assert actions.count("join.stop") == 1 and actions.count("join.resume") == 1


def test_join_stop_and_upload_stop_are_independent(admin, guest, make_client):
    joined = guest()
    join_stop(admin, True)
    assert upload(joined).status_code == 201  # uploads unaffected by the join stop
    post(admin, "/api/admin/upload-stop", {"enabled": True})
    assert upload(joined).json()["error"] == "uploads_stopped"
    join_stop(admin, False)
    assert upload(joined).json()["error"] == "uploads_stopped"  # still stopped
    assert admin.get("/api/admin/upload-stop").json()["enabled"] is True


def test_join_stop_survives_a_restart(admin, settings, extensions):
    from virtubooth.app import create_app

    join_stop(admin, True)
    other = create_app(settings, extensions=extensions)
    try:
        assert other.state.core.services.join_controls.join_stopped()
    finally:
        other.state.core.db.close()


def test_join_stop_publishes_events(admin, core):
    def act():
        join_stop(admin, True)
        join_stop(admin, True)  # no change, no event
        join_stop(admin, False)

    events = _collect_events(core, act, 2)
    assert [e["type"] for e in events] == ["settings.join_stop", "settings.join_stop"]
    assert events[0]["data"]["join_stop"]["enabled"] is True
    assert events[0]["data"]["join_stop"]["by"]
    assert events[1]["data"]["join_stop"] == {
        "enabled": False,
        "since": None,
        "by": events[0]["data"]["join_stop"]["by"],
    }


# ------------------------------------------------------------- visitor id


def test_qr_entry_sets_a_visitor_id_once(client, core):
    r = client.get(f"/?t={PARTY_TOKEN}")
    assert r.status_code == 303
    header = set_cookie_header(r, "vb_vid").lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/" in header
    assert "secure" not in header  # http test server, cookie_secure auto
    vid = visitor_of(core, client)
    assert core.db.one("SELECT user_id FROM visitors WHERE id=?", (vid,))[0] is None

    # scanning again (another QR code) keeps the id: one visitor, not two
    r = client.get(f"/x/demo/?t={PARTY_TOKEN}")
    assert r.status_code == 303 and "vb_vid=" not in r.headers.get("set-cookie", "")
    assert visitor_of(core, client) == vid
    assert core.db.one("SELECT COUNT(*) FROM visitors")[0] == 1


def test_wrong_token_sets_no_visitor_id(client, core):
    r = client.get("/?t=wrong-token")
    assert "vb_vid" not in r.headers.get("set-cookie", "")
    assert core.db.one("SELECT COUNT(*) FROM visitors")[0] == 0


def test_visitor_cookie_is_secure_like_the_others(make_client, core, settings):
    core.settings = settings.replace(cookie_secure="true")
    c = make_client()
    r = c.get(f"/?t={PARTY_TOKEN}")
    for name in ("vb_access", "vb_vid"):
        assert "secure" in set_cookie_header(r, name).lower(), name


def test_joining_links_the_visitor_to_the_guest(client, core):
    scan(client)
    vid = visitor_of(core, client)
    accept_consent(client)
    assert core.repos.presence.visitor_user(vid) == user_id_of(core, client)
    # later anonymous visits never undo the link
    core.repos.presence.visit(vid, at=iso(datetime.now(UTC)))
    assert core.repos.presence.visitor_user(vid) == user_id_of(core, client)


def test_a_guest_from_before_gets_a_visitor_on_its_next_visit(client, core):
    """Guests who joined before the dashboard existed have no visitor id: their
    next identify gives them one, linked to them."""
    scan(client)
    accept_consent(client)
    client.cookies.delete("vb_vid")
    core.db.all("DELETE FROM visitors")
    r = client.post("/api/identify", json={}, headers=ORIGIN)
    assert r.status_code == 200 and "vb_vid=" in r.headers.get("set-cookie", "")
    assert core.repos.presence.visitor_user(visitor_of(core, client)) == user_id_of(core, client)


def test_a_forged_visitor_id_is_replaced(client, core):
    client.cookies.set("vb_vid", "made-up.id", domain="testserver.local")
    scan(client)
    vid = visitor_of(core, client)
    assert vid != "made-up"
    assert core.db.one("SELECT id FROM visitors")[0] == vid


def test_visitors_hold_only_random_ids_and_timestamps(core):
    cols = [r[1] for r in core.db.all("PRAGMA table_info(visitors)")]
    assert cols == ["id", "first_seen_at", "last_seen_at", "user_id"]


# ---------------------------------------------------------- last seen


def _age_everyone(core, minutes=30):
    old = iso(datetime.now(UTC) - timedelta(minutes=minutes))
    with core.db.tx() as c:
        c.execute("UPDATE users SET last_seen_at=?", (old,))
        c.execute("UPDATE visitors SET last_seen_at=?", (old,))
    return old


def test_guest_requests_refresh_last_seen_at_most_once_a_minute(guest, core):
    clock = [1000.0]
    core.services.presence.clock = lambda: clock[0]
    g = guest()
    user_id = user_id_of(core, g)

    old = _age_everyone(core)
    assert g.get("/api/me/photos").status_code == 200
    seen = core.repos.users.get(user_id).last_seen_at
    assert seen > old

    old = _age_everyone(core)
    clock[0] += THROTTLE_SECONDS - 1
    assert g.get("/api/extensions").status_code == 200
    assert core.repos.users.get(user_id).last_seen_at == old  # throttled

    clock[0] += 2
    assert upload(g).status_code == 201
    assert core.repos.users.get(user_id).last_seen_at > old


def test_visitors_that_did_not_join_are_seen_too(client, core):
    clock = [5000.0]
    core.services.presence.clock = lambda: clock[0]
    scan(client)
    vid = visitor_of(core, client)
    old = _age_everyone(core)
    clock[0] += THROTTLE_SECONDS + 1
    assert client.get("/api/extensions").status_code == 200
    row = core.db.one("SELECT last_seen_at FROM visitors WHERE id=?", (vid,))
    assert row[0] > old


def test_presence_forgets_stale_devices(core, monkeypatch):
    import virtubooth.services.presence as presence

    monkeypatch.setattr(presence, "_MAX_REMEMBERED", 3)
    clock = [0.0]
    service = core.services.presence
    service.clock = lambda: clock[0]
    for n in range(3):
        assert service._due(f"u:{n}")
    clock[0] += THROTTLE_SECONDS + 1
    assert service._due("u:new")
    assert len(service._last) == 1


# -------------------------------------------------------------- overview


def test_overview_of_an_empty_party(admin):
    data = overview(admin)
    assert data["active_minutes"] == 5 and data["at"]
    assert data["guests"] == {
        "total": 0, "active_now": 0, "uploading_now": 0, "instagram": 0, "banned": 0, "paused": 0,
    }  # fmt: skip
    assert data["scans"] == {
        "scanned": 0, "joined": 0, "not_joined": 0, "waiting_now": 0, "since": None,
    }  # fmt: skip
    assert data["photos"] == {
        "total": 0, "visible": 0, "hidden": 0, "last_15_min": 0, "last_60_min": 0,
        "last_upload_at": None,
    }  # fmt: skip
    assert data["activities"] == [
        {"id": "demo", "title": "Demo", "photos": 0, "visible": 0, "last_60_min": 0}
    ]


def test_overview_counts_the_party(admin, guest, make_client, core):
    anna = guest(instagram="anna")
    ben = guest(fp_n=2)
    cleo = guest(fp_n=3)
    for _ in range(2):
        lurker = make_client()
        scan(lurker)
        identify(lurker)

    photo_ids = [upload(anna).json()["photo"]["id"] for _ in range(3)]
    upload(ben)
    post(admin, f"/api/admin/photos/{photo_ids[0]}/hide")
    assert admin.delete(f"/api/admin/photos/{photo_ids[1]}", headers=ORIGIN).status_code == 200
    post(admin, f"/api/admin/users/{user_id_of(core, cleo)}/ban", {"reason": "x"})
    post(admin, f"/api/admin/users/{user_id_of(core, ben)}/uploads", {"paused": True})

    data = overview(admin)
    assert data["guests"] == {
        "total": 3,
        "active_now": 2,  # cleo is banned
        "uploading_now": 2,
        "instagram": 1,
        "banned": 1,
        "paused": 1,
    }
    scans = data["scans"]
    assert (scans["scanned"], scans["joined"], scans["not_joined"]) == (5, 3, 2)
    assert scans["waiting_now"] == 2 and scans["since"]
    # 4 uploads, one of them deleted since: still an upload of the last minutes
    assert data["photos"]["total"] == 3 and data["photos"]["hidden"] == 1
    assert data["photos"]["visible"] == 2
    assert data["photos"]["last_15_min"] == 4 and data["photos"]["last_60_min"] == 4
    assert data["photos"]["last_upload_at"]
    assert data["activities"] == [
        {"id": "demo", "title": "Demo", "photos": 3, "visible": 2, "last_60_min": 4}
    ]


def test_overview_windows(admin, guest, core):
    g = guest()
    for _ in range(3):
        upload(g)
    now = datetime.now(UTC)
    ids = [r[0] for r in core.db.all("SELECT id FROM photos ORDER BY id")]
    with core.db.tx() as c:
        for photo_id, minutes in zip(ids, (90, 30, 10), strict=True):
            c.execute(
                "UPDATE photos SET created_at=? WHERE id=?",
                (iso(now - timedelta(minutes=minutes)), photo_id),
            )
        c.execute("UPDATE users SET last_seen_at=?", (iso(now - timedelta(minutes=6)),))
    data = core.repos.overview.overview(now)
    assert (data.photos.last_15_min, data.photos.last_60_min) == (1, 2)
    assert data.guests.active_now == 0 and data.guests.uploading_now == 0
    assert data.activities[0].last_60_min == 2


def test_overview_lists_activities_only_old_photos_have(admin, guest, core):
    g = guest()
    upload(g)
    with core.db.tx() as c:
        c.execute("UPDATE photos SET extension='retired'")
    acts = {a["id"]: a for a in overview(admin)["activities"]}
    assert acts["retired"] == {
        "id": "retired", "title": "retired", "photos": 1, "visible": 1, "last_60_min": 1,
    }  # fmt: skip
    assert acts["demo"]["photos"] == 0


# ---------------------------------------------------- migration, archive


def test_an_old_database_gets_the_visitors_table(tmp_path):
    path = tmp_path / "virtubooth.db"
    make_v1_db(path)
    db = Database(path)
    try:
        from virtubooth.repositories.overview import OverviewReadModel

        assert db.one("PRAGMA user_version")[0] >= 4
        assert db.one("SELECT COUNT(*) FROM visitors")[0] == 0
        indexes = {r[1] for r in db.all("SELECT * FROM sqlite_master WHERE type='index'")}
        assert {"visitors_user", "users_last_seen", "photos_created"} <= indexes
        # counts start now: the old guests are there, no scans yet
        data = OverviewReadModel(db).overview()
        assert data.guests.total == 2 and data.guests.banned == 1
        assert data.scans.scanned == 0 and data.scans.since is None
    finally:
        db.close()


def test_the_archive_database_has_no_visitors(tmp_path):
    assert "visitors" in SCRUBBED_TABLES
    data = tmp_path / "data"
    db = Database(data / "virtubooth.db")
    with db.tx() as c:
        c.execute(
            "INSERT INTO visitors VALUES ('VISITOR-MARKER', '2026', '2026', NULL)",
        )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    snap = take_snapshot(data, scratch, include_hidden=True)
    db.close()
    assert b"VISITOR-MARKER" not in snap.db_file.read_bytes()
    conn = sqlite3.connect(snap.db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM visitors").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize("path", ["/api/admin/overview", "/api/admin/join-stop"])
def test_dashboard_reads_carry_the_event_cursor(admin, path):
    assert admin.get(path).headers["X-VB-Event-Id"]
