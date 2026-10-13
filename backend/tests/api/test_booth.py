"""Fotobox extension: registration, upload meta validation, filter catalogue, page."""

from __future__ import annotations

import json
from urllib.parse import quote

import pytest

from virtubooth.domain.models import PhotoQuery
from virtubooth.extensions import booth
from virtubooth.extensions.sdk import discover_extensions

from ..conftest import JPEG, jpeg, scan

REQUIRED_FILTERS = {"normal", "bw", "sepia", "colorpop", "retro", "vhs", "party", "emoji"}


@pytest.fixture
def extensions():
    return discover_extensions(["booth"])


def meta_header(meta: dict) -> dict:
    return JPEG | {"X-VB-Meta": quote(json.dumps(meta))}


def upload(client, meta: dict | None, data: bytes | None = None):
    headers = JPEG if meta is None else meta_header(meta)
    return client.post("/api/x/booth/upload", content=data or jpeg(1080, 1440), headers=headers)


def test_extension_is_listed(guest):
    g = guest()
    data = g.get("/api/extensions").json()
    [ext] = data["extensions"]
    assert ext == {
        "id": "booth",
        "title": "Fotobox",
        "emoji": "📸",
        "tagline": booth.extension.tagline,
        "url": "/x/booth/",
        "uploads": True,
    }
    assert booth.extension.order == 20
    assert dict(booth.extension.meta_labels) == {"filter": "Filter", "facing": "Kamera"}


def test_upload_stores_meta_and_numbers_photos(guest, core):
    g = guest()
    r = upload(g, {"filter": "bw", "facing": "user"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["booth_number"] == 1 == body["photo"]["seq"]
    assert (body["photo"]["width"], body["photo"]["height"]) == (1080, 1440)
    r = upload(g, {"filter": "party", "facing": "environment"})
    assert r.json()["booth_number"] == 2
    photos = core.repos.photos.list(PhotoQuery(extension="booth", order="asc"))
    assert [p.meta for p in photos] == [
        {"filter": "bw", "facing": "user"},
        {"filter": "party", "facing": "environment"},
    ]


@pytest.mark.parametrize("filter_id", sorted(booth.FILTERS))
def test_every_catalogue_filter_is_accepted(guest, filter_id):
    assert upload(guest(), {"filter": filter_id, "facing": "user"}).status_code == 201


@pytest.mark.parametrize(
    ("meta", "message"),
    [
        ({"filter": "nope", "facing": "user"}, "Unbekannter Filter."),
        ({"filter": "BW", "facing": "user"}, "Unbekannter Filter."),
        ({"filter": "", "facing": "user"}, "Unbekannter Filter."),
        ({"filter": None, "facing": "user"}, "Unbekannter Filter."),
        ({"filter": 1, "facing": "user"}, "Unbekannter Filter."),
        ({"facing": "user"}, "Unbekannter Filter."),
        ({"filter": "bw", "facing": "sideways"}, "Unbekannte Kamera."),
        ({"filter": "bw"}, "Unbekannte Kamera."),
        ({"filter": "bw", "facing": True}, "Unbekannte Kamera."),
    ],
)
def test_invalid_meta_is_rejected(guest, core, meta, message):
    r = upload(guest(), meta)
    assert r.status_code == 400, r.text
    body = r.json()
    assert (body["error"], body["message"]) == ("invalid_meta", message)
    assert core.repos.photos.count("booth") == 0


def test_missing_or_extra_meta_is_rejected(guest):
    g = guest()
    assert upload(g, None).json()["message"] == "Unbekannter Filter."
    r = upload(g, {"filter": "bw", "facing": "user", "secret": "x"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_meta"


def test_oversized_image_is_rejected(guest):
    r = upload(guest(), {"filter": "bw", "facing": "user"}, jpeg(1600, 2133))
    assert r.status_code == 400 and r.json()["error"] == "invalid_image"


def test_upload_needs_consent(client):
    scan(client)
    r = upload(client, {"filter": "bw", "facing": "user"})
    assert r.status_code == 401 and r.json()["error"] == "needs_consent"


# ------------------------------------------------------------ catalogue


def test_filter_catalogue():
    data = json.loads(booth.FILTERS_FILE.read_text(encoding="utf-8"))
    ids = [f["id"] for f in data["filters"]]
    assert list(booth.FILTERS) == ids
    assert REQUIRED_FILTERS <= set(ids)
    assert ids[0] == "normal"
    assert len(set(ids)) == len(ids)
    for entry in data["filters"]:
        assert entry["name"].strip() and entry["icon"].strip()
    assert booth.FILTERS["bw"] == "Schwarz-Weiß"


def test_load_filters_rejects_bad_catalogues(tmp_path):
    bad = tmp_path / "filters.json"
    for filters in (
        [],
        [{"id": "Bad Id", "name": "x"}],
        [{"id": "a", "name": "x"}, {"id": "a", "name": "y"}],
        [{"id": "a", "name": " "}],
    ):
        bad.write_text(json.dumps({"filters": filters}))
        with pytest.raises(ValueError):
            booth.load_filters(bad)


# ----------------------------------------------------------------- page


def test_page_is_served_to_party_guests(client):
    assert client.get("/x/booth/").status_code == 404  # no QR scan yet → gate
    assert client.get("/api/x/booth/filters").json()["error"] == "scan_qr"
    scan(client)
    r = client.get("/x/booth/")
    assert r.status_code == 200
    # the guest app's shell (the stub build's index.html); it renders the Fotobox
    assert 'data-testid="stub-guest-app"' in r.text
    # the page gets the catalogue from the API (it used to fetch ./filters.json)
    r = client.get("/api/x/booth/filters")
    assert r.status_code == 200
    catalogue = json.loads(booth.FILTERS_FILE.read_text(encoding="utf-8"))
    assert r.json() == {"filters": catalogue["filters"]}


# ----------------------------------------------------------------- stats


def test_stats_say_the_next_number_before_the_first_upload(client, guest, core):
    """The film edge shows the next number before a visit's first photo."""
    assert client.get("/api/x/booth/stats").json()["error"] == "scan_qr"
    scan(client)  # party access is enough, like the Beer Cam's counter
    assert client.get("/api/x/booth/stats").json() == {"next_number": 1}
    g = guest()
    first = upload(g, {"filter": "bw", "facing": "user"}).json()
    upload(g, {"filter": "bw", "facing": "user"})
    assert client.get("/api/x/booth/stats").json() == {"next_number": 3}
    # numbers are never reused: a deleted or hidden photo keeps its number
    core.services.moderation.delete_photo(first["photo"]["id"], actor="admin:test")
    assert client.get("/api/x/booth/stats").json() == {"next_number": 3}
    assert upload(g, {"filter": "bw", "facing": "user"}).json()["booth_number"] == 3
    assert g.get("/api/x/booth/stats").json() == {"next_number": 4}
