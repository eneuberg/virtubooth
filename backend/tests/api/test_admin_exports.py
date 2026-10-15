"""Admin export jobs (`/api/admin/exports`): archive and timelapse as
background jobs, one at a time, persisted, with events, audit, downloads and
cleanup.

The worker runs in a thread; `wait_idle()` makes every test deterministic, and
tests that need a job to stay running swap its runner for one that blocks
until released (`Gate`)."""

from __future__ import annotations

import io
import json
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import zipfile
from collections.abc import Iterator
from typing import Any

import httpx2 as httpx
import pytest
import uvicorn
from fastapi import FastAPI

from virtubooth.api.schemas.events import AdminEvent
from virtubooth.app import create_app
from virtubooth.domain.exports import RESTART_ERROR
from virtubooth.services import export_runners
from virtubooth.services import exports as exports_service
from virtubooth.services.export_runners import JobContext
from virtubooth.tools.timelapse import Size

from ..conftest import ADMIN_PASSWORD, JPEG, ORIGIN, PARTY_TOKEN, jpeg
from .test_admin_events import Stream

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")
CURSOR_RE = re.compile(r"^[0-9a-f]{8}-\d+$")
BASE = "https://party.example.com"


# ------------------------------------------------------------------ helpers


def upload(client, color=(200, 120, 40), size=(1080, 1440)) -> str:
    r = client.post("/api/x/demo/upload", content=jpeg(*size, color=color), headers=JPEG)
    assert r.status_code == 201, r.text
    photo_id: str = r.json()["photo"]["id"]
    return photo_id


def start(admin, kind: str, expect: int = 202, **options: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"kind": kind}
    if options:
        body["options"] = options
    r = admin.post("/api/admin/exports", json=body, headers=ORIGIN)
    assert r.status_code == expect, r.text
    job: dict[str, Any] = r.json()["job"]
    return job


def idle(core) -> None:
    assert core.services.exports.wait_idle(60), "export worker still busy"


def jobs(admin) -> list[dict[str, Any]]:
    r = admin.get("/api/admin/exports")
    assert r.status_code == 200, r.text
    result: list[dict[str, Any]] = r.json()["jobs"]
    return result


def job(admin, job_id: str) -> dict[str, Any]:
    return next(j for j in jobs(admin) if j["id"] == job_id)


def run(admin, core, kind: str, **options: Any) -> dict[str, Any]:
    created = start(admin, kind, **options)
    idle(core)
    return job(admin, created["id"])


def download(admin, done: dict[str, Any]):
    r = admin.get(done["download_url"])
    assert r.status_code == 200, r.text
    return r


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        return {name: zf.read(name) for name in zf.namelist()}


def strip_root(files: dict[str, bytes], root: str) -> dict[str, bytes]:
    assert all(name.startswith(root + "/") for name in files), list(files)
    return {name[len(root) + 1 :]: data for name, data in files.items()}


