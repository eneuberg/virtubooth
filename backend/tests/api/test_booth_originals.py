"""The Fotobox's unfiltered originals: the page uploads the filtered photo plus
the same frame without the filter in one request (`X-VB-Raw-Bytes`); the
original is stored next to the photo, served under the photo's access rules
(`?variant=raw`), analysed instead of the photo, deleted with it and exported
on request."""

from __future__ import annotations

import io
import json
from urllib.parse import quote

import pytest
from PIL import Image

from virtubooth.extensions.sdk import discover_extensions
from virtubooth.extensions.wall.media import photo_file

from ..conftest import JPEG, ORIGIN, jpeg
from .test_admin_exports import download, run, strip_root, unzip

RED, BLUE = (230, 20, 20), (20, 20, 230)


@pytest.fixture
def extensions():
    return discover_extensions(["booth", "beer"])


def headers(meta: dict | None = None, raw: int | str | None = None) -> dict[str, str]:
    out = dict(JPEG)
    out["X-VB-Meta"] = quote(json.dumps(meta or {"filter": "thermal", "facing": "user"}))
    if raw is not None:
        out["X-VB-Raw-Bytes"] = str(raw)
    return out


def shoot(client, *, filter_id: str = "thermal", photo=None, raw=None, ext: str = "booth"):
    """Upload `photo` (default red) with `raw` appended (default blue; False: none)."""
    photo = jpeg(color=RED) if photo is None else photo
    raw = jpeg(color=BLUE) if raw is None else raw
    meta = {"filter": filter_id, "facing": "user"} if ext == "booth" else {"vessel": "cup"}
    body = photo + (raw or b"")
    return client.post(
        f"/api/x/{ext}/upload",
        content=body,
        headers=headers(meta, len(raw) if raw else None),
    )


def color(data: bytes) -> tuple[int, int, int]:
    pixel = Image.open(io.BytesIO(data)).convert("RGB").getpixel((50, 50))
    assert isinstance(pixel, tuple)
    return pixel[0], pixel[1], pixel[2]


def is_red(data: bytes) -> bool:
    r, _, b = color(data)
    return r > 180 and b < 80


def is_blue(data: bytes) -> bool:
    r, _, b = color(data)
    return b > 180 and r < 80


# ------------------------------------------------------------------ upload


def test_photo_and_original_in_one_request(guest, core, settings):
    g = guest()
    r = shoot(g)
    assert r.status_code == 201, r.text
    photo = r.json()["photo"]
    pid = photo["id"]
    assert photo["raw_url"] == f"/media/{pid}?variant=raw"
    assert photo["raw_thumb_url"] == f"/media/{pid}?variant=raw&thumb=1"
    stored = core.repos.photos.get(pid)
    assert stored.raw_filename == f"raw/{stored.filename}"
    assert stored.raw_thumb_filename == f"raw/thumbs/{stored.filename}"
    folder = settings.data_dir / "booth"
    assert is_red((folder / stored.filename).read_bytes())
    original = (folder / stored.raw_filename).read_bytes()
    assert is_blue(original)
    # re-encoded like the photo: exactly 1080×1440, nothing of the client's bytes kept
    assert Image.open(io.BytesIO(original)).size == (1080, 1440)
    assert Image.open(folder / stored.raw_thumb_filename).size == (300, 400)
    # the photo counts once: bytes, the per-guest cap, the counters
    assert stored.bytes == (folder / stored.filename).stat().st_size
    assert core.repos.photos.count("booth") == 1
    assert r.json()["booth_number"] == 1


def test_old_clients_send_just_the_photo(guest, core):
    g = guest()
    r = g.post("/api/x/booth/upload", content=jpeg(color=RED), headers=headers())
    assert r.status_code == 201, r.text
    photo = r.json()["photo"]
    assert photo["raw_url"] is None and photo["raw_thumb_url"] is None
    assert core.repos.photos.get(photo["id"]).raw_filename is None
    # the original falls back to the photo everywhere
    assert is_red(g.get(f"/media/{photo['id']}?variant=raw").content)


@pytest.mark.parametrize("same_bytes", [False, True])
def test_no_second_file_when_the_photo_is_its_own_original(guest, core, settings, same_bytes):
    g = guest()
    if same_bytes:
        data = jpeg(color=RED)
        r = shoot(g, photo=data, raw=data)
    else:
        r = shoot(g, filter_id="normal")  # „Normal“: no shader, no overlay
    assert r.status_code == 201, r.text
    assert r.json()["photo"]["raw_url"] is None
    assert not (settings.data_dir / "booth" / "raw").exists()


def test_beer_cam_takes_no_original(guest, core):
    g = guest()
    r = shoot(g, ext="beer")
    assert r.status_code == 400 and r.json()["error"] == "raw_not_allowed"
    assert core.repos.photos.count() == 0


