"""GET /api/me/photos: the guest's own visible photos ("Deine Bilder")."""

from __future__ import annotations

from ..conftest import JPEG, ORIGIN, jpeg, scan

KEYS = {"id", "extension", "seq", "created_at", "width", "height", "url", "thumb_url"}


def upload(client) -> dict:
    r = client.post("/api/x/demo/upload", content=jpeg(400, 300), headers=JPEG)
    assert r.status_code == 201, r.text
    photo: dict = r.json()["photo"]
    return photo


def test_own_visible_photos_newest_first(guest, admin):
    me, other = guest(), guest(fp_n=2)
    first, second, third = upload(me), upload(me), upload(me)
    upload(other)
    admin.post(f"/api/admin/photos/{second['id']}/hide", headers=ORIGIN)
    admin.delete(f"/api/admin/photos/{third['id']}", headers=ORIGIN)
    fourth = upload(me)

    r = me.get("/api/me/photos")
    assert r.status_code == 200
    photos = r.json()["photos"]
    assert [p["id"] for p in photos] == [fourth["id"], first["id"]]
    assert set(photos[0]) == KEYS
    # the same shape as the upload answer
    assert photos[0] == fourth
    assert photos[1]["url"] == f"/media/{first['id']}"
    assert photos[1]["thumb_url"] == f"/media/{first['id']}?thumb=1"
    assert r.headers["cache-control"] == "no-store"
    # and the guest can load them
    assert me.get(photos[0]["thumb_url"]).status_code == 200


def test_only_the_newest_sixty(guest, core):
    core.limits.upload_user = type(core.limits.upload_user)(100, 60)
    me = guest()
    ids = [upload(me)["id"] for _ in range(62)]
    photos = me.get("/api/me/photos").json()["photos"]
    assert len(photos) == 60
    assert [p["id"] for p in photos] == ids[::-1][:60]


def test_empty_for_a_new_guest(guest):
    assert guest().get("/api/me/photos").json() == {"photos": []}


def test_needs_access_consent_and_no_ban(client, guest, core):
    assert client.get("/api/me/photos").json()["error"] == "scan_qr"
    scan(client)
    r = client.get("/api/me/photos")
    assert r.status_code == 401 and r.json()["error"] == "needs_consent"
    g = guest()
    upload(g)
    user = core.repos.users.list()[0]
    core.services.moderation.ban_user(user.id, reason="x", actor="pytest")
    r = g.get("/api/me/photos")
    assert r.status_code == 403
    assert r.json() == {"error": "banned", "message": "Dieses Gerät ist gesperrt."}


def test_paused_guest_still_sees_their_photos(guest, admin, core):
    g = guest()
    photo = upload(g)
    user = core.repos.users.list()[0]
    admin.post(f"/api/admin/users/{user.id}/uploads", json={"paused": True}, headers=ORIGIN)
    assert [p["id"] for p in g.get("/api/me/photos").json()["photos"]] == [photo["id"]]
