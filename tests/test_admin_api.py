"""Admin API: auth on every route, CSRF, photos, bulk, users, bans, overview data."""

from __future__ import annotations

import asyncio
import threading

import pytest

from virtubooth.admin.api import router as admin_router
from virtubooth.repo import PhotoQuery

from .conftest import JPEG, ORIGIN, fp, jpeg, scan

PHOTO = "AAAAAAAAAAAAAAAA"
FP = "ab" * 32

# every route of the admin router, with a request that would pass validation
ROUTES = [
    ("GET", "/api/admin/photos", None),
    ("GET", f"/api/admin/photos/{PHOTO}", None),
    ("POST", f"/api/admin/photos/{PHOTO}/hide", None),
    ("POST", f"/api/admin/photos/{PHOTO}/unhide", None),
    ("DELETE", f"/api/admin/photos/{PHOTO}", None),
    ("POST", "/api/admin/photos/bulk", {"ids": [PHOTO], "action": "hide"}),
    ("GET", "/api/admin/users", None),
    ("GET", "/api/admin/users/1", None),
    ("POST", "/api/admin/users/1/ban", {"reason": "x", "fingerprint": True}),
    ("POST", "/api/admin/users/1/unban", None),
    ("GET", "/api/admin/device-bans", None),
    ("DELETE", f"/api/admin/device-bans/{FP}", None),
    ("GET", "/api/admin/stats", None),
    ("GET", "/api/admin/instagram", None),
    ("GET", "/api/admin/audit", None),
    ("GET", "/api/admin/extensions", None),
    ("GET", "/api/admin/events", None),
    ("GET", "/api/admin/upload-stop", None),
    ("POST", "/api/admin/upload-stop", {"enabled": True}),
    ("GET", "/api/admin/upload-pause", None),
    ("POST", "/api/admin/upload-pause", {"enabled": False, "restore": True}),
    ("POST", "/api/admin/users/1/uploads", {"paused": True}),
]


def upload(client, ext="demo"):
    r = client.post(f"/api/x/{ext}/upload", content=jpeg(), headers=JPEG)
    assert r.status_code == 201, r.text
    return r.json()["photo"]["id"]


def user_of(core, client):
    """The users row behind a guest client (via its signed uid cookie)."""
    public_id = core.signer.unsign("uid", client.cookies.get("vb_uid"))
    user = core.repo.get_user_by_public_id(public_id)
    assert user is not None
    return core.repo.get_user(user.id)


def req(client, method, path, json=None, headers=ORIGIN):
    return client.request(method, path, json=json, headers=headers)


# ------------------------------------------------------------------ access


def _flat_routes(routes, prefix=""):
    """(path, methods), also of routers included into the admin router."""
    for route in routes:
        if hasattr(route, "original_router"):
            yield from _flat_routes(route.original_router.routes, route.include_context.prefix)
        else:
            yield prefix + route.path, route.methods


def test_route_table_is_covered():
    covered = {(m, p) for m, p, _ in ROUTES}
    for path, methods in _flat_routes(admin_router.routes):
        for method in methods:
            sample = {
                (m, p) for m, p in covered
                if m == method and _same_shape(path, p)
            }  # fmt: skip
            assert sample, f"{method} {path} missing from ROUTES"


