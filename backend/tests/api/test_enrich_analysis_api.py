"""The analysis admin API (PLAN §4.4), mounted like WINT will: the enrich
router under the wall extension's prefix `/api/x/wall`."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from virtubooth.extensions.wall.enrich import admin_api, downloads, jobs, models
from virtubooth.extensions.wall.enrich.service import EnrichmentService

from ..conftest import JPEG, ORIGIN, jpeg

BASE = "/api/x/wall/admin"


@pytest.fixture(autouse=True)
def mounted(app, monkeypatch):
    monkeypatch.setenv("VB_WALL_WORKER", "off")
    app.include_router(admin_api.router, prefix="/api/x/wall")


def upload(client) -> str:
    r = client.post("/api/x/demo/upload", content=jpeg(), headers=JPEG)
    assert r.status_code == 201, r.text
    photo_id: str = r.json()["photo"]["id"]
    return photo_id


def internal(core, public_id: str) -> int:
    pid = core.repos.photos.internal_id(public_id)
    assert pid is not None
    return pid


def test_admin_only(client):
    for method, path in [
        ("get", f"{BASE}/analysis"),
        ("post", f"{BASE}/analysis/models/download"),
        ("put", f"{BASE}/analysis/analyzers"),
        ("put", f"{BASE}/analysis/analyzers/faces"),
        ("get", f"{BASE}/photos/x/analysis"),
    ]:
        r = client.request(method, path, json={}, headers=ORIGIN)
        assert r.status_code == 401 and r.json()["error"] == "admin_required", path


def test_status(admin, guest, core):
    g = guest()
    upload(g)
    upload(g)
    r = admin.get(f"{BASE}/analysis")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["worker"]["state"] == "off" and body["worker"]["message"]
    assert body["counts"] == {
        "pending": 2, "running": 0, "done": 0, "failed": 0, "skipped": 0, "total": 2,
    }  # fmt: skip
    analyzers = {a["name"]: a for a in body["analyzers"]}
    assert list(analyzers) == ["basic", "faces", "emotion", "gestures", "objects", "tags", "age"]
    basic = analyzers["basic"]
    assert {k: basic[k] for k in ("name", "title", "kind", "version", "enabled", "available",
                                  "reason", "facts", "settings", "settings_schema")} == {
        "name": "basic", "title": "Bildwerte", "kind": "basic", "version": "1", "enabled": True,
        "available": True, "reason": None,
        "facts": ["brightness", "colorfulness", "sharpness"], "settings": None,
        "settings_schema": [],
    }  # fmt: skip
    assert basic["description"] and basic["stats"]["processed"] == 0
    assert body["queue"]["pending"] == 2
    assert analyzers["age"]["enabled"] is False  # FairFace is opt-in
    # no models in the test data dir: the ML analyzers say why they cannot run
    assert analyzers["faces"]["available"] is False and analyzers["faces"]["reason"]


def test_status_uses_a_fresh_heartbeat(admin, core):
    beat = {"pid": 1, "beat_at": datetime.now(UTC).isoformat(), "ml": True, "models_missing": []}
    core.repos.app_settings.put(jobs.WORKER_KEY, beat, at=beat["beat_at"])
    body = admin.get(f"{BASE}/analysis").json()
    # VB_WALL_WORKER=off here, but a worker elsewhere (another container) beats
    assert body["worker"]["state"] == "running" and body["worker"]["ml"] is True
    analyzers = {a["name"]: a for a in body["analyzers"]}
    assert analyzers["faces"]["available"] is True and analyzers["emotion"]["available"] is True
    # an older beat without the numbers: nothing to show
    assert body["worker"]["processed"] is None and body["worker"]["rss_mb"] is None
    assert body["worker"]["load_errors"] == {}


def test_status_passes_the_heartbeat_numbers(admin, core):
    now = datetime.now(UTC).isoformat()
    beat = {"pid": 1, "beat_at": now, "ml": True, "models_missing": [], "processed": 1234,
            "rss_mb": 411.6, "load_errors": {"age": "Modell kaputt"}}  # fmt: skip
    core.repos.app_settings.put(jobs.WORKER_KEY, beat, at=now)
    worker = admin.get(f"{BASE}/analysis").json()["worker"]
    assert worker["processed"] == 1234 and worker["rss_mb"] == 412
    assert worker["load_errors"] == {"age": "Modell kaputt"}

    # a stale beat: the process is gone, its numbers mean nothing any more
    old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    core.repos.app_settings.put(jobs.WORKER_KEY, {**beat, "beat_at": old}, at=old)
    worker = admin.get(f"{BASE}/analysis").json()["worker"]
    assert worker["last_beat_at"] == old
    assert worker["processed"] is None and worker["rss_mb"] is None
    assert worker["load_errors"] == {}


def test_toggles(admin, core):
    r = admin.put(f"{BASE}/analysis/analyzers", json={"disabled": ["gestures"]}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    analyzers = {a["name"]: a for a in r.json()["analyzers"]}
    assert analyzers["gestures"]["enabled"] is False
    assert analyzers["age"]["enabled"] is True  # the set is complete: age is on now
    assert core.repos.app_settings.get(jobs.ANALYZERS_KEY)["disabled"] == ["gestures"]
    entry = core.repos.audit.list(1)[0]
    assert entry.action == "wall.analyzers" and entry.details == {"disabled": ["gestures"]}
    # basic cannot be switched off
    r = admin.put(f"{BASE}/analysis/analyzers", json={"disabled": ["basic"]}, headers=ORIGIN)
    assert {a["name"]: a["enabled"] for a in r.json()["analyzers"]}["basic"] is True


def test_unknown_analyzer(admin):
    r = admin.put(f"{BASE}/analysis/analyzers", json={"disabled": ["horoscope"]}, headers=ORIGIN)
    assert r.status_code == 400
    assert r.json() == {"error": "unknown_analyzer", "message": "Unbekannte Analyse: horoscope."}


def test_mutations_need_the_origin(admin):
    r = admin.put(f"{BASE}/analysis/analyzers", json={"disabled": []})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"


def test_no_reanalysis(admin, guest):
    """Frozen analyses (PLAN-NIGHT N3): the re-run routes are gone."""
    public_id = upload(guest())
    assert admin.post(f"{BASE}/analysis/rerun", json={"scope": "all"}, headers=ORIGIN
                      ).status_code in (404, 405)  # fmt: skip
    assert admin.post(f"{BASE}/photos/{public_id}/analysis", headers=ORIGIN
                      ).status_code in (404, 405)  # fmt: skip


def test_photo_analysis(admin, guest, core):
    public_id = upload(guest())
    r = admin.get(f"{BASE}/photos/{public_id}/analysis")
    assert r.status_code == 200
    body = r.json()
    assert {k: body[k] for k in ("photo_id", "state", "attempts", "error", "finished_at",
                                 "versions", "facts", "boxes", "details", "objects")} == {
        "photo_id": public_id, "state": "pending", "attempts": 0, "error": None,
        "finished_at": None, "versions": {}, "facts": {}, "boxes": [], "details": [],
        "objects": [],
    }  # fmt: skip
    assert body["opt_out"] == {"analysis": False, "external_ai": False}
    pid = internal(core, public_id)
    jobs.claim(core.db)
    box = {"kind": "face", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "label": "fröhlich 82 %",
           "score": 0.82}  # fmt: skip
    data = {"boxes": [box], "details": [{"label": "Gesichter", "value": "1 (Schätzung)"}]}
    jobs.finish(core.db, pid, facts={"faces": 1, "happy_max": 0.82}, data=data,
                versions={"faces": "1"})  # fmt: skip
    body = admin.get(f"{BASE}/photos/{public_id}/analysis").json()
    assert body["state"] == "done" and body["attempts"] == 1 and body["finished_at"]
    assert body["facts"] == {"faces": 1.0, "happy_max": 0.82}
    assert body["boxes"] == [box] and body["details"] == data["details"]
    assert body["versions"] == {"faces": "1"}


def test_unknown_or_deleted_photo(admin, guest, core):
    assert admin.get(f"{BASE}/photos/nope/analysis").json()["error"] == "not_found"
    public_id = upload(guest())
    assert admin.delete(f"/api/admin/photos/{public_id}", headers=ORIGIN).status_code == 200
    assert admin.get(f"{BASE}/photos/{public_id}/analysis").status_code == 404


def test_service_port(core, guest):
    """What the wall calls: summaries, changes_since (the categories come from
    the engine over the database: test_enrich_engine.py, test_wall_categories.py)."""
    svc = EnrichmentService.of(core)
    assert EnrichmentService.of(core) is svc
    g = guest()
    a, b = internal(core, upload(g)), internal(core, upload(g))
    rev, ids = svc.changes_since(0)
    assert (rev, ids) == (0, [])
    jobs.claim(core.db)  # b
    jobs.finish(core.db, b, facts={"people": 4, "smiles": 2, "faces": 4}, data={}, versions={})
    rev, ids = svc.changes_since(0)
    assert ids == [b]  # one row per photo, at its latest rev
    assert svc.changes_since(rev) == (rev, [])
    summaries = svc.summaries([a, b, 999])
    assert summaries[a].state == "pending" and summaries[a].facts == {}
    assert summaries[b].state == "done" and summaries[b].facts["people"] == 4.0
    assert 999 not in summaries


def test_an_analyzer_that_cannot_run_switches_both_ways(admin):
    """No models here: `faces` is unavailable, yet the switch is the stored wish
    in both directions (the UI keeps it usable and shows the reason)."""
    for enabled in (False, True, False, True):
        r = admin.put(f"{BASE}/analysis/analyzers/faces", json={"enabled": enabled},
                      headers=ORIGIN)  # fmt: skip
        assert r.status_code == 200, r.text
        faces = {a["name"]: a for a in r.json()["analyzers"]}["faces"]
        assert faces["enabled"] is enabled and faces["available"] is False
        assert "Modelle herunterladen" in faces["reason"]


# ------------------------------------------------------- Modelle herunterladen


def beat(core, *, ml: bool, missing: list[str] | None = None) -> None:
    now = datetime.now(UTC).isoformat()
    value = {"pid": 1, "beat_at": now, "ml": ml, "models_missing": missing or []}
    core.repos.app_settings.put(jobs.WORKER_KEY, value, at=now)


@pytest.fixture
def registry(tmp_path, monkeypatch) -> list[models.ModelFile]:
    """The real registry's names and files, served from local file URLs."""
    fake: list[models.ModelFile] = []
    for m in models.REGISTRY:
        content = m.name.encode() * 50
        src = tmp_path / "upstream" / m.file
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(content)
        fake.append(models.ModelFile(m.name, m.file, src.as_uri(),
                                     hashlib.sha256(content).hexdigest(), len(content), m.license,
                                     m.optional))  # fmt: skip
    monkeypatch.setattr(models, "REGISTRY", tuple(fake))
    monkeypatch.setattr(models, "BY_NAME", {m.name: m for m in fake})
    monkeypatch.setattr(models, "BAKED_DIR", tmp_path / "no-baked-models")
    return fake


