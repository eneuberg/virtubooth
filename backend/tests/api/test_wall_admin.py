"""The wall's admin API (PLAN-WALL §4.3) and the categories on both sides,
with a fake photo analysis; and the wall without any analysis."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from virtubooth.app import create_app
from virtubooth.extensions.wall import enrichment as enrichment_module
from virtubooth.extensions.wall import make_extension
from virtubooth.extensions.wall.enrichment import (
    ANALYZERS_KEY,
    SERVICE_MODULE,
    NullEnrichment,
    load_enrichment,
)

from ..conftest import ADMIN_PASSWORD, BASE_URL, ORIGIN
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


def test_get_config(admin, core):
    body = admin.get("/api/x/wall/admin/config").json()
    assert body["config"] == body["defaults"]
    assert body["defaults"]["delay_s"] == 20 and body["defaults"]["rev"] == 0
    assert body["password"] == {"set": False, "changed_at": None}
    assert body["wall_path"] == "/livewall"
    assert body["sources"] == [{"id": "demo", "title": "Demo", "emoji": "🧪"}]
    assert body["open_walls"] == 0 and body["event_name"] == "Testparty"
    cats = {c["id"]: c for c in body["categories"]}
    assert list(cats) == ["volles_haus", "generationen", "farbexplosion"]
    assert cats["volles_haus"] == {
        "id": "volles_haus",
        "emoji": "👥",
        "title": "Volles Haus",
        "line": "Die meisten Leute",
        "enabled": True,
        "available": True,
        "reason": None,
    }
    # FairFace ("age") is off until the analysis admin switches it on
    assert cats["generationen"]["available"] is False
    assert cats["generationen"]["reason"] == "Braucht die Analyse „age“."
    core.repos.app_settings.put(ANALYZERS_KEY, {"disabled": ["objects"]}, at="x")
    cats = {c["id"]: c for c in admin.get("/api/x/wall/admin/config").json()["categories"]}
    assert cats["generationen"]["available"] is True
    assert cats["volles_haus"]["reason"] == "Braucht die Analyse „objects“."


def test_put_config(admin, core):
    config = admin.get("/api/x/wall/admin/config").json()["config"]
    config["look"]["primary"] = "#00FF00"
    config["categories"]["disabled"] = ["generationen"]
    config |= {"rev": 41, "by": "someone", "updated_at": "never", "delay_s": 5}
    r = admin.put("/api/x/wall/admin/config", json=config, headers=ORIGIN)
    assert r.status_code == 200, r.text
    saved = r.json()["config"]
    assert saved["rev"] == 1 and saved["by"].startswith("admin:")
    assert saved["updated_at"] != "never" and saved["look"]["primary"] == "#00ff00"
    assert saved["delay_s"] == 5
    cats = {c["id"]: c["enabled"] for c in r.json()["categories"]}
    assert cats == {"volles_haus": True, "generationen": False, "farbexplosion": True}
    assert admin.get("/api/x/wall/admin/config").json()["config"] == saved
    action, _, details = audit_actions(core)[0]
    assert action == "wall.config"
    assert details == {"changed": ["categories", "delay_s", "look"]}
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


def test_categories(admin, guest, core, fake, make_client):
    g = guest()
    a, b, c, d, hidden = (upload(g) for _ in range(5))
    age_photos(core)
    fresh = upload(g)  # still within the delay
    ids = {p: internal_id(core, p) for p in (a, b, c, d, hidden, fresh)}
    admin.post(f"/api/admin/photos/{hidden}/hide", headers=ORIGIN)
    fake.values = {
        "volles_haus": {ids[a]: 3, ids[b]: 7, ids[c]: 5, ids[d]: 4, ids[hidden]: 9, ids[fresh]: 8},
        "generationen": {ids[a]: 2},
        "farbexplosion": {ids[hidden]: 80},
    }
    # the screen: enabled categories with winners only, at most 3 each
    put_config(admin, categories={"per_category_s": 10, "disabled": ["generationen"]})
    r = admin.get("/livewall/api/categories")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    (cat,) = r.json()["categories"]
    assert (cat["id"], cat["emoji"], cat["title"], cat["line"]) == (
        "volles_haus",
        "👥",
        "Volles Haus",
        "Die meisten Leute",
    )
    assert [(w["photo"]["id"], w["value"], w["label"]) for w in cat["winners"]] == [
        (b, 7, "7 Stück"),
        (c, 5, "5 Stück"),
        (d, 4, "4 Stück"),
    ]
    assert cat["winners"][0]["photo"]["urls"]["s"] == f"/livewall/media/{b}?s=s"
    assert fake.asked[-1] == ["volles_haus", "farbexplosion"]
    flt = fake.filters[-1]
    assert flt.sources == ("demo",) and flt.not_after < core.repos.photos.get(fresh).created_at

    # the admin: every category, disabled ones too
    body = admin.get("/api/x/wall/admin/categories").json()["categories"]
    assert [(x["id"], x["enabled"]) for x in body] == [
        ("volles_haus", True),
        ("generationen", False),
        ("farbexplosion", True),
    ]
    assert body[1]["winners"] == [
        {"photo_id": a, "thumb_url": f"/media/{a}?thumb=1", "value": 2, "label": "2 Stück"}
    ]
    assert [w["photo_id"] for w in body[0]["winners"]] == [b, c, d]
    assert body[2]["winners"] == []


def test_without_analysis(settings, demo_extension, monkeypatch):
    """No `enrich` package: categories stay empty, photos say analysis "off"."""

    def missing(name, *args, **kwargs):
        if name == SERVICE_MODULE:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return importlib.import_module(name, *args, **kwargs)

    monkeypatch.setattr(enrichment_module.importlib, "import_module", missing)
    app = create_app(settings, extensions=[demo_extension, make_extension()])
    try:
        with TestClient(app, base_url=BASE_URL) as admin:
            admin.post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=ORIGIN)
            body = admin.get("/api/x/wall/admin/config").json()
            assert body["categories"] == []
            assert admin.get("/api/x/wall/admin/categories").json() == {"categories": []}
            assert admin.get("/livewall/api/categories").json() == {"categories": []}
            assert admin.get("/livewall/api/feed").json()["photos"] == []
    finally:
        app.state.core.db.close()


def test_loader_falls_back_only_for_the_missing_package(core, monkeypatch):
    def fail(name):
        raise ModuleNotFoundError("No module named 'numpy'", name="numpy")

    monkeypatch.setattr(enrichment_module.importlib, "import_module", fail)
    with pytest.raises(ModuleNotFoundError):
        load_enrichment(core)
    for name in (SERVICE_MODULE, "virtubooth.extensions.wall.enrich"):

        def gone(_name, missing=name):
            raise ModuleNotFoundError(f"No module named {missing!r}", name=missing)

        monkeypatch.setattr(enrichment_module.importlib, "import_module", gone)
        assert isinstance(load_enrichment(core), NullEnrichment)


def test_fake_analysis_runs_with_the_app(fake, client):
    assert fake.started == 1 and fake.stopped == 0
