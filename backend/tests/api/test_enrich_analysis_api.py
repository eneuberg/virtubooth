"""The analysis admin API (PLAN §4.4), mounted like WINT will: the enrich
router under the wall extension's prefix `/api/x/wall`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from virtubooth.extensions.wall.enrich import admin_api, jobs
from virtubooth.extensions.wall.enrich.service import EnrichmentService, PhotoFilter

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
        ("put", f"{BASE}/analysis/analyzers"),
        ("post", f"{BASE}/analysis/rerun"),
        ("get", f"{BASE}/photos/x/analysis"),
        ("post", f"{BASE}/photos/x/analysis"),
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
    assert analyzers["basic"] == {
        "name": "basic", "title": "Bildwerte", "kind": "basic", "version": "1", "enabled": True,
        "available": True, "reason": None,
        "facts": ["brightness", "colorfulness", "sharpness"],
    }  # fmt: skip
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


def test_rerun(admin, guest, core):
    g = guest()
    a, b = upload(g), upload(g)
    for _ in range(2):
        jobs.claim(core.db)
    jobs.finish(core.db, internal(core, b), facts={"faces": 1}, data={}, versions={})
    with core.db.tx() as c:
        c.execute("UPDATE wall_analysis SET state='failed', attempts=2 WHERE photo_id=?",
                  (internal(core, a),))  # fmt: skip
    r = admin.post(f"{BASE}/analysis/rerun", json={"scope": "failed"}, headers=ORIGIN)
    assert r.json() == {"queued": 1}
    assert admin.post(f"{BASE}/analysis/rerun", json={"scope": "all"}, headers=ORIGIN).json() == {
        "queued": 1
    }
    r = admin.post(f"{BASE}/analysis/rerun", json={"scope": "some"}, headers=ORIGIN)
    assert r.status_code == 422


def test_photo_analysis(admin, guest, core):
    public_id = upload(guest())
    r = admin.get(f"{BASE}/photos/{public_id}/analysis")
    assert r.status_code == 200
    assert r.json() == {
        "photo_id": public_id, "state": "pending", "attempts": 0, "error": None,
        "finished_at": None, "versions": {}, "facts": {}, "boxes": [], "details": [],
    }  # fmt: skip
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
    # „Neu analysieren“
    r = admin.post(f"{BASE}/photos/{public_id}/analysis", headers=ORIGIN)
    assert r.status_code == 200
    assert r.json()["state"] == "pending" and r.json()["attempts"] == 0
    assert jobs.get(core.db, pid).state == "pending"


def test_unknown_or_deleted_photo(admin, guest, core):
    assert admin.get(f"{BASE}/photos/nope/analysis").json()["error"] == "not_found"
    public_id = upload(guest())
    assert admin.delete(f"/api/admin/photos/{public_id}", headers=ORIGIN).status_code == 200
    assert admin.get(f"{BASE}/photos/{public_id}/analysis").status_code == 404
    assert admin.post(f"{BASE}/photos/{public_id}/analysis", headers=ORIGIN).status_code == 404


def test_service_port(core, guest):
    """What the wall (W1) calls: summaries, changes_since, catalogue, winners."""
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
    assert len(svc.catalogue()) == 19
    out = svc.winners(["volles_haus", "grinsekatzen", "prost"],
                      PhotoFilter(sources=None, not_after="9999"))  # fmt: skip
    assert [(w.category.id, w.winners) for w in out] == [
        ("volles_haus", [(b, 4.0)]), ("grinsekatzen", [(b, 2.0)]), ("prost", []),
    ]  # fmt: skip
