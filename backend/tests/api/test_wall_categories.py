"""The wall's rule-based categories (PLAN-NIGHT §4.3): CRUD, order, presets,
preview, audit, the screen's categories with verdicts, opt-outs, seeding
from the old config, and the hub's `categories.changed` after an LLM poll."""

from __future__ import annotations

from typing import Any

import pytest

from virtubooth.extensions.wall import make_extension
from virtubooth.extensions.wall.enrich import presets
from virtubooth.extensions.wall.hub import WallHub

from ..conftest import ORIGIN
from .wall_support import (
    FakeEnrichment,
    age_photos,
    audit_actions,
    internal_id,
    upload,
    user_of,
    with_wall_page,
)

BASE = "/api/x/wall/admin/categories"
PRESET_IDS = [pid for pid, _, _ in presets.PRESETS]


@pytest.fixture
def fake():
    return FakeEnrichment()


@pytest.fixture
def extensions(demo_extension, fake):
    return [demo_extension, make_extension(enrichment=fake)]


@pytest.fixture
def web_dir(web_dir):
    return with_wall_page(web_dir)


def spec(**changes: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "emoji": "🎩", "title": "Hutträger", "line": "Die meisten Hüte",
        "where": [{"value": "objects", "op": "contains", "operand": "hat"}],
        "select": {"by": "objects.count:hat", "order": "top", "count": 2},
        "label": {"style": "count", "one": "Hut", "many": "Hüte"},
    }  # fmt: skip
    out.update(changes)
    return out


def facts(core, public_id: str, **values: float) -> int:
    pid = internal_id(core, public_id)
    with core.db.tx() as c:
        c.execute(
            "INSERT OR IGNORE INTO wall_analysis (photo_id, state, data, rev) VALUES "
            "(?, 'done', '{}', (SELECT COALESCE(MAX(rev), 0) + 1 FROM wall_analysis))",
            (pid,),
        )
        c.executemany(
            "INSERT INTO wall_facts (photo_id, key, value) VALUES (?,?,?)",
            [(pid, k, float(v)) for k, v in values.items()],
        )
    return pid


def test_admin_only(client):
    for method, path in [("GET", BASE), ("POST", BASE), ("PUT", f"{BASE}/order"),
                         ("PUT", f"{BASE}/x"), ("DELETE", f"{BASE}/x"),
                         ("POST", f"{BASE}/restore-presets"), ("POST", f"{BASE}/preview"),
                         ("GET", "/api/x/wall/admin/values")]:  # fmt: skip
        r = client.request(method, path, json={}, headers=ORIGIN)
        assert r.status_code == 401, path


def test_presets_are_seeded_once(admin, core):
    body = admin.get(BASE).json()["categories"]
    assert [c["id"] for c in body] == PRESET_IDS
    assert [c["position"] for c in body] == list(range(20))
    volles = body[0]
    assert volles["preset"] == "volles_haus" and volles["enabled"] is True
    assert volles["spec"]["select"]["by"] == "people" and volles["winners"] == []
    assert volles["verdict"] is None
    cool = body[-1]
    assert cool["enabled"] is False and cool["available"] is False
    assert cool["spec"]["verdict"]["prompt"].startswith("Werte das coolste Objekt")
    assert core.repos.app_settings.get(presets.SEEDED_KEY)["from_disabled"] == []
    # deleted presets stay deleted (seeding happens once)
    assert admin.delete(f"{BASE}/rock", headers=ORIGIN).json() == {"ok": True}
    assert "rock" not in [c["id"] for c in admin.get(BASE).json()["categories"]]


