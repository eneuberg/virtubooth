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
        r = client.request(method, path, json={"password": "geheim-123"}, headers=ORIGIN)
        assert r.status_code == 401 and r.json()["error"] == "admin_required", path
    # CSRF: changes need a same-origin request, admin or not
    for method, path in ADMIN_ROUTES:
        if method == "GET":
            continue
        r = admin.request(method, path, json={"password": "geheim-123"})
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
    assert cats["generationen"] is True and "disabled" not in saved["categories"]
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