class Gate:
    """A runner that blocks until released, then writes a small file."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.ran: list[str] = []

    def __call__(self, ctx: JobContext) -> None:
        self.ran.append(ctx.job.id)
        self.started.set()
        assert self.release.wait(30), "gate never released"
        ctx.part.write_bytes(b"gated")


@pytest.fixture
def gate(core) -> Iterator[Gate]:
    g = Gate()
    core.services.exports.runners["archive"] = g
    yield g
    g.release.set()  # never leave the worker hanging


def _quick(ctx: JobContext) -> None:
    ctx.part.write_bytes(b"quick")


@pytest.fixture
def quick(core) -> None:
    """A timelapse job that only writes a small file (no ffmpeg needed)."""
    core.services.exports.runners["timelapse"] = _quick


@pytest.fixture
def published(core, monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    """Every event the bus publishes, in order (also from the worker thread)."""
    seen: list[tuple[str, dict[str, Any]]] = []
    real = core.bus.publish

    def spy(type_: str, data: dict[str, Any]) -> None:
        seen.append((type_, data))
        real(type_, data)

    monkeypatch.setattr(core.bus, "publish", spy)
    return seen


@pytest.fixture
def small_video(monkeypatch) -> None:
    """Tiny, fast timelapse videos (the photos keep their 3:4)."""
    monkeypatch.setattr(export_runners, "TIMELAPSE_SIZE", Size(120, 160))
    monkeypatch.setattr(export_runners, "TIMELAPSE_PRESET", "ultrafast")


@pytest.fixture
def base_url(core) -> str:
    core.settings = core.settings.replace(public_base_url=BASE)
    return BASE


# ------------------------------------------------------------------ archive


def test_archive_job_end_to_end(admin, guest, core):
    g = guest(instagram="anna.party")
    ids = [upload(g, (255, 0, 0)), upload(g, (0, 255, 0)), upload(g, (0, 0, 255))]
    core.services.moderation.hide_photo(ids[1], actor="pytest")

    created = start(admin, "archive")
    assert created["status"] == "queued" and created["progress"] is None
    assert created["options"] == {"include_hidden": False, "include_db": False}
    assert created["file_name"] is None and created["download_url"] is None
    idle(core)

    done = job(admin, created["id"])
    assert done["status"] == "done" and done["progress"] == 1 and done["error"] is None
    assert done["started_at"] and done["finished_at"] >= done["started_at"]
    assert re.fullmatch(r"archiv-\d{8}-\d{4}-[\w-]{8}\.zip", done["file_name"])
    assert done["download_url"] == f"/api/admin/exports/{done['id']}/download"

    r = download(admin, done)
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == f'attachment; filename="{done["file_name"]}"'
    assert r.headers["cache-control"] == "no-store"
    assert CURSOR_RE.match(r.headers["x-vb-event-id"])
    assert len(r.content) == done["bytes"]
    files = strip_root(unzip(r.content), done["file_name"].removesuffix(".zip"))

    photos = sorted(n for n in files if n.startswith("photos/"))
    assert len(photos) == 2 and not [n for n in photos if "/hidden/" in n]
    assert photos[0].startswith("photos/demo/0001_") and photos[1].startswith("photos/demo/0003_")
    first = core.repos.photos.get(ids[0])
    assert files[photos[0]] == core.repos.photos.path("demo", first.filename).read_bytes()
    assert set(files) - set(photos) == {
        "README.txt", "photos.csv", "users.csv", "instagram.csv", "manifest.json",
    }  # fmt: skip
    manifest = json.loads(files["manifest.json"])
    assert manifest["format"] == "virtubooth-archive/1" and manifest["party_name"] == "Testparty"
    assert (manifest["photos"], manifest["hidden"], manifest["guests"]) == (2, 0, 1)
    assert [f["id"] for f in manifest["files"]] == [ids[0], ids[2]]
    assert manifest["files"][0]["instagram"] == "anna.party"
    assert {f["file"] for f in manifest["files"]} == set(photos)
    readme = files["README.txt"].decode()
    assert "manifest.json" in readme and "--no-hidden" not in readme
    assert "(Europe/Berlin) from" in readme  # VB_TIMEZONE, as the file name
    assert "anna.party" in files["instagram.csv"].decode("utf-8-sig")
    # only the zip is left behind: no snapshot, no partial file
    assert [p.name for p in (core.settings.data_dir / "exports").iterdir()] == [done["file_name"]]


def test_archive_with_hidden_photos_and_database(admin, guest, core):
    g = guest()
    a, b = upload(g), upload(g)
    core.services.moderation.hide_photo(b, actor="pytest")
    done = run(admin, core, "archive", include_hidden=True, include_db=True)
    assert done["options"] == {"include_hidden": True, "include_db": True}
    files = strip_root(unzip(download(admin, done).content), done["file_name"][:-4])
    assert any(n.startswith("photos/demo/hidden/0002_") for n in files)
    assert json.loads(files["manifest.json"])["hidden"] == 1

    db_copy = core.settings.data_dir.parent / "copy.db"
    db_copy.write_bytes(files["virtubooth.db"])
    conn = sqlite3.connect(db_copy)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        ids = {r[0] for r in conn.execute("SELECT public_id FROM photos")}
        assert ids == {a, b}
        # SEC-03: no admin sessions (token hashes, password tags, admin IPs) and
        # no export jobs; the tables stay, so the copy still opens as a database
        assert conn.execute("SELECT COUNT(*) FROM admin_sessions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM export_jobs").fetchone()[0] == 0
        assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0
    finally:
        conn.close()


def test_archive_of_an_empty_party(admin, core):
    done = run(admin, core, "archive")
    assert done["status"] == "done"
    files = unzip(download(admin, done).content)
    assert not [n for n in files if "/photos/" in n]
    assert any(n.endswith("/manifest.json") for n in files)


# ------------------------------------------------- the removed QR sheet (N16)


def test_qr_kind_is_gone(admin, core):
    for body in ({"kind": "qr"}, {"kind": "qr", "options": {"base_url": BASE}}):
        r = admin.post("/api/admin/exports", json=body, headers=ORIGIN)
        assert r.status_code == 422 and r.json()["error"] == "invalid_request"
    assert core.repos.exports.list() == []


def test_old_qr_jobs_are_hidden(admin, core):
    """Records of the old QR sheet stay in the table but never show up."""
    idle(core)
    core.repos.exports.insert(
        "OldQrJob00000001", kind="qr", options={"base_url": BASE, "code_id": 1},  # type: ignore[arg-type]
        created_at="2026-10-13T20:00:00.000+00:00", by="admin:test",
    )  # fmt: skip
    core.db.one(
        "UPDATE export_jobs SET status='done', file_name='qr-codes-x.zip' WHERE id=? RETURNING id",
        ("OldQrJob00000001",),
    )
    assert admin.get("/api/admin/exports").json()["jobs"] == []
    r = admin.get("/api/admin/exports/OldQrJob00000001/download")
    assert r.status_code == 404
    r = admin.delete("/api/admin/exports/OldQrJob00000001", headers=ORIGIN)
    assert r.status_code == 404
    done = run(admin, core, "archive")
    assert [j["id"] for j in jobs(admin)] == [done["id"]]


def test_list_tells_the_form_its_defaults(admin, base_url, monkeypatch):
    body = admin.get("/api/admin/exports").json()
    assert body == {"jobs": [], "public_base_url": BASE, "ffmpeg": HAS_FFMPEG}
    monkeypatch.setattr(shutil, "which", lambda *a, **kw: None)
    assert admin.get("/api/admin/exports").json()["ffmpeg"] is False


# ---------------------------------------------------------------- timelapse


@needs_ffmpeg
def test_timelapse_job_makes_a_video(admin, guest, core, small_video):
    g = guest()
    for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255)):
        upload(g, color)
    done = run(admin, core, "timelapse", extension="demo", fps=6)
    assert done["status"] == "done", done["error"]
    assert done["options"] == {
        "extension": "demo", "fps": 6, "crossfade": False, "include_hidden": False,
    }  # fmt: skip
    assert re.fullmatch(r"zeitraffer-demo-\d{8}-\d{4}-[\w-]{8}\.mp4", done["file_name"])
    r = download(admin, done)
    assert r.headers["content-type"] == "video/mp4"
    assert r.content[4:8] == b"ftyp"
    video = core.settings.data_dir / "exports" / done["file_name"]
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
         "stream=width,height,nb_read_frames", "-of", "json", str(video)],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    stream = json.loads(out)["streams"][0]
    # 3 photos at 6/s plus the last one held for 2 s
    assert (stream["width"], stream["height"]) == (120, 160)
    assert int(stream["nb_read_frames"]) == 3 + 12


@needs_ffmpeg
def test_timelapse_crossfade_at_the_highest_rate(admin, guest, core, small_video):
    g = guest()
    upload(g, (255, 0, 0))
    upload(g, (0, 0, 255))
    done = run(admin, core, "timelapse", extension="demo", fps=30, crossfade=True)
    assert done["status"] == "done", done["error"]


def test_timelapse_without_ffmpeg_fails_clearly(admin, guest, core, monkeypatch):
    upload(guest())
    monkeypatch.setattr(shutil, "which", lambda *a, **kw: None)
    failed = run(admin, core, "timelapse", extension="demo")
    assert failed["status"] == "failed" and failed["file_name"] is None
    assert "ffmpeg" in failed["error"] and failed["error"].startswith("Für den Zeitraffer")
    r = admin.get(f"/api/admin/exports/{failed['id']}/download")
    assert r.status_code == 409 and r.json()["error"] == "export_not_ready"
    assert "fehlgeschlagen" in r.json()["message"]
    # the worker lives on: the next job runs
    monkeypatch.undo()
    assert run(admin, core, "archive")["status"] == "done"


def test_timelapse_without_photos_fails_with_a_hint(admin, guest, core):
    g = guest()
    pid = upload(g)
    core.services.moderation.hide_photo(pid, actor="pytest")
    failed = run(admin, core, "timelapse", extension="demo")
    assert failed["status"] == "failed"
    assert failed["error"].startswith("Keine Fotos für den Zeitraffer: „Demo“")
    assert "Ausgeblendete einbeziehen" in failed["error"]
    unknown = run(admin, core, "timelapse", extension="nothing")
    assert "„nothing“" in unknown["error"]


# --------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"kind": "everything"},
        {"kind": "archive", "options": {"include_hidden": "maybe"}},
        {"kind": "archive", "options": {"typo": True}},
        {"kind": "timelapse", "options": {"fps": 0}},
        {"kind": "timelapse", "options": {"fps": 31}},
        {"kind": "timelapse", "options": {"extension": "../beer"}},
        {"kind": "timelapse", "options": {"extension": "Beer"}},
        {"kind": "qr"},
        {"kind": "timelapse", "options": {"include_db": True}},
        ["archive"],
    ],
)
def test_invalid_requests(admin, core, body):
    r = admin.post("/api/admin/exports", json=body, headers=ORIGIN)
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "invalid_request"
    assert core.repos.exports.list() == []


def test_unknown_or_malformed_ids(admin):
    for method in ("GET", "DELETE"):
        suffix = "/download" if method == "GET" else ""
        r = admin.request(method, f"/api/admin/exports/AAAAAAAAAAAAAAAA{suffix}", headers=ORIGIN)
        assert r.status_code == 404 and r.json()["error"] == "not_found"
        r = admin.request(method, f"/api/admin/exports/..%2F..%2Fx{suffix}", headers=ORIGIN)
        assert r.status_code in (404, 422)
        r = admin.request(method, f"/api/admin/exports/bad.id!!!!{suffix}", headers=ORIGIN)
        assert r.status_code == 422


# ------------------------------------------------------- queue and lifecycle


def test_one_job_per_kind_and_one_at_a_time(admin, core, gate, quick):
    first = start(admin, "archive")
    assert gate.started.wait(10)
    assert job(admin, first["id"])["status"] == "running"
    # a second archive while one runs: the running one comes back, nothing new
    r = admin.post(
        "/api/admin/exports", json={"kind": "archive", "options": {"include_db": True}},
        headers=ORIGIN,
    )  # fmt: skip
    assert r.status_code == 200 and r.json()["created"] is False
    assert r.json()["job"]["id"] == first["id"] and r.json()["job"]["status"] == "running"
    # another kind queues behind it: one job at a time
    queued = start(admin, "timelapse")
    assert start(admin, "timelapse", expect=200)["id"] == queued["id"]
    assert job(admin, queued["id"])["status"] == "queued"
    assert [j["id"] for j in jobs(admin)] == [queued["id"], first["id"]]  # newest first

    gate.release.set()
    idle(core)
    finished = {j["id"]: j for j in jobs(admin)}
    assert finished[first["id"]]["status"] == finished[queued["id"]]["status"] == "done"
    assert finished[queued["id"]]["started_at"] >= finished[first["id"]]["finished_at"]
    assert gate.ran == [first["id"]]
    # done: a new archive may start
    assert start(admin, "archive")["id"] != first["id"]
    idle(core)


def test_running_job_cannot_be_deleted_or_downloaded(admin, core, gate):
    running = start(admin, "archive")
    assert gate.started.wait(10)
    r = admin.delete(f"/api/admin/exports/{running['id']}", headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"] == "export_running"
    r = admin.get(f"/api/admin/exports/{running['id']}/download")
    assert r.status_code == 409 and r.json()["error"] == "export_not_ready"
    assert r.json()["message"] == "Der Export ist noch nicht fertig."

    gate.release.set()
    idle(core)
    done = job(admin, running["id"])
    file = core.settings.data_dir / "exports" / done["file_name"]
    assert download(admin, done).content == b"gated" and file.is_file()
    r = admin.delete(f"/api/admin/exports/{running['id']}", headers=ORIGIN)
    assert r.status_code == 200 and r.json() == {"ok": True, "id": running["id"]}
    assert not file.exists() and jobs(admin) == []
    assert admin.delete(f"/api/admin/exports/{running['id']}", headers=ORIGIN).status_code == 404
    assert admin.get(done["download_url"]).status_code == 404


def test_deleting_a_queued_job_cancels_it(admin, core, gate, quick):
    running = start(admin, "archive")
    assert gate.started.wait(10)
    queued = start(admin, "timelapse")
    r = admin.delete(f"/api/admin/exports/{queued['id']}", headers=ORIGIN)
    assert r.status_code == 200
    gate.release.set()
    idle(core)
    assert [j["id"] for j in jobs(admin)] == [running["id"]]
    assert not list((core.settings.data_dir / "exports").glob("zeitraffer-*"))


def test_restart_marks_unfinished_jobs_failed(admin, core, extensions):
    idle(core)  # the worker waits; nothing below wakes it
    repos = core.repos.exports
    for job_id, kind in (("JobRunning000001", "archive"), ("JobQueued0000002", "timelapse")):
        repos.insert(job_id, kind=kind, options={}, created_at="2026-10-13T20:00:00.000+00:00",
                     by="admin:test")  # fmt: skip
    # the worker (idle, nothing woke it) must not pick them up: claim one by hand
    assert repos.claim_next(at="2026-10-13T20:00:01.000+00:00").id == "JobRunning000001"
    exports = core.settings.data_dir / "exports"
    exports.mkdir(exist_ok=True)
    (exports / ".JobRunning000001.part").write_bytes(b"half")
    (exports / ".vb-job-JobRunning000001-abc").mkdir()

    restarted = create_app(core.settings, extensions=extensions)  # same data dir
    try:
        again = restarted.state.core.repos.exports
        for job_id in ("JobRunning000001", "JobQueued0000002"):
            failed = again.get(job_id)
            assert failed.status == "failed" and failed.error == RESTART_ERROR
            assert failed.finished_at
    finally:
        restarted.state.core.db.close()
    assert RESTART_ERROR == "Server wurde neu gestartet."
    assert list(exports.iterdir()) == []
    listed = {j["id"]: j for j in jobs(admin)}
    assert listed["JobQueued0000002"]["error"] == RESTART_ERROR


def test_shutdown_cancels_the_running_job(admin, core):
    started = threading.Event()

    def endless(ctx: JobContext) -> None:
        started.set()
        while True:  # a long job that reports progress
            ctx.progress(0.5)
            time.sleep(0.01)

    exports = core.services.exports
    exports.runners["archive"] = endless
    created = start(admin, "archive")
    assert started.wait(10)
    begin = time.monotonic()
    exports.detach()  # what the app's lifespan end does
    assert time.monotonic() - begin < 5
    assert exports._thread is not None and not exports._thread.is_alive()
    failed = core.repos.exports.get(created["id"])
    assert failed.status == "failed" and failed.error == RESTART_ERROR
    assert list((core.settings.data_dir / "exports").iterdir()) == []
    exports.attach()  # the client's own lifespan end detaches once more


def test_crashing_runner_fails_with_a_generic_message(admin, core):
    def broken(ctx: JobContext) -> None:
        ctx.part.write_bytes(b"half")
        raise RuntimeError("boom")

    core.services.exports.runners["archive"] = broken
    failed = run(admin, core, "archive")
    assert failed["status"] == "failed"
    assert failed["error"] == "Der Export ist fehlgeschlagen. Details stehen im Server-Log."
    assert list((core.settings.data_dir / "exports").iterdir()) == []


def test_old_files_are_pruned(admin, core, quick, monkeypatch, published):
    monkeypatch.setattr(exports_service, "KEEP_DONE", 2)
    done = [run(admin, core, "timelapse") for _ in range(3)]
    listed = jobs(admin)
    assert [j["id"] for j in listed] == [done[2]["id"], done[1]["id"]]
    files = sorted(p.name for p in (core.settings.data_dir / "exports").iterdir())
    assert files == sorted([done[1]["file_name"], done[2]["file_name"]])
    assert ("export.deleted", {"id": done[0]["id"]}) in published


# ------------------------------------------------------------ events, audit


def test_events_follow_the_job(admin, core, published):
    created = start(admin, "archive")
    idle(core)
    admin.delete(f"/api/admin/exports/{created['id']}", headers=ORIGIN)
    ours = [(t, d) for t, d in published if t.startswith("export.")]
    statuses = [d["job"]["status"] for t, d in ours if t == "export.updated"]
    assert statuses[0] == "queued" and statuses[1] == "running" and statuses[-1] == "done"
    assert set(statuses) == {"queued", "running", "done"}
    assert ours[-1] == ("export.deleted", {"id": created["id"]})
    done = [d["job"] for t, d in ours if t == "export.updated"][-1]
    assert done["progress"] == 1 and done["download_url"]
    # every payload is a valid AdminEvent (the OpenAPI union)
    for i, (type_, data) in enumerate(ours):
        event = AdminEvent.model_validate({"type": type_, "id": f"0badcafe-{i}", "data": data})
        assert event.root.type == type_


def test_progress_events_are_throttled(admin, core, published):
    def steps(ctx: JobContext) -> None:
        for i in range(1, 1001):
            ctx.progress(i / 1000)
        ctx.part.write_bytes(b"x")

    core.services.exports.runners["archive"] = steps
    run(admin, core, "archive")
    running = [d["job"]["progress"] for t, d in published
               if t == "export.updated" and d["job"]["status"] == "running"]  # fmt: skip
    # started (0), then at most one per 5 % (or per second)
    assert running[0] == 0 and 10 <= len(running) <= 25
    assert running == sorted(running)


def test_create_and_delete_are_audited(admin, core):
    created = start(admin, "archive", include_db=True)
    idle(core)
    admin.delete(f"/api/admin/exports/{created['id']}", headers=ORIGIN)
    entries = admin.get("/api/admin/audit").json()["entries"]
    delete, create = entries[0], entries[1]
    assert create["action"] == "export.create" and create["target"] == f"export:{created['id']}"
    assert create["actor"].startswith("admin:")
    assert create["details"] == {
        "kind": "archive",
        "options": {"include_hidden": False, "include_db": True},
    }
    assert delete["action"] == "export.delete" and delete["target"] == create["target"]
    assert delete["details"]["kind"] == "archive" and delete["details"]["status"] == "done"
    # a refused delete (or a repeated create) leaves no entry
    assert admin.delete(f"/api/admin/exports/{created['id']}", headers=ORIGIN).status_code == 404
    assert [e["action"] for e in admin.get("/api/admin/audit").json()["entries"]] == [
        "export.delete", "export.create", "admin.login", "code.create",
    ]  # fmt: skip


def test_every_answer_carries_the_event_cursor(admin, core):
    created = start(admin, "archive")
    idle(core)
    done = job(admin, created["id"])
    for r in (
        admin.get("/api/admin/exports"),
        admin.post("/api/admin/exports", json={"kind": "archive"}, headers=ORIGIN),
        admin.get(done["download_url"]),
        admin.delete(f"/api/admin/exports/{done['id']}", headers=ORIGIN),
    ):
        assert r.status_code in (200, 202), r.text
        assert CURSOR_RE.match(r.headers["x-vb-event-id"]), r.request.url
    idle(core)


def test_download_never_leaves_the_exports_dir(admin, core):
    done = run(admin, core, "archive")
    secret = core.settings.data_dir / "virtubooth.db"
    assert secret.is_file()
    for name in ("../virtubooth.db", "/etc/passwd", ".hidden", "sub/x.zip"):
        core.db.one(
            "UPDATE export_jobs SET file_name=? WHERE id=? RETURNING id", (name, done["id"])
        )
        r = admin.get(done["download_url"])
        assert r.status_code == 404 and r.json()["error"] == "not_found", name


# ----------------------------------------------------------- live SSE wire


@pytest.fixture
def live_url(app: FastAPI) -> Iterator[str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                       timeout_graceful_shutdown=1)
    )  # fmt: skip
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)


def test_export_events_on_the_admin_stream(live_url, core):
    origin = {"Origin": live_url}
    with httpx.Client(base_url=live_url, timeout=10) as admin:
        assert admin.post("/api/admin/login", json={"password": ADMIN_PASSWORD},
                          headers=origin).status_code == 200  # fmt: skip
        stream = Stream(admin, "/api/admin/events")
        try:
            assert stream.wait_for(lambda line: line.startswith("retry:"))  # subscribed
            # (an https VB_PUBLIC_BASE_URL would make the cookies Secure: not over http)
            body = {"kind": "archive"}
            r = admin.post("/api/admin/exports", json=body, headers=origin)
            assert r.status_code == 202
            job_id = r.json()["job"]["id"]
            statuses = []
            while "done" not in statuses:
                (msg,) = stream.messages(1, timeout=20)
                assert msg["event"] == "export.updated"
                data = json.loads(msg["data"])
                assert data["job"]["id"] == job_id
                statuses.append(data["job"]["status"])
            assert statuses[0] == "queued" and "running" in statuses
        finally:
            stream.close()