def test_crud_order_restore_and_audit(admin, core):
    r = admin.post(BASE, json={"id": "hutparty", "spec": spec()}, headers=ORIGIN)
    assert r.status_code == 201, r.text
    item = r.json()
    assert (item["id"], item["enabled"], item["preset"], item["position"]) == (
        "hutparty", True, None, 20,
    )  # fmt: skip
    assert item["spec"]["select"] == {"by": "objects.count:hat", "order": "top", "count": 2,
                                      "then_by": [], "one_per_guest": True}  # fmt: skip
    r = admin.post(BASE, json={"id": "hutparty", "spec": spec()}, headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"] == "category_exists"
    # change: spec and switch
    r = admin.put(f"{BASE}/hutparty", json={"spec": spec(title="Hüte!"), "enabled": False},
                  headers=ORIGIN)  # fmt: skip
    assert r.status_code == 200 and r.json()["spec"]["title"] == "Hüte!"
    assert r.json()["enabled"] is False
    # presets can be changed too
    r = admin.put(f"{BASE}/prost", json={"spec": presets.BY_ID["prost"][0], "enabled": False},
                  headers=ORIGIN)  # fmt: skip
    assert r.status_code == 200 and r.json()["preset"] == "prost"
    # order
    r = admin.put(f"{BASE}/order", json={"ids": ["hutparty", "prost"]}, headers=ORIGIN)
    ids = [c["id"] for c in r.json()["categories"]]
    assert ids[:3] == ["hutparty", "prost", "volles_haus"] and len(ids) == 21
    r = admin.put(f"{BASE}/order", json={"ids": ["nope"]}, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["error"] == "invalid_category"
    # delete, restore the presets
    assert admin.delete(f"{BASE}/prost", headers=ORIGIN).status_code == 200
    assert admin.delete(f"{BASE}/hutparty", headers=ORIGIN).status_code == 200
    assert admin.delete(f"{BASE}/hutparty", headers=ORIGIN).status_code == 404
    r = admin.post(f"{BASE}/restore-presets", headers=ORIGIN)
    assert r.json() == {"added": ["prost"]}
    assert admin.post(f"{BASE}/restore-presets", headers=ORIGIN).json() == {"added": []}
    assert [c["id"] for c in admin.get(BASE).json()["categories"]][-1] == "prost"
    actions = [(a, d) for a, _, d in audit_actions(core) if a == "wall.category"]
    assert [d["action"] for _, d in reversed(actions)] == [
        "create", "update", "update", "order", "delete", "delete", "restore",
    ]  # fmt: skip
    assert actions[-1][1] == {"id": "hutparty", "action": "create"}


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"id": "Bad Id", "spec": spec()}, "Ungültige Kategorie: Kennung."),
        ({"id": "order", "spec": spec()}, "Ungültige Kategorie: Kennung."),
        ({"id": "ok_id", "spec": spec(title="")}, "Ungültige Kategorie: Titel."),
        ({"id": "ok_id", "spec": spec(where=[{"value": "people", "op": "gte",
                                              "operand": "x"}])},
         "Ungültige Kategorie: Bedingung 1: Vergleichswert."),
        ({"id": "ok_id", "spec": spec(select={"by": "people", "count": 11})},
         "Ungültige Kategorie: Anzahl."),
        ({"id": "ok_id", "spec": "nope"}, "Ungültige Kategorie: Kategorie."),
        ({"id": "ok_id", "spec": spec(), "enabled": "ja"}, "Ungültige Kategorie: Eingeschaltet."),
    ],
)  # fmt: skip
def test_invalid_input_is_a_400_naming_the_field(admin, body, message):
    r = admin.post(BASE, json=body, headers=ORIGIN)
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_category", "message": message}


def test_put_errors(admin):
    r = admin.put(f"{BASE}/gibts_nicht", json={"spec": spec(), "enabled": True}, headers=ORIGIN)
    assert r.status_code == 404
    r = admin.put(f"{BASE}/prost", json={"spec": spec(emoji="no"), "enabled": True},
                  headers=ORIGIN)  # fmt: skip
    assert r.json()["message"] == "Ungültige Kategorie: Emoji."


