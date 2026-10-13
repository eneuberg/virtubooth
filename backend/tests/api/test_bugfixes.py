"""The known bugs from the overhaul analysis (PLAN §3), one test each.
SSE overflow and the missed-events gap are in test_admin_events.py."""

from __future__ import annotations

import asyncio
import threading

import pytest

from virtubooth.domain.constants import AUTO_BAN_REASON
from virtubooth.domain.models import PhotoQuery
from virtubooth.repositories.audit import AuditRepo

from ..conftest import ADMIN_PASSWORD, JPEG, ORIGIN, fp, jpeg, scan


def upload(client) -> str:
    r = client.post("/api/x/demo/upload", content=jpeg(400, 300), headers=JPEG)
    assert r.status_code == 201, r.text
    photo_id: str = r.json()["photo"]["id"]
    return photo_id


def user_id(core, client) -> int:
    public_id = core.signer.unsign("uid", client.cookies.get("vb_uid"))
    return core.repos.users.get_by_public_id(public_id).id


def collect_events(core, action, n):
    received = []
    loop = asyncio.new_event_loop()
    core.bus.bind_loop(loop)
    ready = threading.Event()

    async def listen():
        sub = core.bus.subscribe()
        ready.set()
        while len(received) < n:
            received.append(await asyncio.wait_for(sub.get(), 5))

    t = threading.Thread(target=loop.run_until_complete, args=(listen(),))
    t.start()
    ready.wait(5)
    action()
    t.join(10)
    loop.close()
    return received


# ------------------------------------------- 3. audit atomic with the change


