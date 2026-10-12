"""Beer Cam API: upload policy, meta validation, numbering, stats, page assets."""

from __future__ import annotations

import io
import json
import re
from html.parser import HTMLParser
from urllib.parse import quote

import pytest
from PIL import Image

from virtubooth.extension import discover_extensions
from virtubooth.extensions import beer
from virtubooth.repo import PhotoQuery

from .conftest import JPEG, jpeg, scan


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
    assert (ext.static_dir / "index.html").is_file()
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

    photos = core.repo.list_photos(PhotoQuery(extension="beer", order="asc"))
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
    assert core.repo.count_photos("beer") == 0


def test_unknown_meta_key_rejected(guest):
    r = upload(guest(), {"vessel": "bottle", "brand": "Augustiner"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_meta"


def test_facing_null_is_dropped(guest, core):
    assert upload(guest(), {"vessel": "cup", "facing": None}).status_code == 201
    assert core.repo.list_photos(PhotoQuery(extension="beer"))[0].meta == {"vessel": "cup"}


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
    user = core.repo.list_users()[0]
    core.repo.ban_user(user.id, "test", "admin:test")
    r = upload(g, {"vessel": "bottle"})
    assert r.status_code == 403 and r.json()["error"] == "banned"


def test_stats_requires_access(client):
    r = client.get("/api/x/beer/stats")
    assert r.status_code == 404 and r.json()["error"] == "scan_qr"
    scan(client)  # access is enough, no consent needed
    r = client.get("/api/x/beer/stats")
    assert r.status_code == 200
    assert r.json() == {"total": 0, "goal": 1_000_000}


def test_stats_counts_non_deleted_beers(guest, core):
    g = guest()
    numbers = [upload(g, {"vessel": "bottle"}).json()["beer_number"] for _ in range(3)]
    assert numbers == [1, 2, 3]
    assert g.get("/api/x/beer/stats").json()["total"] == 3

    first, second, _ = core.repo.list_photos(PhotoQuery(extension="beer", order="asc"))
    core.repo.delete_photo(first.public_id, "admin:test")
    core.repo.hide_photo(second.public_id, "admin:test")  # hidden still counts
    assert g.get("/api/x/beer/stats").json()["total"] == 2

    body = upload(g, {"vessel": "cup"}).json()
    assert body["beer_number"] == 4  # numbers are never reused
    assert body["total"] == 3


def test_stats_ignores_other_extensions(guest, core):
    g = guest()
    upload(g, {"vessel": "bottle"})
    user = core.repo.list_users()[0]
    core.repo.insert_photo(
        extension="booth", user_id=user.id, filename="x.jpg", thumb_filename="thumbs/x.jpg",
        width=10, height=10, size=1, meta={},
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
    assert "beer.js" in r.text and "vb.css" in r.text


@pytest.mark.parametrize(
    ("path", "mime"),
    [("beer.js", "text/javascript"), ("shapes.js", "text/javascript"), ("beer.css", "text/css")],
)
def test_page_assets_served(client, path, mime):
    scan(client)
    r = client.get(f"/x/beer/{path}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(mime)


class _CspAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.problems: list[str] = []
        self.testids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        names = dict(attrs)
        if tag == "style":
            self.problems.append("inline <style>")
        if tag == "script" and "src" not in names:
            self.problems.append("inline <script>")
        for name, value in attrs:
            if name == "style":
                self.problems.append(f"style= on <{tag}>")
            if name.startswith("on"):
                self.problems.append(f"{name}= on <{tag}>")
            if name in ("src", "href") and value and re.match(r"^(https?:)?//", value):
                self.problems.append(f"external {name}={value}")
            if name == "data-testid":
                self.testids.add(value)


def test_page_is_csp_clean():
    html = (beer.extension.static_dir / "index.html").read_text(encoding="utf-8")
    audit = _CspAudit()
    audit.feed(html)
    assert audit.problems == []
    assert {"shutter", "frame", "vessel-bottle", "vessel-cup", "success-title", "again"} <= audit.testids
    for js in beer.extension.static_dir.glob("*.js"):
        source = js.read_text(encoding="utf-8")
        assert "innerHTML" not in source, js.name
        assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", source), js.name
