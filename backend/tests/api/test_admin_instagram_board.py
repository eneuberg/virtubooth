"""The Instagram board: the „Erledigt“ mark per handle and the ZIP of the
photos to post (`/api/admin/instagram/{handle}/...`)."""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

import pytest

from virtubooth.api.schemas.events import AdminEvent

from ..conftest import JPEG, ORIGIN, jpeg

CURSOR_RE = re.compile(r"^[0-9a-f]{8}-\d+$")


def upload(client, color=(200, 120, 40)) -> str:
    r = client.post("/api/x/demo/upload", content=jpeg(color=color), headers=JPEG)
    assert r.status_code == 201, r.text
    photo_id: str = r.json()["photo"]["id"]
    return photo_id


def user_id(core, client) -> int:
    public_id = core.signer.unsign("uid", client.cookies.get("vb_uid"))
    return core.repos.users.get_by_public_id(public_id).id


def handles(admin) -> dict[str, dict[str, Any]]:
    r = admin.get("/api/admin/instagram")
    assert r.status_code == 200, r.text
    return {h["handle"]: h for h in r.json()["handles"]}


def mark(admin, handle: str, done: Any):
    return admin.post(f"/api/admin/instagram/{handle}/done", json={"done": done}, headers=ORIGIN)


@pytest.fixture
def published(core, monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []
    real = core.bus.publish

    def spy(type_: str, data: dict[str, Any]) -> None:
        seen.append((type_, data))
        real(type_, data)

    monkeypatch.setattr(core.bus, "publish", spy)
    return seen


# -------------------------------------------------------------------- done


def test_done_mark_round_trip(admin, guest, published):
    upload(guest(instagram="@Anna.Party"))
    guest(instagram="ben", fp_n=2)
    assert {h: v["done"] for h, v in handles(admin).items()} == {"anna.party": False, "ben": False}

    # normalized like the guests' input: case, "@"
    r = mark(admin, "@ANNA.Party", True)
    assert r.status_code == 200, r.text
    assert r.json() == {"handle": "anna.party", "done": True, "changed": True}
    assert CURSOR_RE.match(r.headers["x-vb-event-id"])
    assert {h: v["done"] for h, v in handles(admin).items()} == {"anna.party": True, "ben": False}
    assert mark(admin, "anna.party", True).json()["changed"] is False  # idempotent
    r = mark(admin, "%40Anna.party", False)
    assert r.json() == {"handle": "anna.party", "done": False, "changed": True}
    assert not handles(admin)["anna.party"]["done"]

    ours = [(t, d) for t, d in published if t == "instagram.done"]
    assert ours == [
        ("instagram.done", {"handle": "anna.party", "done": True}),
        ("instagram.done", {"handle": "anna.party", "done": False}),
    ]
    for i, (type_, data) in enumerate(ours):
        AdminEvent.model_validate({"type": type_, "id": f"0badcafe-{i}", "data": data})

    entries = admin.get("/api/admin/audit").json()["entries"]
    actions = [(e["action"], e["target"]) for e in entries if e["action"].startswith("instagram")]
    assert actions == [
        ("instagram.undone", "instagram:anna.party"),
        ("instagram.done", "instagram:anna.party"),
    ]
    assert all(e["actor"].startswith("admin:") for e in entries)


def test_done_mark_survives_a_restart(admin, guest, core, extensions):
    from virtubooth.app import create_app

    guest(instagram="anna")
    assert mark(admin, "anna", True).status_code == 200
    again = create_app(core.settings, extensions=extensions)
    try:
        assert again.state.core.services.instagram.done_handles() == {"anna"}
    finally:
        again.state.core.db.close()


def test_done_mark_errors(admin, guest):
    guest(instagram="anna")
    r = mark(admin, "nobody", True)
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    r = mark(admin, "%C3%A4nna", True)  # "änna"
    assert r.status_code == 400 and r.json()["error"] == "invalid_instagram"
    assert "Umlaute" in r.json()["message"]
    assert mark(admin, "%40", True).json()["error"] == "invalid_instagram"  # only "@"
    for body in ({}, {"done": "maybe"}, None):
        r = admin.post("/api/admin/instagram/anna/done", json=body, headers=ORIGIN)
        assert r.status_code == 422, body
    assert not handles(admin)["anna"]["done"]


# --------------------------------------------------------------------- zip


def test_photos_zip_has_the_visible_photos_of_unbanned_guests(admin, guest, core):
    anna = guest(instagram="anna")
    anna_phone2 = guest(instagram="@Anna", fp_n=2)  # same person, second phone
    troll = guest(instagram="anna", fp_n=3)  # same handle, banned later
    other = guest(instagram="ben", fp_n=4)
    a1 = upload(anna, (255, 0, 0))
    hidden = upload(anna, (0, 255, 0))
    upload(other, (0, 0, 255))
    t1 = upload(troll, (9, 9, 9))
    a2 = upload(anna_phone2, (255, 255, 0))
    core.services.moderation.hide_photo(hidden, actor="pytest")
    core.services.moderation.ban_user(user_id(core, troll), actor="pytest")
    # the admin put the banned guest's photo back up: still not to be posted
    core.services.moderation.unhide_photo(t1, actor="pytest")
    deleted = upload(anna, (1, 2, 3))
    core.services.moderation.delete_photo(deleted, actor="pytest")

    r = admin.get("/api/admin/instagram/ANNA/photos.zip")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="fotos-anna.zip"'
    assert r.headers["cache-control"] == "no-store"
    assert CURSOR_RE.match(r.headers["x-vb-event-id"])
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.testzip() is None
        names = zf.namelist()
        assert names == [f"0001-demo-{a1}.jpg", f"0002-demo-{a2}.jpg"]  # upload order
        for name, pid in zip(names, (a1, a2), strict=True):
            photo = core.repos.photos.get(pid)
            assert zf.read(name) == core.repos.photos.path("demo", photo.filename).read_bytes()


def test_photos_zip_skips_a_file_deleted_meanwhile(admin, guest, core):
    g = guest(instagram="anna")
    keep, gone = upload(g), upload(g)
    photo = core.repos.photos.get(gone)
    core.repos.photos.path("demo", photo.filename).unlink()
    with zipfile.ZipFile(
        io.BytesIO(admin.get("/api/admin/instagram/anna/photos.zip").content)
    ) as zf:
        assert zf.namelist() == [f"0001-demo-{keep}.jpg"]


def test_photos_zip_404_without_visible_photos(admin, guest, core):
    g = guest(instagram="anna")
    guest(instagram="nophotos", fp_n=2)
    core.services.moderation.hide_photo(upload(g), actor="pytest")
    for handle in ("anna", "nophotos", "nobody"):
        r = admin.get(f"/api/admin/instagram/{handle}/photos.zip")
        assert r.status_code == 404 and r.json()["error"] == "not_found", handle
        assert r.json()["message"] == "Für diesen Instagram-Namen gibt es keine sichtbaren Fotos."
    r = admin.get("/api/admin/instagram/no%20spaces/photos.zip")
    assert r.status_code == 400 and r.json()["error"] == "invalid_instagram"
