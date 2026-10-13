"""Beer Cam API: upload policy, meta validation, numbering, stats, page assets."""

from __future__ import annotations

import io
import json
from urllib.parse import quote

import pytest
from PIL import Image

from virtubooth.core.clock import now_iso
from virtubooth.domain.models import PhotoQuery, new_public_id
from virtubooth.extensions import beer
from virtubooth.extensions.sdk import discover_extensions

from ..conftest import JPEG, jpeg, scan


@pytest.fixture
def extensions():
    return discover_extensions(["beer"])


def meta_header(meta: dict) -> dict[str, str]:
    return {"X-VB-Meta": quote(json.dumps(meta))}


def upload(client, meta=None, data=None):
    headers = JPEG | (meta_header(meta) if meta is not None else {})
    return client.post("/api/x/beer/upload", content=jpeg() if data is None else data, headers=headers)


def test_extension_definition():
    ext = beer.extension
    assert (ext.id, ext.title, ext.emoji, ext.order) == ("beer", "Beer Cam", "🍺", 10)
    assert ext.tagline and len(ext.tagline) < 60
    assert ext.upload is not None
    assert ext.upload.max_side == 1440
    assert ext.upload.meta_keys == {"vessel", "facing"}
    assert dict(ext.meta_labels) == {"vessel": "Gefäß", "facing": "Kamera"}
    assert [e.id for e in discover_extensions()].count("beer") == 1


def test_upload_returns_beer_number_and_total(guest, core, settings):
    g = guest()
    r = upload(g, {"vessel": "bottle", "facing": "environment"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["beer_number"] == 1
    assert body["total"] == 1
    assert body["photo"]["seq"] == 1
    assert (body["photo"]["width"], body["photo"]["height"]) == (1080, 1440)

    other = guest(fp_n=2)
    r = upload(other, {"vessel": "cup"})
    assert r.status_code == 201, r.text
    assert (r.json()["beer_number"], r.json()["total"]) == (2, 2)

    photos = core.repos.photos.list(PhotoQuery(extension="beer", order="asc"))
    assert [p.meta for p in photos] == [{"vessel": "bottle", "facing": "environment"}, {"vessel": "cup"}]
    assert len(list((settings.data_dir / "beer").glob("*.jpg"))) == 2


def test_stored_photo_is_1080x1440(guest, settings):
    g = guest()
    assert upload(g, {"vessel": "bottle"}).status_code == 201
    stored = next((settings.data_dir / "beer").glob("*.jpg"))
    assert Image.open(io.BytesIO(stored.read_bytes())).size == (1080, 1440)


@pytest.mark.parametrize(
    ("meta", "message"),
    [
        (None, "Unbekanntes Gefäß. Flasche oder Becher?"),  # no header at all
        ({}, "Unbekanntes Gefäß. Flasche oder Becher?"),
        ({"vessel": "glass"}, "Unbekanntes Gefäß. Flasche oder Becher?"),
        ({"vessel": "BOTTLE"}, "Unbekanntes Gefäß. Flasche oder Becher?"),
        ({"vessel": 1}, "Unbekanntes Gefäß. Flasche oder Becher?"),
        ({"vessel": None}, "Unbekanntes Gefäß. Flasche oder Becher?"),
        ({"vessel": "bottle", "facing": "sideways"}, "Unbekannte Kamera."),
        ({"vessel": "bottle", "facing": True}, "Unbekannte Kamera."),
    ],
)
def test_invalid_meta_rejected(guest, core, meta, message):
    g = guest()
    r = upload(g, meta)
    assert r.status_code == 400, r.text
    assert r.json() == {"error": "invalid_meta", "message": message}
    assert core.repos.photos.count("beer") == 0


def test_unknown_meta_key_rejected(guest):
    r = upload(guest(), {"vessel": "bottle", "brand": "Augustiner"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_meta"


def test_facing_null_is_dropped(guest, core):
    assert upload(guest(), {"vessel": "cup", "facing": None}).status_code == 201
    assert core.repos.photos.list(PhotoQuery(extension="beer"))[0].meta == {"vessel": "cup"}


def test_image_size_limits(guest):
    g = guest()
    r = upload(g, {"vessel": "bottle"}, jpeg(1600, 2000))
    assert r.status_code == 400 and r.json()["error"] == "invalid_image"
    r = upload(g, {"vessel": "bottle"}, jpeg(300, 400))
    assert r.status_code == 400 and r.json()["error"] == "invalid_image"


def test_upload_needs_consent(client):
    scan(client)
    r = upload(client, {"vessel": "bottle"})
    assert r.status_code == 401 and r.json()["error"] == "needs_consent"


def test_banned_guest_cannot_upload(guest, core):
    g = guest()
    user = core.repos.users.list()[0]
    core.services.moderation.ban_user(user.id, reason="test", actor="admin:test")
    r = upload(g, {"vessel": "bottle"})
    assert r.status_code == 403 and r.json()["error"] == "banned"


def test_stats_requires_access(client):
    r = client.get("/api/x/beer/stats")
    assert r.status_code == 404 and r.json()["error"] == "scan_qr"
    scan(client)  # access is enough, no consent needed
    r = client.get("/api/x/beer/stats")
    assert r.status_code == 200
    assert r.json() == {"total": 0, "goal": 1_000_000}


def test_stats_counts_visible_beers(guest, core):
    g = guest()
    numbers = [upload(g, {"vessel": "bottle"}).json()["beer_number"] for _ in range(3)]
    assert numbers == [1, 2, 3]
    assert g.get("/api/x/beer/stats").json()["total"] == 3

    first, second, _ = core.repos.photos.list(PhotoQuery(extension="beer", order="asc"))
    core.services.moderation.delete_photo(first.public_id, actor="admin:test")
    core.services.moderation.hide_photo(second.public_id, actor="admin:test")  # taken down: no longer counts
    assert g.get("/api/x/beer/stats").json()["total"] == 1

    body = upload(g, {"vessel": "cup"}).json()
    assert body["beer_number"] == 4  # numbers are never reused
    assert body["total"] == 2


def test_rejects_wrong_frame_size(guest):
    g = guest()
    r = upload(g, {"vessel": "bottle"}, data=jpeg(1440, 1080))
    assert r.status_code == 400 and r.json()["error"] == "invalid_image"


def test_stats_ignores_other_extensions(guest, core):
    g = guest()
    upload(g, {"vessel": "bottle"})
    user = core.repos.users.list()[0]
    core.repos.photos.insert(
        public_id=new_public_id(), extension="booth", user_id=user.id, filename="x.jpg",
        thumb_filename="thumbs/x.jpg", width=10, height=10, size=1, meta={}, created_at=now_iso(),
    )
    assert g.get("/api/x/beer/stats").json()["total"] == 1


def test_listed_on_home(guest):
    exts = guest().get("/api/extensions").json()["extensions"]
    assert [e["id"] for e in exts] == ["beer"]
    assert exts[0]["url"] == "/x/beer/" and exts[0]["uploads"] is True


# ------------------------------------------------------------------ page


def test_page_requires_access(client):
    r = client.get("/x/beer/")
    assert r.status_code == 404 and 'data-testid="gate"' in r.text
    scan(client, "/x/beer/")
    r = client.get("/x/beer/")
    assert r.status_code == 200
    # the guest app's shell (the stub build's index.html); it renders the Beer Cam
    assert 'data-testid="stub-guest-app"' in r.text