def _same_shape(template: str, path: str) -> bool:
    a, b = template.split("/"), path.split("/")
    return len(a) == len(b) and all(x == y or x.startswith("{") for x, y in zip(a, b, strict=True))


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=[f"{m} {p}" for m, p, _ in ROUTES])
def test_every_route_needs_admin(client, guest, method, path, body):
    r = req(client, method, path, body)
    assert r.status_code == 401, r.text
    assert r.json()["error"] == "admin_required"
    # a party guest is no admin either
    g = guest()
    r = req(g, method, path, body)
    assert r.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [r for r in ROUTES if r[0] != "GET"],
    ids=[f"{m} {p}" for m, p, _ in ROUTES if m != "GET"],
)
def test_mutations_need_same_origin(admin, method, path, body):
    r = req(admin, method, path, body, headers={})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"
    r = req(admin, method, path, body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_logout_revokes_api_access(admin):
    assert admin.get("/api/admin/stats").status_code == 200
    admin.post("/api/admin/logout", headers=ORIGIN)
    assert admin.get("/api/admin/stats").status_code == 401


def test_invalid_ids_rejected(admin):
    for bad in ("short", "x" * 40, "bad%20id!!!!!!!", "..%2F..%2Fetc"):
        assert admin.get(f"/api/admin/photos/{bad}").status_code in (404, 422)
    assert admin.post("/api/admin/photos/a.b.c.d.e.f/hide", headers=ORIGIN).status_code == 422
    assert admin.get("/api/admin/users/abc").status_code == 422
    assert admin.get("/api/admin/users/0").status_code == 422
    assert admin.get("/api/admin/users/-1").status_code == 422
    assert admin.delete("/api/admin/device-bans/NOTHEX", headers=ORIGIN).status_code == 422
    assert admin.get("/api/admin/photos?user_id=abc").status_code == 400
    assert admin.get("/api/admin/photos?extension=../x").status_code == 400
    assert admin.get("/api/admin/photos?hidden=maybe").status_code == 400
    assert admin.get("/api/admin/photos?before=nope").status_code == 400
    assert admin.get(f"/api/admin/photos?before={PHOTO}").json()["error"] == "invalid_cursor"
    assert admin.get("/api/admin/photos?limit=0").status_code == 422
    assert admin.get("/api/admin/photos?limit=201").status_code == 422


def test_unknown_things_404(admin):
    assert admin.get(f"/api/admin/photos/{PHOTO}").status_code == 404
    assert admin.post(f"/api/admin/photos/{PHOTO}/hide", headers=ORIGIN).status_code == 404
    assert admin.post(f"/api/admin/photos/{PHOTO}/unhide", headers=ORIGIN).status_code == 404
    assert admin.delete(f"/api/admin/photos/{PHOTO}", headers=ORIGIN).status_code == 404
    assert admin.get("/api/admin/users/999").status_code == 404
    assert admin.post("/api/admin/users/999/ban", json={}, headers=ORIGIN).status_code == 404
    assert admin.post("/api/admin/users/999/unban", headers=ORIGIN).status_code == 404
    assert admin.delete(f"/api/admin/device-bans/{FP}", headers=ORIGIN).status_code == 404


# ------------------------------------------------------------------ photos


def test_list_photos_newest_first_with_user(admin, guest):
    g = guest(instagram="@party.anna")
    ids = [upload(g) for _ in range(3)]
    body = admin.get("/api/admin/photos").json()
    assert [p["id"] for p in body["photos"]] == ids[::-1]
    assert body["total"] == 3 and body["next"] is None
    first = body["photos"][0]
    assert first["extension"] == "demo" and first["seq"] == 3
    assert first["thumb_url"] == f"/media/{ids[2]}?thumb=1"
    assert first["user"]["instagram"] == "party.anna"
    assert first["user"]["name"] and first["hidden"] is False
    assert admin.get(f"/api/admin/photos/{ids[0]}").json()["photo"]["seq"] == 1


def test_list_photos_pagination_and_polling(admin, guest):
    g = guest()
    ids = [upload(g) for _ in range(5)]
    page1 = admin.get("/api/admin/photos?limit=2").json()
    assert [p["id"] for p in page1["photos"]] == [ids[4], ids[3]]
    assert page1["next"] == ids[3] and page1["total"] == 5
    page2 = admin.get(f"/api/admin/photos?limit=2&before={page1['next']}").json()
    assert [p["id"] for p in page2["photos"]] == [ids[2], ids[1]]
    assert "total" not in page2
    page3 = admin.get(f"/api/admin/photos?limit=2&before={page2['next']}").json()
    assert [p["id"] for p in page3["photos"]] == [ids[0]] and page3["next"] is None
    # polling: what is newer than the newest one I know
    newer = admin.get(f"/api/admin/photos?after={ids[2]}").json()
    assert [p["id"] for p in newer["photos"]] == [ids[4], ids[3]]
    assert admin.get(f"/api/admin/photos?after={ids[4]}").json()["photos"] == []


def test_list_photos_filters(admin, guest, core):
    a, b = guest(), guest(fp_n=2)
    a1, a2 = upload(a), upload(a)
    b1 = upload(b)
    core.repo.hide_photo(a2, "pytest")
    uid_a = user_of(core, a).id

    def ids(query):
        r = admin.get(f"/api/admin/photos{query}")
        assert r.status_code == 200, r.text
        return [p["id"] for p in r.json()["photos"]]

    assert ids("?hidden=true") == [a2]
    assert ids("?hidden=hidden") == [a2]
    assert ids("?hidden=false") == [b1, a1]
    assert ids("?hidden=visible") == [b1, a1]
    assert ids("?hidden=all") == [b1, a2, a1]
    assert ids("?hidden=") == [b1, a2, a1]
    assert ids(f"?user_id={uid_a}") == [a2, a1]
    assert ids(f"?user_id={uid_a}&hidden=false") == [a1]
    assert ids("?extension=demo") == [b1, a2, a1]
    assert ids("?extension=beer") == []
    assert ids("?extension=&user_id=") == [b1, a2, a1]
    total = admin.get(f"/api/admin/photos?user_id={uid_a}&hidden=true").json()["total"]
    assert total == 1


def test_hide_unhide_photo(admin, guest, core):
    g = guest()
    pid = upload(g)
    r = admin.post(f"/api/admin/photos/{pid}/hide", headers=ORIGIN)
    assert r.status_code == 200
    assert r.json()["changed"] is True and r.json()["photo"]["hidden"] is True
    assert r.json()["photo"]["hidden_reason"] == "admin"
    assert core.repo.get_photo(pid).hidden
    # idempotent
    r = admin.post(f"/api/admin/photos/{pid}/hide", headers=ORIGIN)
    assert r.status_code == 200 and r.json()["changed"] is False
    r = admin.post(f"/api/admin/photos/{pid}/unhide", headers=ORIGIN)
    assert r.json()["changed"] is True and r.json()["photo"]["hidden"] is False
    assert not core.repo.get_photo(pid).hidden
    assert admin.post(f"/api/admin/photos/{pid}/unhide", headers=ORIGIN).json()["changed"] is False
    actions = [e["action"] for e in core.repo.list_audit()]
    assert actions.count("photo.hide") == 1 and actions.count("photo.unhide") == 1
    actors = {e["actor"] for e in core.repo.list_audit() if e["action"].startswith("photo.")}
    assert len(actors) == 1 and actors.pop().startswith("admin:")


def test_hidden_photo_still_served_to_admin_and_owner(admin, guest):
    g = guest()
    pid = upload(g)
    admin.post(f"/api/admin/photos/{pid}/hide", headers=ORIGIN)
    assert admin.get(f"/media/{pid}?thumb=1").status_code == 200
    assert admin.get(f"/media/{pid}?download=1").status_code == 200


def test_delete_photo_removes_files(admin, guest, core, settings):
    g = guest()
    pid = upload(g)
    keep = upload(g)
    photo = core.repo.get_photo(pid)
    files = [
        core.repo.photo_path(photo.extension, photo.filename),
        core.repo.photo_path(photo.extension, photo.thumb_filename),
    ]
    assert all(f.is_file() for f in files)
    r = admin.delete(f"/api/admin/photos/{pid}", headers=ORIGIN)
    assert r.status_code == 200 and r.json() == {"ok": True, "id": pid}
    assert not any(f.exists() for f in files)
    assert admin.get(f"/media/{pid}").status_code == 404
    assert admin.get(f"/api/admin/photos/{pid}").status_code == 404
    assert [p["id"] for p in admin.get("/api/admin/photos").json()["photos"]] == [keep]
    assert admin.delete(f"/api/admin/photos/{pid}", headers=ORIGIN).status_code == 404
    assert "photo.delete" in {e["action"] for e in core.repo.list_audit()}
    # the sequence number is never reused
    assert core.repo.get_photo(upload(g)).seq == 3


def test_bulk_actions(admin, guest, core, settings):
    g = guest()
    ids = [upload(g) for _ in range(4)]
    r = admin.post(
        "/api/admin/photos/bulk",
        json={"ids": [ids[0], ids[1], ids[1], PHOTO], "action": "hide"},
        headers=ORIGIN,
    )
    assert r.status_code == 200
    assert r.json() == {
        "action": "hide",
        "changed": [ids[0], ids[1]],
        "unchanged": [],
        "missing": [PHOTO],
    }
    assert core.repo.get_photo(ids[0]).hidden and core.repo.get_photo(ids[1]).hidden
    r = admin.post(
        "/api/admin/photos/bulk", json={"ids": ids[:3], "action": "unhide"}, headers=ORIGIN
    ).json()
    assert r["changed"] == ids[:2] and r["unchanged"] == [ids[2]]
    assert not any(core.repo.get_photo(i).hidden for i in ids)
    r = admin.post(
        "/api/admin/photos/bulk", json={"ids": ids[:3], "action": "delete"}, headers=ORIGIN
    ).json()
    assert r["changed"] == ids[:3]
    assert [p.public_id for p in core.repo.list_photos(PhotoQuery())] == [ids[3]]
    assert len(list((settings.data_dir / "demo").glob("*.jpg"))) == 1


def test_bulk_validation(admin):
    def bulk(body):
        return admin.post("/api/admin/photos/bulk", json=body, headers=ORIGIN).status_code

    assert bulk({"ids": [], "action": "hide"}) == 422
    assert bulk({"ids": [PHOTO] * 201, "action": "hide"}) == 422
    assert bulk({"ids": [PHOTO] * 200, "action": "hide"}) == 200
    assert bulk({"ids": [PHOTO], "action": "explode"}) == 422
    assert bulk({"ids": ["../../etc/passwd"], "action": "delete"}) == 422
    assert bulk({"ids": PHOTO, "action": "hide"}) == 422


# ------------------------------------------------------------------- users


def test_users_list_search_and_detail(admin, guest, core):
    a = guest(instagram="anna.party")
    guest(fp_n=2)
    upload(a)
    upload(a)
    body = admin.get("/api/admin/users").json()
    assert len(body["users"]) == 2 and body["next_offset"] is None
    anna = next(u for u in body["users"] if u["instagram"] == "anna.party")
    assert anna["photo_count"] == 2
    assert [u["id"] for u in admin.get("/api/admin/users?search=anna").json()["users"]] == [
        anna["id"]
    ]
    assert (
        admin.get(f"/api/admin/users?search=%23{anna['id']}").json()["users"][0]["id"] == anna["id"]
    )
    assert admin.get("/api/admin/users?banned=true").json()["users"] == []
    assert len(admin.get("/api/admin/users?banned=false").json()["users"]) == 2
    page = admin.get("/api/admin/users?limit=1").json()
    assert len(page["users"]) == 1 and page["next_offset"] == 1
    assert len(admin.get("/api/admin/users?limit=1&offset=1").json()["users"]) == 1

    detail = admin.get(f"/api/admin/users/{anna['id']}").json()
    assert detail["user"]["instagram"] == "anna.party"
    assert detail["user"]["fp_components"]["screen"] == "390x844@3"
    assert detail["user"]["consent_at"]
    assert len(detail["photos"]) == 2
    assert detail["fingerprints"][0]["fp_hash"] == fp(1)["hash"]
    assert detail["fingerprints"][0]["current"] is True
    assert detail["fingerprints"][0]["users"] == [] and detail["sharing"] == []


def test_user_detail_shows_devices_sharing_fingerprint(admin, guest, core):
    a = guest(fp_n=5)
    b = guest(fp_n=5, instagram="twin")
    guest(fp_n=6)
    ua, ub = user_of(core, a), user_of(core, b)
    detail = admin.get(f"/api/admin/users/{ua.id}").json()
    assert detail["fingerprints"][0]["shared_with"] == 1
    assert detail["fingerprints"][0]["users"] == [
        {"id": ub.id, "name": ub.name, "instagram": "twin", "banned": False}
    ]
    assert [u["id"] for u in detail["sharing"]] == [ub.id]


def test_ban_hides_photos_blocks_uploads_and_unban_restores(admin, guest, core):
    g = guest()
    other = guest(fp_n=2)
    p1, p2 = upload(g), upload(g)
    p_other = upload(other)
    admin.post(f"/api/admin/photos/{p1}/hide", headers=ORIGIN)  # hidden before the ban
    user = user_of(core, g)

    r = admin.post(
        f"/api/admin/users/{user.id}/ban", json={"reason": "  Spam\n  Fotos "}, headers=ORIGIN
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"] is True and body["fingerprint_banned"] is False
    assert body["user"]["banned"] is True and body["user"]["ban_reason"] == "Spam Fotos"
    assert {p["id"]: p["hidden"] for p in body["photos"]} == {p1: True, p2: True}
    assert core.repo.get_photo(p2).hidden_reason == "ban"
    assert not core.repo.get_photo(p_other).hidden
    r = g.post("/api/x/demo/upload", content=jpeg(), headers=JPEG)
    assert r.status_code == 403 and r.json()["error"] == "banned"
    assert core.repo.list_fingerprint_bans() == []
    # banning twice is harmless
    again = admin.post(f"/api/admin/users/{user.id}/ban", json={"reason": "x"}, headers=ORIGIN)
    assert again.json()["changed"] is False

    r = admin.post(f"/api/admin/users/{user.id}/unban", headers=ORIGIN)
    assert r.status_code == 200 and r.json()["changed"] is True
    assert r.json()["user"]["banned"] is False
    assert core.repo.get_photo(p1).hidden  # the admin hid this one, it stays hidden
    assert not core.repo.get_photo(p2).hidden
    assert g.post("/api/x/demo/upload", content=jpeg(), headers=JPEG).status_code == 201
    assert (
        admin.post(f"/api/admin/users/{user.id}/unban", headers=ORIGIN).json()["changed"] is False
    )
    actions = [e["action"] for e in core.repo.list_audit()]
    assert {"user.ban", "user.unban"} <= set(actions)


def test_fingerprint_ban_catches_new_guest_with_same_fp(admin, guest, make_client, core):
    g = guest(fp_n=7)
    user = user_of(core, g)
    r = admin.post(
        f"/api/admin/users/{user.id}/ban",
        json={"reason": "Ärger", "fingerprint": True},
        headers=ORIGIN,
    )
    assert r.json()["fingerprint_banned"] is True
    bans = admin.get("/api/admin/device-bans").json()["bans"]
    assert len(bans) == 1
    assert bans[0]["fp_hash"] == fp(7)["hash"] and bans[0]["reason"] == "Ärger"
    assert bans[0]["source_user_id"] == user.id and bans[0]["source_user_name"] == user.name
    assert [u["id"] for u in bans[0]["users"]] == [user.id]

    # same device, cookies cleared: a new identity starts banned
    evader = make_client()
    scan(evader)
    r = evader.post(
        "/api/join",
        json={"accept": True, "version": "1", "fp": fp(7)},
        headers=ORIGIN,
    )
    assert r.json()["state"] == "banned"
    assert evader.post("/api/x/demo/upload", content=jpeg(), headers=JPEG).status_code == 403
    # a different device is fine
    assert upload(guest(fp_n=8))

    detail = admin.get(f"/api/admin/users/{user.id}").json()
    assert detail["fingerprints"][0]["banned"] is True
    assert len(detail["fingerprints"][0]["users"]) == 1  # the evader

    r = admin.delete(f"/api/admin/device-bans/{fp(7)['hash']}", headers=ORIGIN)
    assert r.status_code == 200
    assert admin.get("/api/admin/device-bans").json()["bans"] == []
    newcomer = make_client()
    scan(newcomer)
    r = newcomer.post(
        "/api/join", json={"accept": True, "version": "1", "fp": fp(7)}, headers=ORIGIN
    )
    assert r.json()["state"] == "ok"
    actions = {e["action"] for e in core.repo.list_audit()}
    assert {"fingerprint.ban", "fingerprint.unban"} <= actions


def test_fingerprint_ban_needs_a_fingerprint(admin, make_client, core):
    # consent requires a fingerprint now; older rows may still lack one
    user = core.repo.create_user(
        consent_version="1", instagram=None, fp_hash=None, fp_components={},
        ip="1.2.3.4", user_agent="legacy",
    )
    r = admin.post(f"/api/admin/users/{user.id}/ban", json={"fingerprint": True}, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["error"] == "no_fingerprint"
    assert not core.repo.get_user(user.id).banned  # nothing half-done


def test_unban_can_lift_fingerprint_bans_too(admin, guest, core):
    g = guest(fp_n=9)
    user = user_of(core, g)
    admin.post(f"/api/admin/users/{user.id}/ban", json={"fingerprint": True}, headers=ORIGIN)
    r = admin.post(f"/api/admin/users/{user.id}/unban", json={"fingerprint": True}, headers=ORIGIN)
    assert r.json()["fingerprints_unbanned"] == [fp(9)["hash"]]
    assert core.repo.list_fingerprint_bans() == []


def test_ban_reason_length_limit(admin, guest, core):
    user = user_of(core, guest())
    r = admin.post(f"/api/admin/users/{user.id}/ban", json={"reason": "x" * 201}, headers=ORIGIN)
    assert r.status_code == 422
    assert not core.repo.get_user(user.id).banned


# ------------------------------------------------------------- overview


def test_stats(admin, guest, core):
    a = guest(instagram="a.a")
    b = guest(fp_n=2)
    guest(fp_n=3)
    pa, _ = upload(a), upload(a)
    pb = upload(b)
    admin.post(f"/api/admin/photos/{pa}/hide", headers=ORIGIN)
    admin.delete(f"/api/admin/photos/{pb}", headers=ORIGIN)
    admin.post(
        f"/api/admin/users/{user_of(core, b).id}/ban", json={"fingerprint": True}, headers=ORIGIN
    )
    s = admin.get("/api/admin/stats").json()
    assert s["photos"] == 2 and s["visible"] == 1 and s["hidden"] == 1 and s["deleted"] == 1
    assert s["guests"] == 3 and s["banned"] == 1 and s["instagram"] == 1
    assert s["uploaders"] == 1 and s["fingerprint_bans"] == 1
    assert s["extensions"] == {"demo": {"photos": 2, "hidden": 1}}
    assert s["last_upload_at"]


def test_stats_empty(admin):
    s = admin.get("/api/admin/stats").json()
    assert s["photos"] == 0 and s["hidden"] == 0 and s["guests"] == 0 and s["extensions"] == {}


def test_instagram_handles(admin, guest, core):
    anna1 = guest(instagram="@anna")
    anna2 = guest(instagram="anna", fp_n=2)  # same person, second phone
    ben = guest(instagram="ben", fp_n=3)
    guest(fp_n=4)  # no handle
    a1, a2 = upload(anna1), upload(anna2)
    upload(anna2)
    admin.post(f"/api/admin/photos/{a1}/hide", headers=ORIGIN)
    body = admin.get("/api/admin/instagram").json()
    handles = body["handles"]
    assert [h["handle"] for h in handles] == ["anna", "ben"]
    anna = handles[0]
    assert anna["photos"] == 3 and anna["visible"] == 2 and anna["hidden"] == 1
    assert {u["id"] for u in anna["users"]} == {user_of(core, anna1).id, user_of(core, anna2).id}
    assert anna["last_upload_at"]
    # quick access: only visible photos, newest first
    assert a1 not in [p["id"] for p in anna["recent"]]
    assert anna["recent"][-1]["id"] == a2 and len(anna["recent"]) == 2
    assert handles[1]["photos"] == 0 and handles[1]["recent"] == []
    assert ben  # used


def test_audit_log_paged(admin, guest, core):
    g = guest()
    pid = upload(g)
    for _ in range(3):
        admin.post(f"/api/admin/photos/{pid}/hide", headers=ORIGIN)
        admin.post(f"/api/admin/photos/{pid}/unhide", headers=ORIGIN)
    body = admin.get("/api/admin/audit?limit=4").json()
    assert [e["action"] for e in body["entries"]] == ["photo.unhide", "photo.hide"] * 2
    assert body["entries"][0]["target"] == f"photo:{pid}"
    assert body["entries"][0]["actor"].startswith("admin:")
    rest = admin.get(f"/api/admin/audit?before={body['next']}").json()
    assert rest["next"] is None
    assert rest["entries"][-1]["action"] == "admin.login"
    assert all(e["id"] < body["next"] for e in rest["entries"])


def test_extensions(admin, guest, core):
    g = guest()
    upload(g)
    # a photo from an extension that is no longer loaded
    core.db.all("UPDATE photos SET extension='oldext'")
    exts = {e["id"]: e for e in admin.get("/api/admin/extensions").json()["extensions"]}
    assert exts["demo"]["emoji"] == "🧪" and exts["demo"]["loaded"] is True
    assert exts["demo"]["meta_labels"] == {}
    assert exts["oldext"]["loaded"] is False


# ------------------------------------------------------------------ events


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


def test_mutations_publish_events(admin, guest, core):
    g = guest()
    pid = upload(g)
    user = user_of(core, g)

    def act():
        admin.post(f"/api/admin/photos/{pid}/hide", headers=ORIGIN)
        admin.post(f"/api/admin/photos/{pid}/hide", headers=ORIGIN)  # no change, no event
        admin.post(f"/api/admin/photos/{pid}/unhide", headers=ORIGIN)
        admin.post(f"/api/admin/users/{user.id}/ban", json={"fingerprint": True}, headers=ORIGIN)
        admin.post(f"/api/admin/users/{user.id}/unban", headers=ORIGIN)
        admin.delete(f"/api/admin/device-bans/{fp(1)['hash']}", headers=ORIGIN)
        admin.delete(f"/api/admin/photos/{pid}", headers=ORIGIN)

    events = _collect_events(core, act, 7)
    assert [e["type"] for e in events] == [
        "photo.hidden",
        "photo.unhidden",
        "fingerprint.banned",
        "user.banned",
        "user.unbanned",
        "fingerprint.unbanned",
        "photo.deleted",
    ]
    assert events[0]["data"]["photo"]["id"] == pid and events[0]["data"]["photo"]["hidden"]
    banned = events[3]["data"]
    assert banned["user"]["id"] == user.id and banned["user"]["banned"]
    assert banned["photos"][0]["hidden_reason"] == "ban"
    assert events[6]["data"]["id"] == pid and events[6]["data"]["photo"]["deleted"]


def test_bulk_publishes_one_event_per_photo(admin, guest, core):
    g = guest()
    ids = [upload(g) for _ in range(3)]

    def act():
        admin.post("/api/admin/photos/bulk", json={"ids": ids, "action": "delete"}, headers=ORIGIN)

    events = _collect_events(core, act, 3)
    assert [e["type"] for e in events] == ["photo.deleted"] * 3
    assert [e["data"]["id"] for e in events] == ids
