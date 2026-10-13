"""Upload controls: pause one guest, pause new guests (with restore/keep when
lifting it), stop all uploads. Auth for these routes is also covered by the
route table in test_admin_api.py."""

from __future__ import annotations

import asyncio
import threading

import pytest

from virtubooth.app import create_app
from virtubooth.domain.constants import PAUSE_ADMIN, PAUSE_NEW_GUEST_LOCK
from virtubooth.domain.models import PhotoQuery

from ..conftest import JPEG, ORIGIN, accept_consent, jpeg, scan

PAUSED_MSG = "Uploads sind für dich gerade pausiert. Die Gastgeber schalten sie bald wieder frei."
STOPPED_MSG = "Uploads sind gerade kurz gestoppt – gleich geht's weiter."


def upload(client, ext="demo"):
    return client.post(f"/api/x/{ext}/upload", content=jpeg(400, 400), headers=JPEG)


def can_upload(client) -> bool:
    r = upload(client)
    assert r.status_code in (201, 403), r.text
    return r.status_code == 201


def uid(core, client) -> int:
    public_id = core.signer.unsign("uid", client.cookies.get("vb_uid"))
    user = core.repos.users.get_by_public_id(public_id)
    assert user is not None
    return user.id


def post(client, path, json=None):
    r = client.post(path, json=json, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def lock_on(admin):
    return post(admin, "/api/admin/upload-pause", {"enabled": True})


def lock_off(admin, *, restore):
    return post(admin, "/api/admin/upload-pause", {"enabled": False, "restore": restore})


def set_paused(admin, user_id, paused):
    return post(admin, f"/api/admin/users/{user_id}/uploads", {"paused": paused})


def identify(client) -> dict:
    r = client.post("/api/identify", json={}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def _collect_events(core, action, n):
    """Run `action` while subscribed to the bus; return the first n events."""
    received = []
    loop = asyncio.new_event_loop()
    core.bus.bind_loop(loop)
    ready = threading.Event()

    async def listen():
        q = core.bus.subscribe()
        ready.set()
        while len(received) < n:
            received.append(await asyncio.wait_for(q.get(), 5))

    t = threading.Thread(target=loop.run_until_complete, args=(listen(),))
    t.start()
    ready.wait(5)
    action()
    t.join(10)
    loop.close()
    return received


# ---------------------------------------------------------------- one guest


def test_paused_guest_cannot_upload_but_keeps_everything_else(admin, guest, core):
    g = guest(instagram="anna")
    assert upload(g).status_code == 201
    user_id = uid(core, g)

    res = set_paused(admin, user_id, True)
    assert res["changed"] is True
    assert res["user"]["uploads_paused"] is True
    assert res["user"]["uploads_paused_source"] == PAUSE_ADMIN
    assert res["user"]["uploads_lock_period"] is None
    assert res["user"]["uploads_paused_at"]

    r = upload(g)
    assert r.status_code == 403
    assert r.json() == {"error": "uploads_paused", "message": PAUSED_MSG}
    # not a ban: photos stay visible, the guest can browse and edit the handle
    photos = core.repos.photos.list(PhotoQuery(user_id=user_id))
    assert len(photos) == 1 and not photos[0].hidden
    assert not core.repos.users.get(user_id).banned
    assert admin.get("/api/admin/photos?hidden=false").json()["total"] == 1
    assert g.get("/api/extensions").status_code == 200
    r = g.patch("/api/me", json={"instagram": "anna.neu"}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["user"]["uploads_paused"] is True
    me = identify(g)
    assert me["state"] == "ok" and me["user"]["uploads_paused"] is True
    # the guest sees only the flag, not why or since when
    assert set(me["user"]) == {
        "name",
        "instagram",
        "banned",
        "uploads_paused",
        "analysis_opt_out",
    }

    # idempotent
    assert set_paused(admin, user_id, True)["changed"] is False
    res = set_paused(admin, user_id, False)
    assert res["changed"] is True and res["user"]["uploads_paused"] is False
    assert res["user"]["uploads_paused_source"] is None
    assert set_paused(admin, user_id, False)["changed"] is False
    assert can_upload(g)
    assert identify(g)["user"]["uploads_paused"] is False

    entries = [e for e in core.repos.audit.list() if e.action.startswith("user.uploads_")]
    assert [e.action for e in entries] == ["user.uploads_unpause", "user.uploads_pause"]
    assert entries[0].details == {"source": PAUSE_ADMIN}
    assert all(e.actor.startswith("admin:") and e.target == f"user:{user_id}" for e in entries)


def test_set_user_uploads_validation(admin):
    def status(user_id, body):
        return admin.post(
            f"/api/admin/users/{user_id}/uploads", json=body, headers=ORIGIN
        ).status_code

    assert status(999, {"paused": True}) == 404
    assert status(0, {"paused": True}) == 422
    assert status(1, {}) == 422
    assert status(1, {"paused": "x"}) == 422


def test_ban_wins_over_pause(admin, guest, core):
    g = guest()
    user_id = uid(core, g)
    set_paused(admin, user_id, True)
    post(admin, f"/api/admin/users/{user_id}/ban", {"reason": "x"})
    assert upload(g).json()["error"] == "banned"
    post(admin, f"/api/admin/users/{user_id}/unban")
    # unbanning doesn't lift the pause: they are separate
    assert upload(g).json()["error"] == "uploads_paused"


def test_users_filter_paused(admin, guest, core):
    a, b, c = guest(), guest(fp_n=2), guest(fp_n=3)
    set_paused(admin, uid(core, a), True)
    lock_on(admin)
    d = guest(fp_n=4)

    def ids(query):
        r = admin.get(f"/api/admin/users{query}")
        assert r.status_code == 200, r.text
        return sorted(u["id"] for u in r.json()["users"])

    assert ids("?paused=true") == sorted([uid(core, a), uid(core, d)])
    assert ids("?paused=false") == sorted([uid(core, b), uid(core, c)])
    assert len(ids("?paused=all")) == 4
    assert ids("?paused=true&banned=false") == sorted([uid(core, a), uid(core, d)])
    assert admin.get("/api/admin/users?paused=maybe").status_code == 400
    listed = {u["id"]: u for u in admin.get("/api/admin/users").json()["users"]}
    assert listed[uid(core, a)]["uploads_paused_source"] == PAUSE_ADMIN
    assert listed[uid(core, d)]["uploads_paused_source"] == PAUSE_NEW_GUEST_LOCK


def test_photo_user_ref_shows_pause(admin, guest, core):
    g = guest()
    assert can_upload(g)
    set_paused(admin, uid(core, g), True)
    assert admin.get("/api/admin/photos").json()["photos"][0]["user"]["uploads_paused"] is True


# ---------------------------------------------------------- new-guest lock


def test_lock_pauses_only_guests_who_join_while_it_is_on(admin, guest, core):
    before = guest()
    assert admin.get("/api/admin/upload-pause").json() == {
        "enabled": False, "since": None, "period": None, "by": None, "affected": 0, "paused_total": 0,
    }  # fmt: skip
    res = lock_on(admin)
    assert res["enabled"] is True and res["changed"] is True
    assert res["since"] and res["period"] == 1 and res["affected"] == 0
    assert lock_on(admin)["changed"] is False  # already on: same period

    during = guest(fp_n=2)
    joined = core.repos.users.get(uid(core, during))
    assert joined.uploads_paused_source == PAUSE_NEW_GUEST_LOCK and joined.uploads_lock_period == 1
    assert joined.uploads_paused_at == joined.created_at
    r = upload(during)
    assert r.status_code == 403 and r.json() == {"error": "uploads_paused", "message": PAUSED_MSG}
    assert can_upload(before)  # existing guests are unaffected
    assert identify(during)["user"]["uploads_paused"] is True
    state = admin.get("/api/admin/upload-pause").json()
    assert state["affected"] == 1 and state["paused_total"] == 1


def test_lift_lock_with_restore(admin, guest, core):
    before = guest()
    lock_on(admin)
    d1, d2, d3 = guest(fp_n=2), guest(fp_n=3), guest(fp_n=4)
    manual = uid(core, d2)
    # the admin pauses one of them by hand: restore must not free that guest
    set_paused(admin, manual, False)
    set_paused(admin, manual, True)
    # and frees another by hand early
    set_paused(admin, uid(core, d3), False)
    assert admin.get("/api/admin/upload-pause").json()["affected"] == 1

    res = lock_off(admin, restore=True)
    assert res["changed"] is True and res["enabled"] is False and res["since"] is None
    assert res["restored"] == 1 and res["kept"] == 0 and res["affected"] == 0
    assert can_upload(d1) and can_upload(d3) and can_upload(before)
    assert not can_upload(d2)
    assert core.repos.users.get(manual).uploads_paused_source == PAUSE_ADMIN
    after = guest(fp_n=5)
    assert can_upload(after)
    # already off: nothing to do
    assert lock_off(admin, restore=True)["changed"] is False

    entry = next(e for e in core.repos.audit.list() if e.action == "uploads.lock_off")
    assert entry.details == {"period": 1, "restore": True, "restored": 1, "kept": 0}
    assert entry.actor.startswith("admin:")
    assert any(e.action == "uploads.lock_on" for e in core.repos.audit.list())


def test_lift_lock_keep_paused(admin, guest, core):
    lock_on(admin)
    d1, d2 = guest(fp_n=2), guest(fp_n=3)
    res = lock_off(admin, restore=False)
    assert res["restored"] == 0 and res["kept"] == 2 and res["paused_total"] == 2
    assert not can_upload(d1) and not can_upload(d2)
    after = guest(fp_n=4)
    assert can_upload(after)

    # a second pause period: restoring it leaves the first period's guests paused
    second = lock_on(admin)
    assert second["period"] == 2 and second["affected"] == 0
    d3 = guest(fp_n=5)
    assert core.repos.users.get(uid(core, d3)).uploads_lock_period == 2
    res = lock_off(admin, restore=True)
    assert res["restored"] == 1
    assert can_upload(d3)
    assert not can_upload(d1) and not can_upload(d2)
    # the kept ones can still be freed one by one
    set_paused(admin, uid(core, d1), False)
    assert can_upload(d1)


def test_lift_lock_needs_a_choice(admin):
    lock_on(admin)
    r = admin.post("/api/admin/upload-pause", json={"enabled": False}, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["error"] == "restore_required"
    assert admin.get("/api/admin/upload-pause").json()["enabled"] is True
    assert admin.post("/api/admin/upload-pause", json={}, headers=ORIGIN).status_code == 422


def test_rejoining_device_keeps_its_identity(admin, guest, core):
    """The lock applies when a user is created, not when a known device comes back."""
    g = guest()
    lock_on(admin)
    r = g.post(
        "/api/join",
        json={"accept": True, "version": "1", "fp": {"hash": "ab" * 16}},
        headers=ORIGIN,
    )
    assert r.status_code == 200 and r.json()["user"]["uploads_paused"] is False
    assert can_upload(g)


# ------------------------------------------------------------- stop all


def test_stop_all_blocks_everyone_and_restores_exactly(admin, guest, core):
    free, paused = guest(), guest(fp_n=2)
    set_paused(admin, uid(core, paused), True)
    lock_on(admin)
    locked = guest(fp_n=3)
    assert admin.get("/api/admin/upload-stop").json() == {
        "enabled": False,
        "since": None,
        "by": None,
    }
    assert identify(free)["uploads_stopped"] is False

    res = post(admin, "/api/admin/upload-stop", {"enabled": True})
    assert res["enabled"] is True and res["since"] and res["changed"] is True
    assert post(admin, "/api/admin/upload-stop", {"enabled": True})["changed"] is False
    r = upload(free)
    assert r.status_code == 403 and r.json() == {"error": "uploads_stopped", "message": STOPPED_MSG}
    # a paused guest hears about their own pause: it outlasts the stop
    assert upload(paused).json()["error"] == "uploads_paused"
    assert upload(locked).json()["error"] == "uploads_paused"
    assert identify(free)["uploads_stopped"] is True
    newcomer = guest(fp_n=4)
    assert upload(newcomer).json()["error"] == "uploads_paused"  # the lock is still on, too
    users_before = {u.id: u for u in core.repos.users.list()}
    lock_before = core.repos.app_settings.upload_lock()

    res = post(admin, "/api/admin/upload-stop", {"enabled": False})
    assert res == {"enabled": False, "since": None, "by": res["by"], "changed": True}
    # nothing else changed: per-guest pauses and the lock are exactly as before
    assert {u.id: u for u in core.repos.users.list()} == users_before
    assert core.repos.app_settings.upload_lock() == lock_before
    assert can_upload(free)
    assert not can_upload(paused) and not can_upload(locked) and not can_upload(newcomer)
    assert identify(free)["uploads_stopped"] is False
    actions = [e.action for e in core.repos.audit.list()]
    assert actions.count("uploads.stop") == 1 and actions.count("uploads.resume") == 1


def test_stop_all_while_nobody_is_paused(admin, guest):
    g = guest()
    post(admin, "/api/admin/upload-stop", {"enabled": True})
    assert upload(g).json()["error"] == "uploads_stopped"
    # joining still works during a stop; the new guest is not paused
    n = guest(fp_n=2)
    assert identify(n)["user"]["uploads_paused"] is False
    post(admin, "/api/admin/upload-stop", {"enabled": False})
    assert can_upload(g) and can_upload(n)


def test_controls_validation(admin):
    for path in ("/api/admin/upload-stop", "/api/admin/upload-pause"):
        assert admin.post(path, json={"enabled": "maybe"}, headers=ORIGIN).status_code == 422
        assert admin.post(path, json=[], headers=ORIGIN).status_code == 422


# ----------------------------------------------------------- persistence


def test_switches_persist_across_restarts(settings, extensions, make_client):
    app = create_app(settings, extensions=extensions)
    core = app.state.core
    core.services.upload_controls.set_pause(True, restore=None, actor="pytest")
    core.services.upload_controls.set_stop(True, actor="pytest")
    lock = core.repos.app_settings.upload_lock()
    core.db.close()

    again = create_app(settings, extensions=extensions)
    try:
        assert again.state.core.repos.app_settings.upload_lock() == lock
        assert again.state.core.repos.app_settings.upload_stop().enabled is True
    finally:
        again.state.core.db.close()


# ---------------------------------------------------------------- events


def test_controls_publish_events(admin, guest, make_client, core):
    g = guest()
    user_id = uid(core, g)
    # a new client binds the event bus to its own loop: make it before listening
    newcomer_client = make_client()
    scan(newcomer_client)

    def act():
        post(admin, "/api/admin/upload-stop", {"enabled": True})
        post(admin, "/api/admin/upload-stop", {"enabled": True})  # no change, no event
        post(admin, "/api/admin/upload-stop", {"enabled": False})
        set_paused(admin, user_id, True)
        set_paused(admin, user_id, True)  # no change, no event
        set_paused(admin, user_id, False)
        lock_on(admin)
        accept_consent(newcomer_client, fp_n=2)  # user.created, paused
        lock_off(admin, restore=True)

    events = _collect_events(core, act, 8)
    assert [e["type"] for e in events] == [
        "settings.upload_stop",
        "settings.upload_stop",
        "user.uploads_changed",
        "user.uploads_changed",
        "settings.upload_pause",
        "user.created",
        "settings.upload_pause",
        "user.uploads_changed",
    ]
    data = [e["data"] for e in events]
    assert data[0]["upload_stop"]["enabled"] is True and data[1]["upload_stop"]["enabled"] is False
    assert data[2]["paused"] is True and data[2]["users"][0]["id"] == user_id
    assert data[2]["users"][0]["uploads_paused"] is True
    assert data[3]["paused"] is False and data[3]["users"][0]["uploads_paused"] is False
    assert data[4]["upload_pause"]["enabled"] is True and data[4]["upload_pause"]["period"] == 1
    assert data[5]["uploads_paused"] is True
    newcomer = data[5]["id"]
    assert data[6]["upload_pause"]["enabled"] is False
    assert data[6]["restored"] == [newcomer] and data[6]["kept"] == []
    newcomer_view = core.services.views.user(core.repos.users.get(newcomer))
    assert data[7] == {"users": [newcomer_view.model_dump(mode="json")], "paused": False}


def test_keep_paused_publishes_no_user_change(admin, make_client, core):
    newcomer_client = make_client()
    scan(newcomer_client)

    def act():
        lock_on(admin)
        accept_consent(newcomer_client, fp_n=2)
        lock_off(admin, restore=False)

    events = _collect_events(core, act, 3)
    assert [e["type"] for e in events] == [
        "settings.upload_pause",
        "user.created",
        "settings.upload_pause",
    ]
    assert len(events[2]["data"]["kept"]) == 1 and events[2]["data"]["restored"] == []


@pytest.mark.parametrize("path", ["/api/admin/upload-stop", "/api/admin/upload-pause"])
def test_switches_need_admin_and_same_origin(client, guest, admin, path):
    assert client.get(path).status_code == 401
    assert guest().post(path, json={"enabled": True}, headers=ORIGIN).status_code == 401
    r = admin.post(path, json={"enabled": True}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"
    assert admin.get(path).json()["enabled"] is False