@pytest.mark.parametrize("value", ["abc", "0", "-5", "1e3", "9" * 13])
def test_bad_raw_length(guest, core, value):
    g = guest()
    body = jpeg(color=RED) + jpeg(color=BLUE)
    r = g.post("/api/x/booth/upload", content=body, headers=headers(raw=value))
    assert r.status_code == 400 and r.json()["error"] == "invalid_raw"
    assert core.repos.photos.count() == 0


def test_raw_length_must_leave_a_photo(guest, core):
    g = guest()
    body = jpeg(color=BLUE)
    r = g.post("/api/x/booth/upload", content=body, headers=headers(raw=len(body)))
    assert r.status_code == 400 and r.json()["error"] == "invalid_raw"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (jpeg(800, 600, color=BLUE), "1080×1440"),
        (b"\xff\xd8\xff" + b"\0" * 500, "Original ohne Filter"),
        (b"GIF89a" + b"\0" * 500, "JPEG"),
    ],
)
def test_the_original_passes_the_same_checks(guest, core, settings, raw, message):
    g = guest()
    r = shoot(g, raw=raw)
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "invalid_raw" and message in r.json()["message"]
    assert core.repos.photos.count() == 0
    # nothing half-stored
    assert not list((settings.data_dir / "booth").rglob("*.jpg"))


def test_a_bad_photo_is_still_a_bad_photo(guest, core):
    g = guest()
    r = shoot(g, photo=jpeg(800, 600, color=RED))
    assert r.status_code == 400 and r.json()["error"] == "invalid_image"


def test_each_part_has_the_size_limit(guest, core):
    photo, raw = jpeg(color=RED), jpeg(color=BLUE)
    # both together are over the limit, each alone is not: fine
    core.settings = core.settings.replace(max_upload_bytes=max(len(photo), len(raw)) + 10)
    g = guest()
    assert shoot(g, photo=photo, raw=raw).status_code == 201
    # a part over the limit is refused, whichever it is
    big = raw + b"\0" * (core.settings.max_upload_bytes + 1)
    assert shoot(g, photo=photo, raw=big).status_code == 413
    assert (
        shoot(g, photo=photo + b"\0" * (core.settings.max_upload_bytes + 1), raw=raw).status_code
        == 413
    )
    # a declared length over twice the limit is refused before reading
    r = g.post(
        "/api/x/booth/upload",
        content=(
            chunk for chunk in [b"\xff\xd8\xff" + b"\0" * (3 * core.settings.max_upload_bytes)]
        ),
        headers=headers(raw=100),
    )
    assert r.status_code == 413
    assert core.repos.photos.count() == 1


# ------------------------------------------------------------------- media


def test_who_sees_the_original(guest, admin, client, core):
    owner, other = guest(), guest(fp_n=2)
    pid = shoot(owner).json()["photo"]["id"]
    raw_url = f"/media/{pid}?variant=raw"
    assert is_blue(owner.get(raw_url).content)
    assert is_red(owner.get(f"/media/{pid}").content)
    assert is_red(owner.get(f"/media/{pid}?variant=filtered").content)
    assert owner.get(f"{raw_url}&thumb=1").status_code == 200
    assert is_blue(admin.get(raw_url).content)
    # other guests and strangers learn nothing, for either version
    for c in (other, client):
        assert c.get(raw_url).status_code == 404
        assert c.get(f"{raw_url}&thumb=1").status_code == 404
    assert owner.get(f"/media/{pid}?variant=bogus").status_code == 422

    # hidden: the owner and the admin still see both, nobody else either
    assert admin.post(f"/api/admin/photos/{pid}/hide", headers=ORIGIN).status_code == 200
    assert is_blue(owner.get(raw_url).content) and is_blue(admin.get(raw_url).content)
    assert other.get(raw_url).status_code == 404


def test_the_wall_shows_the_filtered_photo(guest, core):
    g = guest()
    pid = shoot(g).json()["photo"]["id"]
    photo = core.repos.photos.get(pid)
    for size in ("s", "m", "l"):
        path = photo_file(core, photo, size)
        assert path is not None and "raw" not in path.parts


def test_download_names(guest, admin):
    g = guest()
    pid = shoot(g).json()["photo"]["id"]
    r = admin.get(f"/media/{pid}?variant=raw&download=1")
    assert r.headers["content-disposition"] == 'attachment; filename="booth-00001-original.jpg"'
    r = g.get(f"/media/{pid}?download=1")
    assert r.headers["content-disposition"] == 'attachment; filename="booth-00001.jpg"'


