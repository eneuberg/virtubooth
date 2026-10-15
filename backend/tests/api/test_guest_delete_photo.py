"""DELETE /api/me/photos/{id}: a guest deletes one of their own photos (the
admin's delete path, audited as `guest:<id>`)."""

from __future__ import annotations

from ..conftest import JPEG, ORIGIN, jpeg


def upload(client) -> str:
    r = client.post("/api/x/demo/upload", content=jpeg(400, 300), headers=JPEG)
    assert r.status_code == 201, r.text
    photo_id: str = r.json()["photo"]["id"]
    return photo_id


def test_own_photo(guest, admin, core):
    g = guest()
    keep, gone = upload(g), upload(g)
    r = g.delete(f"/api/me/photos/{gone}", headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    assert [p["id"] for p in g.get("/api/me/photos").json()["photos"]] == [keep]
    assert g.get(f"/media/{gone}").status_code == 404
    tombstone = core.repos.photos.get(gone, include_deleted=True)
    assert tombstone is not None and tombstone.deleted
    entry = core.repos.audit.list(limit=1)[0]
    assert (entry.action, entry.target) == ("photo.delete", f"photo:{gone}")
    assert entry.actor == f"guest:{tombstone.user_id}"
    # twice: gone
    assert g.delete(f"/api/me/photos/{gone}", headers=ORIGIN).status_code == 404


def test_not_someone_elses(guest, core):
    me, other = guest(fp_n=1), guest(fp_n=2)
    theirs = upload(other)
    r = me.delete(f"/api/me/photos/{theirs}", headers=ORIGIN)
    assert r.status_code == 404
    assert core.repos.photos.get(theirs) is not None
    assert me.delete("/api/me/photos/AAAAAAAAAAAAAAAA", headers=ORIGIN).status_code == 404
    assert me.delete("/api/me/photos/..%2Fx", headers=ORIGIN).status_code in (404, 422)


def test_a_hidden_photo_too(guest, admin):
    g = guest()
    photo = upload(g)
    admin.post(f"/api/admin/photos/{photo}/hide", headers=ORIGIN)
    assert g.delete(f"/api/me/photos/{photo}", headers=ORIGIN).status_code == 200


def test_needs_origin_and_a_guest(guest, client):
    g = guest()
    photo = upload(g)
    assert g.delete(f"/api/me/photos/{photo}").status_code == 403  # no Origin
    assert client.delete(f"/api/me/photos/{photo}", headers=ORIGIN).status_code in (401, 403, 404)
