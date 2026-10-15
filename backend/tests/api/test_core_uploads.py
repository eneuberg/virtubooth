"""Upload pipeline, media access, bans, deletion, events."""

from __future__ import annotations

import asyncio
import io
import threading

from fastapi.sse import format_sse_event
from PIL import Image

from virtubooth.api.routers.admin.events import sse_message
from virtubooth.core.events import EventBus
from virtubooth.domain.models import PhotoQuery

from ..conftest import JPEG, ORIGIN, jpeg, png, scan


def upload(client, data=None, headers=None, ext="demo"):
    data = jpeg() if data is None else data
    return client.post(f"/api/x/{ext}/upload", content=data, headers=headers or JPEG)


def test_upload_happy_path(guest, core, settings):
    g = guest()
    r = upload(g, headers=JPEG | {"X-VB-Meta": "%7B%22mood%22%3A%22happy%22%7D"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["photo"]["seq"] == 1
    assert body["count"] == 1  # from on_upload
    assert upload(g).json()["photo"]["seq"] == 2

    photos = core.repos.photos.list(PhotoQuery(extension="demo", order="asc"))
    assert [p.seq for p in photos] == [1, 2]
    assert photos[0].meta == {"mood": "happy"}
    files = sorted((settings.data_dir / "demo").glob("*.jpg"))
    thumbs = sorted((settings.data_dir / "demo" / "thumbs").glob("*.jpg"))
    assert len(files) == 2 and len(thumbs) == 2
    assert files[0].name < files[1].name  # timestamped names sort by time


def test_upload_reencodes_and_strips_exif(guest, settings):
    g = guest()
    img = Image.new("RGB", (800, 600), (10, 200, 10))
    exif = Image.Exif()
    exif[0x010F] = "SpyCam"  # Make
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    raw = buf.getvalue() + b"TRAILING-GARBAGE"
    assert upload(g, raw).status_code == 201
    stored = next((settings.data_dir / "demo").glob("*.jpg")).read_bytes()
    assert b"SpyCam" not in stored and b"TRAILING-GARBAGE" not in stored
    assert len(Image.open(io.BytesIO(stored)).getexif()) == 0


def test_upload_rejections(guest):
    g = guest()
    assert (
        upload(g, headers={"Content-Type": "image/png", "Origin": "http://testserver"}).status_code
        == 415
    )
    r = upload(g, png())
    assert r.status_code == 400 and r.json()["error"] == "invalid_image"
    assert upload(g, b"\xff\xd8\xff" + b"garbage" * 100).json()["error"] == "invalid_image"
    assert upload(g, jpeg(3000, 3000)).json()["error"] == "invalid_image"  # > max_side
    assert upload(g, jpeg(20, 20)).json()["error"] == "invalid_image"  # < min_side
    r = upload(g, headers=JPEG | {"X-VB-Meta": "%7B%22evil%22%3A1%7D"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_meta"
    r = upload(g, headers=JPEG | {"X-VB-Meta": "%7B%22mood%22%3A%22angry%22%7D"})
    assert r.json()["message"] == "Unbekannte Laune."
    assert upload(g, headers=JPEG | {"X-VB-Meta": "not json"}).status_code == 400
    assert upload(g, b"").status_code in (400, 422)
    assert upload(g, ext="nope").status_code == 404


def test_upload_refused_while_the_disk_is_almost_full(guest, core, caplog):
    """online-review 2b: below VB_MIN_FREE_MB free, no upload is read or stored
    (503 storage_full with Retry-After); one warning a minute in the log."""
    g = guest()
    uploads = core.services.uploads
    uploads.free_bytes = lambda: 2047 * 1024 * 1024  # default minimum: 2048 MB
    caplog.set_level("WARNING", logger="virtubooth.services.uploads")
    for _ in range(2):
        r = upload(g)
        assert r.status_code == 503
        assert r.json() == {
            "error": "storage_full",
            "message": "Der Speicher auf dem Server ist fast voll. "
            "Sag bitte den Gastgebern Bescheid.",
        }
        assert r.headers["retry-after"] == "300"
    assert [r.message for r in caplog.records] == [
        f"uploads refused: 2047 MB free under {core.settings.data_dir}, below VB_MIN_FREE_MB=2048"
    ]
    assert core.repos.photos.count() == 0

    uploads.free_bytes = lambda: 2048 * 1024 * 1024
    assert upload(g).status_code == 201
    # VB_MIN_FREE_MB=0 turns the check off
    uploads.free_bytes = lambda: 0
    core.settings = core.settings.replace(min_free_mb=0)
    assert upload(g).status_code == 201


def test_disk_check_reads_the_data_dir(core):
    assert core.services.uploads.free_bytes() > 0


def test_photo_cap_per_guest(guest, core, admin):
    """online-review 2b: VB_MAX_PHOTOS_PER_GUEST photos that are not deleted,
    over every activity; deleting one makes room; 0 = no cap."""
    core.settings = core.settings.replace(max_photos_per_guest=2)
    g, other = guest(), guest(fp_n=2)
    first = upload(g).json()["photo"]["id"]
    assert upload(g).status_code == 201
    r = upload(g)
    assert r.status_code == 403
    assert r.json() == {
        "error": "photo_limit",
        "message": "Du hast schon sehr viele Fotos gemacht – mehr passen leider nicht. "
        "Lösche ein paar unter „Deine Bilder“, dann geht's weiter.",
    }
    assert upload(other).status_code == 201  # per guest
    assert g.delete(f"/api/me/photos/{first}", headers=ORIGIN).status_code == 200
    assert upload(g).status_code == 201
    assert upload(g).json()["error"] == "photo_limit"
    core.settings = core.settings.replace(max_photos_per_guest=0)
    assert upload(g).status_code == 201


def test_upload_guard_defaults(settings):
    assert settings.min_free_mb == 2048
    assert settings.max_photos_per_guest == 300
    assert settings.scans_per_ip_per_10min == 120


def test_exact_size_policy(guest, core, demo_extension):
    from dataclasses import replace

    policy = replace(demo_extension.upload, exact_size=(1080, 1440))
    core.extensions["demo"] = replace(demo_extension, upload=policy)
    g = guest()
    assert upload(g, jpeg(1080, 1440)).status_code == 201
    r = upload(g, jpeg(1440, 1080))
    assert r.status_code == 400 and "1080×1440" in r.json()["message"]


def test_upload_too_large(guest, core):
    core.settings = core.settings.replace(max_upload_bytes=10_000)
    g = guest()
    r = upload(g, jpeg(1000, 1000) + b"\0" * 20_000)
    assert r.status_code == 413
    # a lying Content-Length must not get around the limit either
    r = g.post(
        "/api/x/demo/upload",
        content=(chunk for chunk in [b"\xff\xd8\xff" + b"\0" * 15_000]),
        headers=JPEG,
    )
    assert r.status_code == 413


def test_upload_needs_access_consent_and_no_ban(client, guest, core):
    assert upload(client).json()["error"] == "scan_qr"
    scan(client)
    assert upload(client).status_code == 401
    g = guest()
    user = core.repos.users.list()[0]
    core.services.moderation.ban_user(user.id, reason="test", actor="pytest")
    r = upload(g)
    assert r.status_code == 403 and r.json()["error"] == "banned"


def test_upload_rate_limit_per_user(guest, core):
    core.limits.upload_user = type(core.limits.upload_user)(2, 60)
    g, other = guest(), guest(fp_n=2)
    assert upload(g).status_code == 201
    assert upload(g).status_code == 201
    r = upload(g)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert upload(other).status_code == 201  # other guests unaffected


def test_media_access_rules(guest, admin, make_client, core):
    owner, stranger = guest(), guest(fp_n=2)
    photo_id = upload(owner).json()["photo"]["id"]
    assert owner.get(f"/media/{photo_id}").status_code == 200
    assert owner.get(f"/media/{photo_id}?thumb=1").headers["content-type"] == "image/jpeg"
    assert stranger.get(f"/media/{photo_id}").status_code == 404
    assert make_client().get(f"/media/{photo_id}").status_code == 404
    assert admin.get(f"/media/{photo_id}").status_code == 200
    r = admin.get(f"/media/{photo_id}?download=1")
    assert "attachment" in r.headers["content-disposition"]
    assert admin.get("/media/../../etc/passwd").status_code == 404
    core.services.moderation.delete_photo(photo_id, actor="pytest")
    assert admin.get(f"/media/{photo_id}").status_code == 404


def test_ban_hides_photos_and_unban_restores_only_those(guest, core):
    g = guest()
    a = upload(g).json()["photo"]["id"]
    b = upload(g).json()["photo"]["id"]
    core.services.moderation.hide_photo(a, actor="pytest")  # hidden by admin before the ban
    user = core.repos.users.list()[0]
    assert core.services.moderation.ban_user(user.id, reason="spam", actor="pytest").changed
    assert not core.services.moderation.ban_user(
        user.id, reason="spam", actor="pytest"
    ).changed  # already banned
    assert all(p.hidden for p in core.repos.photos.list(PhotoQuery(user_id=user.id)))
    core.services.moderation.unban_user(user.id, actor="pytest")
    assert core.repos.photos.get(a).hidden
    assert not core.repos.photos.get(b).hidden
    actions = [e.action for e in core.repos.audit.list()]
    assert {"user.ban", "user.unban", "photo.hide"} <= set(actions)


def test_fingerprint_ban_catches_new_identity(make_client, guest, core):
    guest(fp_n=7)
    core.services.moderation.ban_fingerprint(f"{7:064x}", reason="evader", actor="pytest")
    c = make_client()
    scan(c)
    r = c.post(
        "/api/join",
        json={"accept": True, "version": "1", "fp": {"hash": f"{7:064x}", "components": {}}},
        headers=ORIGIN,
    )
    assert r.json()["state"] == "banned"
    assert upload(c).status_code == 403
    sharing = core.repos.users.sharing_fingerprint(core.repos.users.list()[0].id)
    assert len(sharing) == 1


def test_delete_keeps_tombstone_and_sequence(guest, core, settings):
    g = guest()
    first = upload(g).json()["photo"]["id"]
    assert core.services.moderation.delete_photo(first, actor="pytest")
    assert not core.services.moderation.delete_photo(first, actor="pytest")
    assert list((settings.data_dir / "demo").glob("*.jpg")) == []
    assert upload(g).json()["photo"]["seq"] == 2  # never reuses #1
    assert core.repos.photos.count("demo") == 1
    deleted = core.repos.photos.get(first, include_deleted=True)
    assert deleted is not None and deleted.deleted


def test_list_photos_pagination(guest, core):
    g = guest()
    for _ in range(5):
        upload(g)
    newest = core.repos.photos.list(PhotoQuery(limit=2))
    older = core.repos.photos.list(PhotoQuery(limit=10, before_id=newest[-1].id))
    assert [p.seq for p in newest] == [5, 4]
    assert [p.seq for p in older] == [3, 2, 1]
    newer = core.repos.photos.list(PhotoQuery(after_id=older[0].id))
    assert [p.seq for p in newer] == [5, 4]


def test_upload_publishes_event(guest, core):
    received = []

    async def listen():
        q = core.bus.subscribe()
        received.append(await asyncio.wait_for(q.get(), 5))

    loop = asyncio.new_event_loop()
    core.bus.bind_loop(loop)
    task = loop.create_task(listen())
    t = threading.Thread(target=loop.run_until_complete, args=(task,))
    t.start()
    while not core.bus.subscriber_count:
        pass
    g = guest()
    upload(g)
    t.join(5)
    loop.close()
    types = [e["type"] for e in received]
    assert types and types[0] in ("user.created", "photo.created")


def test_event_bus_drops_stalled_subscriber():
    async def run():
        bus = EventBus(queue_size=2)
        bus.bind_loop(asyncio.get_running_loop())
        q = bus.subscribe()
        for i in range(4):
            bus.publish("x", {"i": i})
        await asyncio.sleep(0.05)
        return q.qsize(), bus.subscriber_count

    size, subs = asyncio.run(run())
    assert size == 2 and subs == 0


def test_format_sse():
    """One bus event on the wire (FastAPI writes the ServerSentEvent fields)."""
    bus = EventBus()
    msg = sse_message(bus, {"id": 3, "type": "photo.created", "data": {"a": 1}})
    wire = format_sse_event(data_str=msg.raw_data, event=msg.event, id=msg.id, retry=msg.retry)
    assert wire == f'event: photo.created\ndata: {{"a": 1}}\nid: {bus.epoch}-3\n\n'.encode()


def test_junk_uploads_dont_use_up_shared_budgets(guest, core):
    """One guest sending invalid uploads must not lock out everyone on the WiFi."""
    core.limits.upload_ip = type(core.limits.upload_ip)(3, 60)
    core.limits.upload_user = type(core.limits.upload_user)(50, 60)
    troll, friend = guest(), guest(fp_n=2)
    for _ in range(20):
        assert upload(troll, b"").status_code == 400
    assert upload(friend).status_code == 201