def test_winners_preview_and_the_screen(admin, guest, core):
    g1, g2, g3 = guest(), guest(), guest()
    a, b, c = upload(g1), upload(g2), upload(g3)
    a2 = upload(g1)
    age_photos(core)
    facts(core, a, people=4)
    facts(core, a2, people=6)
    facts(core, b, people=5)
    facts(core, c, people=3, colorfulness=80)
    body = {x["id"]: x for x in admin.get(BASE).json()["categories"]}
    winners = body["volles_haus"]["winners"]
    assert [(w["photo_id"], w["value"], w["label"]) for w in winners] == [
        (a2, 6.0, "6 Personen"), (b, 5.0, "5 Personen"), (c, 3.0, "3 Personen"),
    ]  # fmt: skip
    assert winners[0]["thumb_url"] == f"/media/{a2}?thumb=1" and winners[0]["object_idx"] is None
    # preview: nothing stored
    r = admin.post(f"{BASE}/preview", json={"spec": spec(
        where=[{"value": "people", "op": "between", "operand": [4, 5]}],
        select={"by": "people", "order": "bottom", "count": 10, "one_per_guest": False},
        label={"style": "fixed", "one": "mittendrin"})}, headers=ORIGIN)  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json() == {
        "winners": [
            {"photo_id": a, "thumb_url": f"/media/{a}?thumb=1", "value": 4.0,
             "label": "mittendrin", "object_idx": None},
            {"photo_id": b, "thumb_url": f"/media/{b}?thumb=1", "value": 5.0,
             "label": "mittendrin", "object_idx": None},
        ],
        "matched": 2, "reason": None,
    }  # fmt: skip
    assert len(admin.get(BASE).json()["categories"]) == 20
    # the screen: enabled categories with winners, in order, up to `count`
    cats = admin.get("/livewall/api/categories").json()["categories"]
    assert [x["id"] for x in cats] == ["volles_haus", "farbexplosion", "eroeffnung"]
    assert [w["photo"]["id"] for w in cats[0]["winners"]] == [a2, b, c]
    assert cats[0]["verdict"] is None and cats[2]["winners"][0]["label"].startswith("um ")
    # the analysis opt-out (live) takes all of a guest's photos out
    with core.db.tx() as tx:
        tx.execute("UPDATE users SET analysis_opt_out=1 WHERE id=?", (user_of(core, g1).id,))
    cats = admin.get("/livewall/api/categories").json()["categories"]
    assert [w["photo"]["id"] for w in cats[0]["winners"]] == [b, c]
    eroeffnung = next(x for x in cats if x["id"] == "eroeffnung")
    assert eroeffnung["winners"][0]["photo"]["id"] != a


def test_the_verdict_reaches_the_screen(admin, guest, core):
    g = guest()
    pid_pub = upload(g)
    age_photos(core)
    pid = facts(core, pid_pub, people=1)
    with core.db.tx() as c:
        c.execute("INSERT INTO photo_objects VALUES (?, 0, 'hat', 'Hut', 0.9, NULL, NULL, NULL, "
                  "NULL, 'local', 'm@1', 'now')", (pid,))  # fmt: skip
        c.execute("INSERT INTO photo_detection_runs VALUES (?, 'local', 'done', 'm@1', NULL, 1, "
                  "'now')", (pid,))  # fmt: skip
        c.execute("INSERT INTO llm_properties (id, name, prompt, created_at) "
                  "VALUES (1, 'coolness', 'p', 'now')")  # fmt: skip
        c.execute("INSERT INTO llm_polls (id, started_at, state) VALUES (1, 'now', 'done')")
        c.execute("INSERT INTO property_scores VALUES (1, ?, '[0.8]', 1, 'now')", (pid,))
        c.execute("INSERT INTO wall_category_verdicts VALUES ('coolstes_objekt', "
                  "'Der Hut von Otter 3!', '🎩', ?, 0, 1, 'now')", (pid,))  # fmt: skip
    item = next(x for x in admin.get(BASE).json()["categories"] if x["id"] == "coolstes_objekt")
    assert item["available"] is True
    assert item["verdict"] == {"text": "Der Hut von Otter 3!", "emoji": "🎩", "photo_id": pid_pub}
    assert [(w["photo_id"], w["label"], w["object_idx"]) for w in item["winners"]] == [
        (pid_pub, "Hut", 0),
    ]  # fmt: skip
    r = admin.put(f"{BASE}/coolstes_objekt", json={"spec": item["spec"], "enabled": True},
                  headers=ORIGIN)  # fmt: skip
    assert r.status_code == 200
    cat = next(x for x in admin.get("/livewall/api/categories").json()["categories"]
               if x["id"] == "coolstes_objekt")  # fmt: skip
    assert cat["verdict"] == {"text": "Der Hut von Otter 3!", "emoji": "🎩", "photo_id": pid_pub}
    assert cat["winners"][0]["label"] == "Hut" and cat["winners"][0]["object_idx"] == 0
    # deleting the category drops its verdict
    admin.delete(f"{BASE}/coolstes_objekt", headers=ORIGIN)
    assert core.db.one("SELECT COUNT(*) FROM wall_category_verdicts")[0] == 0


