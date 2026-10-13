"""The wall's feed and media (PLAN-WALL D5, §4.2): what is visible, the delay,
sources, Instagram, the photo shape, and `s`/`m`/`l` files."""

from __future__ import annotations

import io
import re

import pytest
from PIL import Image

from virtubooth.extensions.sdk import Extension, UploadPolicy
from virtubooth.extensions.wall import make_extension
from virtubooth.extensions.wall.media import cache_path

from ..conftest import ORIGIN
from .wall_support import (
    FakeEnrichment,
    age_photos,
    internal_id,
    put_config,
    set_wall_password,
    upload,
    user_of,
    wait_until,
    wall_login,
    with_wall_page,
)


@pytest.fixture
def fake():
    return FakeEnrichment()


@pytest.fixture
def extensions(demo_extension, fake):
    other = Extension(
        id="other", title="Other", emoji="🧩", tagline="Zweite Quelle", upload=UploadPolicy()
    )
    return [demo_extension, other, make_extension(enrichment=fake)]


@pytest.fixture
def web_dir(web_dir):
    return with_wall_page(web_dir)


@pytest.fixture
def wall(make_client, admin):
    set_wall_password(admin)
    c = make_client()
    assert wall_login(c).status_code == 200
    return c


def feed_ids(client, **params):
    r = client.get("/livewall/api/feed", params=params)
    assert r.status_code == 200, r.text
    return [p["id"] for p in r.json()["photos"]]


def test_feed_shape(wall, guest, core, admin):
    g = guest(instagram="@anna.party")
    pid = upload(g)
    age_photos(core)
    r = wall.get("/livewall/api/feed")
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["event_name"] == "Testparty" and body["total"] == 1
    assert body["config"]["delay_s"] == 20 and body["config"]["rev"] == 0
    assert re.fullmatch(r"[0-9a-f]{8}-\d+", body["cursor"])
    assert body["server_time"].endswith("+00:00")
    (photo,) = body["photos"]
    user = user_of(core, g)
    assert photo == {
        "id": pid,
        "source": "demo",
        "seq": 1,
        "taken_at": photo["taken_at"],
        "width": 1080,
        "height": 1440,
        "author": user.name,
        "instagram": None,
        "author_key": core.signer.mac("wall-author", str(user.id))[:12],
        "urls": {
            "s": f"/livewall/media/{pid}?s=s",
            "m": f"/livewall/media/{pid}?s=m",
            "l": f"/livewall/media/{pid}?s=l",
        },
        "facts": {},
        "analysis": "pending",
    }
    put_config(admin, show_instagram=True)
    (photo,) = wall.get("/livewall/api/feed").json()["photos"]
    assert photo["instagram"] == "anna.party"


def test_analysis_summary_and_public_facts(wall, guest, core, fake):
    pid = upload(guest())
    age_photos(core)
    fake.analysed(
        internal_id(core, pid),
        {"people": 3, "faces": 3, "smiles": 2, "sad_max": 0.7, "age_groups": 2},
    )
    (photo,) = wall.get("/livewall/api/feed").json()["photos"]
    assert photo["analysis"] == "done"
    assert photo["facts"] == {"people": 3, "faces": 3, "smiles": 2}


def test_visibility(wall, guest, admin, core):
    g, other_guest = guest(), guest(fp_n=2)
    hidden, deleted, banned, shown = upload(g), upload(g), upload(other_guest), upload(g)
    age_photos(core)
    assert feed_ids(wall) == [shown, banned, deleted, hidden]
    admin.post(f"/api/admin/photos/{hidden}/hide", headers=ORIGIN)
    admin.delete(f"/api/admin/photos/{deleted}", headers=ORIGIN)
    r = admin.post(f"/api/admin/users/{user_of(core, other_guest).id}/ban", json={}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert feed_ids(wall) == [shown]
    assert wall.get("/livewall/api/feed").json()["total"] == 1
    for pid in (hidden, deleted, banned):
        assert wall.get(f"/livewall/media/{pid}?s=s").status_code == 404
    admin.post(f"/api/admin/photos/{hidden}/unhide", headers=ORIGIN)
    assert feed_ids(wall) == [shown, hidden]


def test_delay(wall, guest, admin, core):
    pid = upload(guest())
    assert feed_ids(wall) == []
    assert wall.get(f"/livewall/media/{pid}?s=s").status_code == 404
    put_config(admin, delay_s=0)
    assert feed_ids(wall) == [pid]
    put_config(admin, delay_s=600)
    assert feed_ids(wall) == []
    age_photos(core, 601)
    assert feed_ids(wall) == [pid]


def test_sources(wall, guest, admin, core):
    g = guest()
    demo, other = upload(g), upload(g, "other")
    age_photos(core)
    assert feed_ids(wall) == [other, demo]
    put_config(admin, sources=["other"])
    assert feed_ids(wall) == [other]
    assert wall.get(f"/livewall/media/{demo}?s=s").status_code == 404
    sources = admin.get("/api/x/wall/admin/config").json()["sources"]
    assert [s["id"] for s in sources] == ["demo", "other"]


def test_limit_and_order(wall, guest, core):
    g = guest()
    ids = [upload(g) for _ in range(3)]
    age_photos(core)
    assert feed_ids(wall, limit=2) == ids[::-1][:2]
    assert wall.get("/livewall/api/feed", params={"limit": 2}).json()["total"] == 3
    assert wall.get("/livewall/api/feed", params={"limit": 0}).status_code == 422
    assert wall.get("/livewall/api/feed", params={"limit": 1001}).status_code == 422


def size_of(response) -> tuple[int, int]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, max-age=86400"
    with Image.open(io.BytesIO(response.content)) as image:
        return image.size


def test_media_sizes_and_cache(wall, guest, admin, core, monkeypatch):
    pid = upload(guest())
    age_photos(core)
    assert size_of(wall.get(f"/livewall/media/{pid}?s=s")) == (300, 400)
    assert size_of(wall.get(f"/livewall/media/{pid}?s=l")) == (1080, 1440)
    cached = cache_path(core, pid)
    assert not cached.exists()
    assert size_of(wall.get(f"/livewall/media/{pid}?s=m")) == (960, 1280)
    assert cached.is_file() and cached.parent == core.settings.data_dir / "wall/cache/m"
    # the second request is served from the cache
    from virtubooth.extensions.wall import media

    monkeypatch.setattr(media, "_make_medium", lambda *_: pytest.fail("not cached"))
    assert size_of(wall.get(f"/livewall/media/{pid}")) == (960, 1280)
    assert wall.get(f"/livewall/media/{pid}?s=xl").status_code == 422
    assert wall.get("/livewall/media/nope?s=s").status_code == 404
    assert wall.get("/livewall/media/AAAAAAAAAAAAAAAA?s=s").status_code == 404
    # deleting the photo removes the cached copy too
    admin.delete(f"/api/admin/photos/{pid}", headers=ORIGIN)
    wait_until(lambda: not cached.exists())


def test_media_needs_the_wall(make_client, guest, core, admin):
    pid = upload(guest())
    age_photos(core)
    r = make_client().get(f"/livewall/media/{pid}?s=s")
    assert r.status_code == 401 and r.json()["error"] == "wall_login_required"
    assert admin.get(f"/livewall/media/{pid}?s=s").status_code == 200