def test_admin_lists_carry_the_original(guest, admin):
    g = guest()
    with_raw = shoot(g).json()["photo"]["id"]
    without = shoot(g, filter_id="normal").json()["photo"]["id"]
    photos = {p["id"]: p for p in admin.get("/api/admin/photos").json()["photos"]}
    assert photos[with_raw]["raw_url"] == f"/media/{with_raw}?variant=raw"
    assert photos[with_raw]["raw_thumb_url"] == f"/media/{with_raw}?variant=raw&thumb=1"
    assert photos[without]["raw_url"] is None
    mine = {p["id"]: p for p in g.get("/api/me/photos").json()["photos"]}
    assert mine[with_raw]["raw_url"] and mine[with_raw]["meta"]["filter"] == "thermal"


@pytest.mark.parametrize("who", ["guest", "admin"])
def test_deleting_a_photo_deletes_its_original(guest, admin, core, settings, who):
    g = guest()
    pid = shoot(g).json()["photo"]["id"]
    stored = core.repos.photos.get(pid)
    folder = settings.data_dir / "booth"
    files = [stored.filename, stored.thumb_filename, stored.raw_filename, stored.raw_thumb_filename]
    assert all((folder / f).is_file() for f in files)
    if who == "guest":
        r = g.delete(f"/api/me/photos/{pid}", headers=ORIGIN)
    else:
        r = admin.delete(f"/api/admin/photos/{pid}", headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert not any((folder / f).exists() for f in files)
    assert g.get(f"/media/{pid}?variant=raw").status_code == 404


# ------------------------------------------------------------------ export


@pytest.fixture
def party(guest, core):
    """Three Fotobox photos: thermal with an original, Normal, and a hidden one with an original."""
    g = guest()
    a = shoot(g).json()["photo"]["id"]
    b = shoot(g, filter_id="normal").json()["photo"]["id"]
    c = shoot(g).json()["photo"]["id"]
    core.services.moderation.hide_photo(c, actor="pytest")
    return a, b, c


def archive(admin, core, **options) -> tuple[dict[str, bytes], dict]:
    done = run(admin, core, "archive", **options)
    assert done["status"] == "done", done
    files = strip_root(unzip(download(admin, done).content), done["file_name"][:-4])
    return files, json.loads(files["manifest.json"])


def photos_of(files: dict[str, bytes]) -> dict[str, bytes]:
    return {n: d for n, d in files.items() if n.endswith(".jpg")}


def test_export_baked_in_is_the_default(admin, core, party):
    files, manifest = archive(admin, core, include_hidden=True)
    assert manifest["filters"] == "baked" and manifest["originals"] == 0
    jpgs = photos_of(files)
    assert len(jpgs) == 3 and not any("/raw/" in n for n in jpgs)
    assert all(is_red(d) for d in jpgs.values())
    by_id = {f["id"]: f for f in manifest["files"]}
    assert by_id[party[0]]["has_original"] is True and by_id[party[1]]["has_original"] is False
    assert by_id[party[0]]["original_file"] is None


def test_export_without_filters(admin, core, party):
    files, manifest = archive(admin, core, filters="raw", include_hidden=True)
    jpgs = photos_of(files)
    assert len(jpgs) == 3 and not any("/raw/" in n for n in jpgs)
    by_id = {f["id"]: f for f in manifest["files"]}
    # the originals stand in for their photos, under the same names
    assert is_blue(jpgs[by_id[party[0]]["file"]]) and is_blue(jpgs[by_id[party[2]]["file"]])
    # „Normal“ has no separate original: the photo itself
    assert is_red(jpgs[by_id[party[1]]["file"]])
    assert "without their filter" in files["README.txt"].decode()


def test_export_both(admin, core, party):
    files, manifest = archive(admin, core, filters="both")  # hidden left out
    jpgs = photos_of(files)
    by_id = {f["id"]: f for f in manifest["files"]}
    assert party[2] not in by_id  # the hidden photo, and so its original, stay out
    a = by_id[party[0]]
    assert a["original_file"] == a["file"].replace("photos/booth/", "photos/booth/raw/")
    assert is_red(jpgs[a["file"]]) and is_blue(jpgs[a["original_file"]])
    assert by_id[party[1]]["original_file"] is None
    assert len(jpgs) == 3 and manifest["originals"] == 1
    csv = files["photos.csv"].decode("utf-8-sig").splitlines()
    assert csv[0].endswith(",file,has_original,original_file")
    assert any(line.endswith(f",1,{a['original_file']}") for line in csv)


def test_export_both_with_hidden(admin, core, party):
    files, _ = archive(admin, core, filters="both", include_hidden=True)
    hidden_raw = [n for n in photos_of(files) if n.startswith("photos/booth/hidden/raw/")]
    assert len(hidden_raw) == 1 and is_blue(files[hidden_raw[0]])


def test_export_rejects_unknown_filter_mode(admin):
    r = admin.post(
        "/api/admin/exports",
        json={"kind": "archive", "options": {"filters": "sometimes"}},
        headers=ORIGIN,
    )
    assert r.status_code == 422