def test_models_status_without_the_ml_packages(admin, core, registry):
    beat(core, ml=False)
    body = admin.get(f"{BASE}/analysis").json()
    m = body["models"]
    assert m["ml"] is False and m["can_download"] is False
    # the standard set; FairFace only once `age` is switched on
    assert m["missing"] == ["yunet", "face_landmarker", "ferplus", "gesture_recognizer",
                            "efficientdet_lite2", "clip_vision"]  # fmt: skip
    assert m["dest"] == str(core.settings.data_dir / "wall" / "models")
    r = admin.post(f"{BASE}/analysis/models/download", headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"] == "ml_missing"
    assert "VB_ML=1" in r.json()["message"]
    assert not (core.settings.data_dir / "wall" / "models").exists()


def test_download_needs_the_origin(admin, core, registry):
    beat(core, ml=True)
    r = admin.post(f"{BASE}/analysis/models/download")
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"


def test_download_the_missing_models(admin, core, registry, monkeypatch):
    beat(core, ml=True, missing=[m.name for m in registry])
    monkeypatch.setattr(downloads, "_free_bytes", lambda _p: 1 << 40)  # VB_MIN_FREE_MB is 2 GB
    started: list[downloads.Downloader] = []
    real_start = downloads.Downloader.start

    def start_inline(self, wanted, **kw):  # run it in the request (deterministic)
        started.append(self)
        return real_start(self, wanted, **{**kw, "wait": True})

    monkeypatch.setattr(downloads.Downloader, "start", start_inline)
    m = admin.get(f"{BASE}/analysis").json()["models"]
    assert m["can_download"] is True and len(m["missing"]) == 6
    assert m["download"]["state"] == "idle"

    # the client sends nothing: the server picks the files and their URLs
    r = admin.post(f"{BASE}/analysis/models/download", headers=ORIGIN)
    assert r.status_code == 200, r.text
    m = r.json()["models"]
    assert m["download"]["state"] == "done", m
    assert m["missing"] == [] and m["can_download"] is False
    assert m["download"]["done_bytes"] == m["download"]["total_bytes"] > 0
    dest = Path(m["dest"])
    assert sorted(p.name for p in dest.iterdir()) == sorted(
        x.file for x in registry if not x.optional
    )
    entry = core.repos.audit.list(1)[0]
    assert entry.action == "wall.models.download" and len(entry.details["models"]) == 6

    # idempotent: nothing missing, nothing happens
    r = admin.post(f"{BASE}/analysis/models/download", headers=ORIGIN)
    assert r.status_code == 200 and len(started) == 1

    # switching FairFace on makes its model needed: the button comes back for it
    admin.put(f"{BASE}/analysis/analyzers/age", json={"enabled": True}, headers=ORIGIN)
    m = admin.get(f"{BASE}/analysis").json()["models"]
    assert m["missing"] == ["fairface_age"] and m["can_download"] is True
    r = admin.post(f"{BASE}/analysis/models/download", headers=ORIGIN)
    assert r.json()["models"]["missing"] == []
    assert (dest / "fairface_age_model_int8.onnx").is_file()