def test_audit_entry_is_written_with_the_change_or_not_at_all(guest, core, monkeypatch):
    """A failing audit write rolls the ban back: no ban without its log entry."""
    g = guest()
    photo = upload(g)
    uid = user_id(core, g)

    def broken(self, *args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(AuditRepo, "log", broken)
    with pytest.raises(RuntimeError):
        core.services.moderation.ban_user(uid, reason="spam", actor="pytest")
    with pytest.raises(RuntimeError):
        core.services.moderation.hide_photo(photo, actor="pytest")
    with pytest.raises(RuntimeError):
        core.services.upload_controls.set_stop(True, actor="pytest")
    monkeypatch.undo()

    user = core.repos.users.get(uid)
    assert not user.banned
    assert not core.repos.photos.get(photo).hidden
    assert not core.repos.app_settings.upload_stop().enabled
    assert [e.action for e in core.repos.audit.list()] == []
    # and it works once the log can be written again
    assert core.services.moderation.ban_user(uid, reason="spam", actor="pytest").changed
    assert [e.action for e in core.repos.audit.list()] == ["user.ban"]


def test_ban_with_fingerprint_is_one_change(guest, core, monkeypatch):
    """Ban, photo hiding, fingerprint ban and both audit entries commit together."""
    g = guest(fp_n=4)
    upload(g)
    uid = user_id(core, g)
    calls = []

    def log_then_fail(self, actor, action, *args, **kwargs):
        calls.append(action)
        if action == "fingerprint.ban":
            raise RuntimeError("boom")

    monkeypatch.setattr(AuditRepo, "log", log_then_fail)
    with pytest.raises(RuntimeError):
        core.services.moderation.ban_user(uid, fingerprint=True, actor="pytest")
    monkeypatch.undo()
    assert calls == ["user.ban", "fingerprint.ban"]
    assert not core.repos.users.get(uid).banned
    assert core.repos.bans.list() == []
    assert not any(p.hidden for p in core.repos.photos.list(PhotoQuery()))


# -------------------------------- 4. files are removed only after the commit


def test_failed_delete_keeps_the_files(guest, core, monkeypatch):
    g = guest()
    pid = upload(g)
    photo = core.repos.photos.get(pid)
    files = [core.repos.photos.path(photo.extension, n) for n in (photo.filename, photo.thumb_filename)]

    def broken(self, *args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(AuditRepo, "log", broken)
    with pytest.raises(RuntimeError):
        core.services.moderation.delete_photo(pid, actor="pytest")
    monkeypatch.undo()
    # the deletion rolled back: row and files are still there
    assert core.repos.photos.get(pid) is not None
    assert all(f.is_file() for f in files)
    assert g.get(f"/media/{pid}").status_code == 200

    assert core.services.moderation.delete_photo(pid, actor="pytest")
    assert not any(f.exists() for f in files)


def test_files_go_after_the_outer_transaction_commits(guest, core):
    g = guest()
    pid = upload(g)
    photo = core.repos.photos.get(pid)
    path = core.repos.photos.path(photo.extension, photo.filename)
    with pytest.raises(RuntimeError), core.db.tx():
        assert core.services.moderation.delete_photo(pid, actor="pytest")
        assert path.is_file()  # not yet: the outer transaction is still open
        raise RuntimeError("rolled back")
    assert path.is_file() and core.repos.photos.get(pid) is not None
    with core.db.tx():
        core.services.moderation.delete_photo(pid, actor="pytest")
        assert path.is_file()
    assert not path.exists()


# ------------------------------- 5. auto_banned on every user reference


def test_user_refs_say_auto_banned_everywhere(admin, guest, make_client, core):
    troll = guest(fp_n=7, instagram="troll")
    upload(troll)
    admin.post(f"/api/admin/users/{user_id(core, troll)}/ban", json={"fingerprint": True}, headers=ORIGIN)
    twin = make_client()
    scan(twin)
    r = twin.post("/api/join", json={"accept": True, "version": "1", "instagram": "twin", "fp": fp(7)}, headers=ORIGIN)
    assert r.json()["state"] == "banned"
    twin_id = user_id(core, twin)
    assert core.repos.users.get(twin_id).ban_reason == AUTO_BAN_REASON
    # a photo the auto-banned guest owns (inserted directly: banned guests can't upload)
    pid = upload(guest(fp_n=9))
    core.db.all("UPDATE photos SET user_id=? WHERE public_id=?", (twin_id, pid))

    photo = admin.get(f"/api/admin/photos/{pid}").json()["photo"]
    assert photo["user"]["auto_banned"] is True and photo["user"]["banned"] is True
    troll_photo = admin.get(f"/api/admin/photos?user_id={user_id(core, troll)}").json()["photos"][0]
    assert troll_photo["user"]["auto_banned"] is False
    handles = {h["handle"]: h for h in admin.get("/api/admin/instagram").json()["handles"]}
    assert handles["twin"]["users"][0]["auto_banned"] is True
    assert handles["troll"]["users"][0]["auto_banned"] is False

    def act():
        r = admin.post(f"/api/admin/users/{twin_id}/uploads", json={"paused": True}, headers=ORIGIN)
        assert r.status_code == 200
        act.user = r.json()["user"]

    (event,) = collect_events(core, act, 1)
    assert event["type"] == "user.uploads_changed"
    sent = event["data"]["users"][0]
    assert sent["auto_banned"] is True
    assert sent["auto_ban"] == {
        "fp_hash": fp(7)["hash"],
        "source_user_id": user_id(core, troll),
        "source_user_name": core.repos.users.get(user_id(core, troll)).name,
    }
    # the answer and the event carry the same user view as GET /users/{id}
    assert act.user == sent == admin.get(f"/api/admin/users/{twin_id}").json()["user"]


def test_user_created_event_carries_a_user_ref(make_client, core):
    c = make_client()
    scan(c)

    def act():
        c.post("/api/join", json={"accept": True, "version": "1", "instagram": "neu", "fp": fp(3)}, headers=ORIGIN)

    (event,) = collect_events(core, act, 1)
    assert event["type"] == "user.created"
    assert set(event["data"]) == {"id", "name", "instagram", "banned", "auto_banned", "uploads_paused"}
    assert event["data"]["instagram"] == "neu" and event["data"]["auto_banned"] is False


# -------------------------------------- 6. no `next` on an exactly full page


def test_full_last_page_has_no_next_cursor(admin, guest):
    g = guest()
    ids = [upload(g) for _ in range(4)]
    page = admin.get("/api/admin/photos?limit=4").json()
    assert [p["id"] for p in page["photos"]] == ids[::-1]
    assert page["next"] is None and page["total"] == 4
    page = admin.get("/api/admin/photos?limit=2").json()
    assert page["next"] == ids[2]
    rest = admin.get(f"/api/admin/photos?limit=2&before={page['next']}").json()
    assert [p["id"] for p in rest["photos"]] == [ids[1], ids[0]] and rest["next"] is None


def test_full_last_page_of_guests_and_audit_has_no_next(admin, guest):
    for n in range(3):
        guest(fp_n=n + 1)
    assert admin.get("/api/admin/users?limit=3").json()["next_offset"] is None
    assert admin.get("/api/admin/users?limit=2").json()["next_offset"] == 2
    assert admin.get("/api/admin/users?limit=2&offset=2").json()["next_offset"] is None
    entries = admin.get("/api/admin/audit").json()["entries"]  # just the login
    assert len(entries) == 1
    assert admin.get("/api/admin/audit?limit=1").json()["next"] is None


# -------------------------------- 7. PATCH /api/me for a banned guest


def test_banned_guest_cannot_edit_the_handle_and_is_told_why(guest, core):
    g = guest(instagram="anna")
    core.services.moderation.ban_user(user_id(core, g), reason="x", actor="pytest")
    r = g.patch("/api/me", json={"instagram": "anna.neu"}, headers=ORIGIN)
    assert r.status_code == 403
    assert r.json() == {"error": "banned", "message": "Dieses Gerät ist gesperrt."}
    assert core.repos.users.get(user_id(core, g)).instagram == "anna"
    # uploads keep their message
    r = g.post("/api/x/demo/upload", content=jpeg(), headers=JPEG)
    assert r.json() == {"error": "banned", "message": "Dieses Gerät wurde für Uploads gesperrt."}


# ----------------------------------------- 8. login_locked has Retry-After


def test_login_locked_says_when_to_retry(make_client, core):
    core.limits.login_failures_global = type(core.limits.login_failures_global)(2, 3600)
    codes = []
    for i in range(3):
        core.limits.login_ip.reset()
        r = make_client().post("/api/admin/login", json={"password": f"wrong-{i}-pw"}, headers=ORIGIN)
        codes.append(r.status_code)
    assert codes == [401, 429, 429]
    assert r.json()["error"] == "login_locked"
    assert int(r.headers["retry-after"]) >= 1
    core.limits.login_ip.reset()
    ok = make_client().post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=ORIGIN)
    assert ok.status_code == 200
