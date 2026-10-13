"""Per-guest metrics for the admin: online time on `AdminUser` (list, detail,
events), the user page's `stats`, and the archive's users.csv columns."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from virtubooth.core.clock import iso
from virtubooth.extensions.sdk import Extension, UploadPolicy
from virtubooth.tools.export import USER_COLUMNS, take_snapshot, users_csv

from ..conftest import JPEG, ORIGIN, jpeg
from ..unit.test_tools import read_csv
from .test_admin_dashboard import user_id_of


@pytest.fixture
def extensions(demo_extension):
    second = Extension(
        id="zweite", title="Zweite", emoji="📷", tagline="Noch eine", upload=UploadPolicy()
    )
    return [demo_extension, second]


def upload(client, ext="demo") -> str:
    r = client.post(f"/api/x/{ext}/upload", content=jpeg(400, 400), headers=JPEG)
    assert r.status_code == 201, r.text
    photo_id: str = r.json()["photo"]["id"]
    return photo_id


def here(client, visible=True):
    r = client.post("/api/here", json={"visible": visible}, headers=ORIGIN)
    assert r.status_code == 200, r.text


def detail(admin, user_id) -> dict:
    r = admin.get(f"/api/admin/users/{user_id}")
    assert r.status_code == 200, r.text
    body: dict = r.json()
    return body


def test_admin_user_carries_the_online_time(admin, guest, core):
    g = guest()
    user_id = user_id_of(core, g)
    [listed] = admin.get("/api/admin/users").json()["users"]
    assert (listed["online_seconds"], listed["online_sessions"], listed["online_now"]) == (
        0, 0, False,
    )  # fmt: skip

    start = datetime.now(UTC) - timedelta(seconds=90)
    moment = [start]
    core.services.presence.now = lambda: moment[0]
    here(g)
    moment[0] = start + timedelta(seconds=75)
    here(g)
    [listed] = admin.get("/api/admin/users").json()["users"]
    user = detail(admin, user_id)["user"]
    assert user == listed
    assert (user["online_seconds"], user["online_sessions"], user["online_now"]) == (75, 1, True)


def test_stats_of_a_guest_without_photos(admin, guest, core):
    g = guest()
    stats = detail(admin, user_id_of(core, g))["stats"]
    assert stats == {
        "photos": 0, "visible": 0, "hidden": 0, "deleted": 0, "by_activity": [],
        "first_photo_at": None, "last_photo_at": None,
    }  # fmt: skip


def test_stats_count_photos_per_activity(admin, guest, core):
    g, other = guest(), guest(fp_n=2)
    ids = [upload(g, "demo") for _ in range(2)] + [upload(g, "zweite") for _ in range(4)]
    upload(other, "demo")  # someone else's
    hidden, deleted = ids[2], ids[3]  # both in "zweite"
    assert admin.post(f"/api/admin/photos/{hidden}/hide", headers=ORIGIN).status_code == 200
    assert admin.delete(f"/api/admin/photos/{deleted}", headers=ORIGIN).status_code == 200
    base = datetime(2026, 10, 13, 20, 0, tzinfo=UTC)
    with core.db.tx() as c:
        for n, photo_id in enumerate(ids):
            c.execute(
                "UPDATE photos SET created_at=? WHERE public_id=?",
                (iso(base + timedelta(minutes=n)), photo_id),
            )

    stats = detail(admin, user_id_of(core, g))["stats"]
    assert (stats["photos"], stats["visible"], stats["hidden"], stats["deleted"]) == (5, 4, 1, 1)
    assert stats["by_activity"] == [{"id": "zweite", "photos": 3}, {"id": "demo", "photos": 2}]
    assert stats["first_photo_at"] == iso(base)
    # the last upload counts even though it was deleted later
    assert stats["last_photo_at"] == iso(base + timedelta(minutes=5))
    assert detail(admin, user_id_of(core, other))["stats"]["photos"] == 1


def test_users_csv_has_the_online_time(guest, core, tmp_path):
    g = guest()
    with core.db.tx() as c:
        c.execute(
            "UPDATE users SET online_seconds=4321, online_sessions=3 WHERE id=?",
            (user_id_of(core, g),),
        )
    assert USER_COLUMNS[-2:] == ["online_seconds", "online_sessions"]
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    snap = take_snapshot(core.settings.data_dir, scratch, include_hidden=True)
    [row] = read_csv(users_csv(snap.users))
    assert list(row) == USER_COLUMNS
    assert (row["online_seconds"], row["online_sessions"]) == ("4321", "3")
