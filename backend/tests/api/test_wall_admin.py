"""The wall's admin API (PLAN-WALL §4.3) with a fake photo analysis, and the
wall with the real analysis service. The categories' own API:
test_wall_categories.py."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from virtubooth.app import create_app
from virtubooth.extensions.wall import make_extension
from virtubooth.extensions.wall.enrich.presets import PRESETS
from virtubooth.extensions.wall.enrich.service import EnrichmentService
from virtubooth.extensions.wall.enrichment import load_enrichment

from ..conftest import ADMIN_PASSWORD, BASE_URL, ORIGIN, accept_consent, scan
from .wall_support import (
    FakeEnrichment,
    age_photos,
    audit_actions,
    internal_id,
    put_config,
    upload,
    with_wall_page,
)

ADMIN_ROUTES = [
    ("GET", "/api/x/wall/admin/config"),
    ("PUT", "/api/x/wall/admin/config"),
    ("PUT", "/api/x/wall/admin/password"),
    ("DELETE", "/api/x/wall/admin/password"),
    ("POST", "/api/x/wall/admin/logout"),
    ("GET", "/api/x/wall/admin/categories"),
]


@pytest.fixture
def fake():
    return FakeEnrichment()


@pytest.fixture
def extensions(demo_extension, fake):
    return [demo_extension, make_extension(enrichment=fake)]


@pytest.fixture
def web_dir(web_dir):
    return with_wall_page(web_dir)


def test_admin_only(client, admin):
    for method, path in ADMIN_ROUTES:
        r = client.request(method, path, json={"password": "geheim-123456"}, headers=ORIGIN)
        assert r.status_code == 401 and r.json()["error"] == "admin_required", path
    # CSRF: changes need a same-origin request, admin or not
    for method, path in ADMIN_ROUTES:
        if method == "GET":
            continue
        r = admin.request(method, path, json={"password": "geheim-123456"})
        assert r.status_code == 403 and r.json()["error"] == "bad_origin", path
        r = admin.request(method, path, json={}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 403, path


def test_get_config(admin, core, fake):
    body = admin.get("/api/x/wall/admin/config").json()
    assert body["config"] == body["defaults"]
    assert body["defaults"]["delay_s"] == 20 and body["defaults"]["rev"] == 0
    assert body["password"] == {"set": False, "changed_at": None}
    assert body["wall_path"] == "/livewall"
    assert body["sources"] == [{"id": "demo", "title": "Demo", "emoji": "🧪"}]
    assert body["open_walls"] == 0 and body["event_name"] == "Testparty"
    cats = {c["id"]: c for c in body["categories"]}
    assert list(cats) == [pid for pid, _, _ in PRESETS]
    assert cats["volles_haus"] == {
        "id": "volles_haus",
        "emoji": "👥",
        "title": "Volles Haus",
        "line": "Die meisten Leute auf einem Foto",
        "enabled": True,
        "available": True,
        "reason": None,
    }
    # the LLM preset is off and needs its property
    assert cats["coolstes_objekt"]["enabled"] is False
    assert cats["coolstes_objekt"]["reason"] == "Braucht die Eigenschaft „coolness“."
    fake.active = {"basic", "tags"}
    cats = {c["id"]: c for c in admin.get("/api/x/wall/admin/config").json()["categories"]}
    assert cats["hutparade"]["available"] is True
    assert cats["volles_haus"]["reason"] == "Braucht die Analyse „Objekte“."


def test_put_config(admin, core):
    config = admin.get("/api/x/wall/admin/config").json()["config"]
    config["look"]["primary"] = "#00FF00"
    config["categories"]["disabled"] = ["generationen"]  # an old client: ignored
    config |= {"rev": 41, "by": "someone", "updated_at": "never", "delay_s": 5}
    r = admin.put("/api/x/wall/admin/config", json=config, headers=ORIGIN)
    assert r.status_code == 200, r.text
    saved = r.json()["config"]
    assert saved["rev"] == 1 and saved["by"].startswith("admin:")
    assert saved["updated_at"] != "never" and saved["look"]["primary"] == "#00ff00"
    assert saved["delay_s"] == 5
    cats = {c["id"]: c["enabled"] for c in r.json()["categories"]}
    assert cats["generationen"] is True and saved["categories"]["disabled"] == []
    assert admin.get("/api/x/wall/admin/config").json()["config"] == saved
    action, _, details = audit_actions(core)[0]
    assert action == "wall.config"
    assert details == {"changed": ["delay_s", "look"]}
    assert put_config(admin, delay_s=6)["config"]["rev"] == 2


def test_put_config_errors(admin, core):
    config = admin.get("/api/x/wall/admin/config").json()["config"]
    r = admin.put("/api/x/wall/admin/config", json=config | {"sources": ["beer"]}, headers=ORIGIN)
    assert r.status_code == 400
    assert r.json() == {
        "error": "invalid_wall_config",
        "message": "Ungültige Einstellung: sources.",
    }
    config["spotlight"]["n"] = 0
    r = admin.put("/api/x/wall/admin/config", json=config, headers=ORIGIN)
    assert r.json()["message"] == "Ungültige Einstellung: spotlight.n."
    r = admin.put(
        "/api/x/wall/admin/config",
        content=b"{not json",
        headers=ORIGIN | {"Content-Type": "application/json"},
    )
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"
    assert admin.get("/api/x/wall/admin/config").json()["config"]["rev"] == 0
    assert not [a for a, _, _ in audit_actions(core) if a == "wall.config"]


def test_with_the_real_analysis(settings, demo_extension):
    """The app's own service: its catalogue, photos `pending` until the worker
    (off in tests) gets to them, the analysis admin routes under /api/x/wall."""
    app = create_app(settings, extensions=[demo_extension, make_extension()])
    try:
        with TestClient(app, base_url=BASE_URL, follow_redirects=False) as admin:
            core = app.state.core
            assert isinstance(load_enrichment(core), EnrichmentService)
            admin.post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=ORIGIN)
            body = admin.get("/api/x/wall/admin/config").json()
            cats = {c["id"]: c for c in body["categories"]}
            assert list(cats) == [pid for pid, _, _ in PRESETS]
            # without the ml extra only the basic image values run
            assert cats["farbexplosion"]["available"] is True
            assert cats["eroeffnung"]["available"] is True
            status = admin.get("/api/x/wall/admin/analysis").json()
            assert status["worker"]["state"] == "off"
            scan(admin)
            accept_consent(admin)
            pid = upload(admin)
            age_photos(core)
            (photo,) = admin.get("/livewall/api/feed").json()["photos"]
            assert photo["id"] == pid and photo["analysis"] == "pending" and photo["facts"] == {}
            r = admin.get(f"/api/x/wall/admin/photos/{pid}/analysis")
            assert r.status_code == 200 and r.json()["state"] == "pending"
    finally:
        app.state.core.db.close()


def test_fake_analysis_runs_with_the_app(fake, client):
    assert fake.started == 1 and fake.stopped == 0


def test_the_ml_pipeline_status_and_analyzer_settings(settings, demo_extension):
    """GET /analysis: queue, per-analyzer description, size, stats, settings;
    PUT /analysis/analyzers/{name}: on/off plus settings, audited."""
    app = create_app(settings, extensions=[demo_extension, make_extension()])
    try:
        with TestClient(app, base_url=BASE_URL, follow_redirects=False) as admin:
            core = app.state.core
            admin.post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=ORIGIN)
            core.repos.app_settings.put("x.wall.worker", {"stats": {"basic": {
                "processed": 4, "errors": 1, "avg_ms": 12.5, "last_ms": 10}}}, at="now")  # fmt: skip
            scan(admin)
            accept_consent(admin)
            upload(admin)
            status = admin.get("/api/x/wall/admin/analysis").json()
            assert status["queue"]["pending"] == 1 and status["queue"]["running"] == 0
            assert status["queue"]["oldest_pending_s"] >= 0
            by = {a["name"]: a for a in status["analyzers"]}
            assert by["basic"]["stats"] == {"processed": 4, "errors": 1, "avg_ms": 12.5,
                                            "last_ms": 10.0}  # fmt: skip
            assert by["faces"]["stats"]["processed"] == 0 and by["faces"]["size_mb"] == 4.0
            assert by["objects"]["description"] and by["objects"]["size_mb"] == 7.5
            assert by["objects"]["settings"] == {"score_min": 0.35, "max_objects": 50}
            assert [s["key"] for s in by["objects"]["settings_schema"]] == [
                "score_min", "max_objects",
            ]  # fmt: skip
            assert by["basic"]["settings"] is None and by["basic"]["settings_schema"] == []

            url = "/api/x/wall/admin/analysis/analyzers"
            r = admin.put(f"{url}/objects", json={"enabled": False,
                          "settings": {"score_min": 0.5}}, headers=ORIGIN)  # fmt: skip
            assert r.status_code == 200, r.text
            by = {a["name"]: a for a in r.json()["analyzers"]}
            assert by["objects"]["enabled"] is False
            assert by["objects"]["settings"] == {"score_min": 0.5, "max_objects": 50}
            for body, error in [
                ({"enabled": True, "settings": {"score_min": 2}}, "invalid_analyzer_settings"),
                ({"enabled": True, "settings": {"nope": 1}}, "invalid_analyzer_settings"),
                ({"enabled": True, "settings": {"max_objects": 2.5}}, "invalid_analyzer_settings"),
            ]:
                r = admin.put(f"{url}/objects", json=body, headers=ORIGIN)
                assert r.status_code == 400 and r.json()["error"] == error, body
            r = admin.put(f"{url}/basic", json={"enabled": False}, headers=ORIGIN)
            assert r.json()["error"] == "invalid_analyzer_settings"
            r = admin.put(f"{url}/gibts", json={"enabled": True}, headers=ORIGIN)
            assert r.status_code == 400 and r.json()["error"] == "unknown_analyzer"
            action, target, details = audit_actions(core)[0]
            assert (action, target) == ("wall.analyzers", "objects")
            assert details == {"enabled": False, "settings": {"score_min": 0.5}}
    finally:
        app.state.core.db.close()


def test_photo_analysis_shows_objects_runs_and_opt_outs(settings, demo_extension):
    app = create_app(settings, extensions=[demo_extension, make_extension()])
    try:
        with TestClient(app, base_url=BASE_URL, follow_redirects=False) as admin:
            core = app.state.core
            admin.post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=ORIGIN)
            scan(admin)
            accept_consent(admin)
            pub = upload(admin)
            pid = internal_id(core, pub)
            from virtubooth.extensions.wall.enrich import jobs, objects
            from virtubooth.extensions.wall.enrich.objects import DetectedObject

            jobs.claim(core.db)
            jobs.finish(core.db, pid, facts={"people": 1}, versions={"objects": "2"},
                        data={"boxes": [], "details": [], "durations_ms": {"objects": 81},
                              "opt_out": False},
                        objects_found=[DetectedObject("hat", "Hut", 0.9, (0.1, 0.2, 0.3, 0.4))],
                        objects_model="efficientdet_lite2@2")  # fmt: skip
            objects.record_run(core.db, pid, "claude", "failed", "claude-haiku-5-5", "timeout")
            # Mistral (another provider, earlier) found the hat too and a cap: linked + appended
            objects.append(core.db, pid, "mistral", "mistral-small", [
                DetectedObject("hats", "Hut", 0.6, (0.11, 0.2, 0.3, 0.4)),
                DetectedObject("cap", "Kappe", 0.5, None),
            ])  # fmt: skip
            with core.db.tx() as c:
                c.execute("INSERT INTO llm_properties (id, name, prompt, created_at) "
                          "VALUES (1, 'coolness', 'p', 'now')")  # fmt: skip
                c.execute("INSERT INTO property_scores VALUES (1, ?, '[0.7]', 1, 'now')", (pid,))
                c.execute("UPDATE users SET ai_opt_out=1")
            body = admin.get(f"/api/x/wall/admin/photos/{pub}/analysis").json()
            # the merged list (what the poll rates), and each source's own list
            assert body["objects"] == [
                {"idx": 0, "label": "hat", "label_de": "Hut", "score": 0.9,
                 "box": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}, "source": "local",
                 "model": "efficientdet_lite2@2", "sources": ["local", "mistral"]},
                {"idx": 1, "label": "cap", "label_de": "Kappe", "score": 0.5, "box": None,
                 "source": "mistral", "model": "mistral-small", "sources": ["mistral"]},
            ]  # fmt: skip
            assert body["objects_local"] == [
                {"pos": 0, "label": "hat", "label_de": "Hut", "score": 0.9,
                 "box": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}, "source": "local",
                 "model": "efficientdet_lite2@2", "merged_idx": 0},
            ]  # fmt: skip
            assert [(o["pos"], o["label"], o["source"], o["merged_idx"])
                    for o in body["objects_ai"]] == [(0, "hats", "mistral", 0),
                                                     (1, "cap", "mistral", 1)]  # fmt: skip
            assert body["runs"] == [
                {"source": "local", "state": "done", "model": "efficientdet_lite2@2", "error": None,
                 "image": None},
                {"source": "claude", "state": "failed", "model": "claude-haiku-5-5",
                 "error": "timeout", "image": None},
                {"source": "mistral", "state": "done", "model": "mistral-small", "error": None,
                 "image": None},
            ]  # fmt: skip
            assert body["opt_out"] == {"analysis": False, "external_ai": True}
            assert body["opt_out_at_analysis"] is False
            assert body["properties"] == [{"name": "coolness", "inactive": False, "scores": [0.7]}]
            assert body["durations_ms"] == {"objects": 81}
    finally:
        app.state.core.db.close()


def test_photo_analysis_summaries_for_the_live_screen(settings, demo_extension):
    """GET /admin/photos/analysis?ids=…: a batch of tiles' state, key facts, objects
    with score and frame, face and hand frames, and opt-outs (unknown ids left out); the poller announces new analyses
    to the admin stream as `photo.analyzed`."""
    app = create_app(settings, extensions=[demo_extension, make_extension()])
    try:
        with TestClient(app, base_url=BASE_URL, follow_redirects=False) as admin:
            core = app.state.core
            admin.post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=ORIGIN)
            scan(admin)
            accept_consent(admin)
            first, second = upload(admin), upload(admin)
            from virtubooth.extensions.wall.enrich import jobs
            from virtubooth.extensions.wall.enrich.objects import DetectedObject

            seen: list[tuple[str, dict]] = []
            core.bus.publish = lambda type_, data: seen.append((type_, data))  # type: ignore[method-assign]
            claimed = jobs.claim(core.db)
            assert claimed is not None
            pid = claimed.id
            done, waiting = (first, second) if pid == internal_id(core, first) else (second, first)
            frames = [
                {
                    "kind": "face",
                    "x": 0.123456,
                    "y": 0.2,
                    "w": 0.1,
                    "h": 0.15,
                    "label": "lächelt",
                    "score": 0.9,
                },
                {
                    "kind": "hand",
                    "x": 0.6,
                    "y": 0.5,
                    "w": 0.1,
                    "h": 0.1,
                    "label": "Daumen hoch",
                    "score": 0.8,
                },
                # persons and objects come from the object list, never twice
                {"kind": "person", "x": 0, "y": 0, "w": 1, "h": 1, "label": "Person", "score": 0.7},
                {"kind": "face", "x": "broken"},
            ]
            jobs.finish(core.db, pid, facts={"people": 3, "smiles": 2, "brightness": 0.4},
                        versions={"objects": "2"}, data={"boxes": frames, "details": []},
                        objects_found=[
                            DetectedObject("bottle", "Flasche", 0.9071, (0.1, 0.2, 0.30004, 0.4)),
                            DetectedObject("cake", "Kuchen", 0.5, None),
                        ],
                        objects_model="efficientdet_lite2@2")  # fmt: skip
            with core.db.tx() as c:
                c.execute("UPDATE users SET analysis_opt_out=1")

            r = admin.get("/api/x/wall/admin/photos/analysis",
                          params=[("ids", waiting), ("ids", "nope"), ("ids", done)])  # fmt: skip
            assert r.status_code == 200, r.text
            items = r.json()["items"]
            assert [i["photo_id"] for i in items] == [waiting, done]
            assert items[0]["state"] in {"pending", "running"} and items[0]["facts"] == {}
            assert items[1]["state"] == "done"
            # only the key values, not every raw fact
            assert items[1]["facts"] == {"people": 3.0, "smiles": 2.0}
            # objects with score and frame (3 places), faces and hands as frames
            assert items[1]["objects"] == [
                {"label": "bottle", "label_de": "Flasche", "source": "local", "sources": ["local"], "score": 0.91,
                 "box": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}},
                {"label": "cake", "label_de": "Kuchen", "source": "local", "sources": ["local"], "score": 0.5,
                 "box": None},
            ]  # fmt: skip
            assert items[1]["boxes"] == [
                {"kind": "face", "x": 0.123, "y": 0.2, "w": 0.1, "h": 0.15},
                {"kind": "hand", "x": 0.6, "y": 0.5, "w": 0.1, "h": 0.1},
            ]
            assert items[0]["objects"] == [] and items[0]["boxes"] == []
            assert items[1]["opt_out"] == {"analysis": True, "external_ai": False}
            assert items[1]["wins"] == []

            too_many = [("ids", f"x{i}") for i in range(101)]
            r = admin.get("/api/x/wall/admin/photos/analysis", params=too_many)
            assert r.status_code == 400

            # the poller (a fresh hub from rev 0) announces the finished analysis
            from virtubooth.extensions.wall.hub import WallHub

            WallHub(core, EnrichmentService.of(core))._poll_once()
            assert ("photo.analyzed", {"ids": [done]}) in seen
    finally:
        app.state.core.db.close()