def test_seeding_takes_over_the_old_disabled_list(settings, demo_extension):
    from fastapi.testclient import TestClient

    from virtubooth.app import create_app
    from virtubooth.db.database import Database
    from virtubooth.repositories.container import Repositories

    from ..conftest import ADMIN_PASSWORD, BASE_URL

    db = Database(settings.data_dir / "virtubooth.db")
    Repositories.create(db, settings.data_dir).app_settings.put(
        "x.wall.config", {"categories": {"per_category_s": 12, "disabled": ["prost", "rock"]}},
        at="2026-10-14T20:00:00.000+00:00",
    )  # fmt: skip
    db.close()
    app = create_app(settings, extensions=[demo_extension, make_extension(FakeEnrichment())])
    try:
        with TestClient(app, base_url=BASE_URL, follow_redirects=False) as admin:
            admin.post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=ORIGIN)
            cats = {c["id"]: c["enabled"] for c in admin.get(BASE).json()["categories"]}
            assert cats["prost"] is False and cats["rock"] is False and cats["peace"] is True
            seeded = app.state.core.repos.app_settings.get(presets.SEEDED_KEY)
            assert seeded["from_disabled"] == ["prost", "rock"]
    finally:
        app.state.core.db.close()


def test_values_catalogue(admin, guest, core):
    g = guest()
    pid = facts(core, upload(g), people=1)
    with core.db.tx() as c:
        c.execute("INSERT INTO photo_objects VALUES (?, 0, 'hat', 'Hut', 0.9, NULL, NULL, NULL, "
                  "NULL, 'local', 'm@1', 'now')", (pid,))  # fmt: skip
        c.execute("INSERT INTO llm_properties (name, prompt, created_at, archived_at) "
                  "VALUES ('lustigkeit', 'p', 'now', 'now')")  # fmt: skip
    body = admin.get("/api/x/wall/admin/values").json()
    values = {v["key"]: v for v in body["values"]}
    assert values["people"]["title"] == "Personen" and values["people"]["kind"] == "count"
    assert values["people"]["needs"] == ["objects", "faces"] and values["people"]["available"]
    assert values["objects"]["kind"] == "labels"
    assert values["photo.created_at"]["kind"] == "time"
    assert values["prop.lustigkeit.max"]["archived"] is True
    assert values["prop.lustigkeit.count"]["kind"] == "count"
    assert values["age_spread"]["available"] is False  # FairFace off in the fake
    assert body["labels"] == [{"label": "hat", "label_de": "Hut", "count": 1}]


def test_the_hub_announces_a_finished_llm_poll(core, fake):
    hub = WallHub(core, fake)
    hub._catch_up()
    assert hub._poll_once() is False
    with core.db.tx() as c:
        c.execute("INSERT INTO llm_polls (id, started_at, state) VALUES (1, 'now', 'running')")
    assert hub._poll_once() is False
    with core.db.tx() as c:
        c.execute("UPDATE llm_polls SET state='done' WHERE id=1")
    assert hub._poll_once() is True
    assert hub._poll_once() is False
