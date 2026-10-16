"""Properties over HTTP (PLAN-NIGHT §4.4, N7, categories v2): create, list with
the derived status and the categories that read it, the Papierkorb (trash
switches those categories off, restore, delete for good); never edited (no
PUT); the old switch „aktiv“ is gone (410)."""

from __future__ import annotations

import pytest

from virtubooth.extensions.wall.llm import admin_api

from ..conftest import ORIGIN

BASE = "/api/x/wall/admin/llm/properties"


@pytest.fixture(autouse=True)
def mounted(app):
    app.include_router(admin_api.router, prefix="/api/x/wall")


def create(admin, name="coolness", prompt="Wie cool ist jedes Objekt?"):
    return admin.post(BASE, json={"name": name, "prompt": prompt}, headers=ORIGIN)


def test_create_and_list(admin, core):
    r = create(admin)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "coolness" and body["prompt"] == "Wie cool ist jedes Objekt?"
    assert body["status"] == "idle" and body["used_by"] == [] and body["deleted_at"] is None
    assert "active" not in body and "inactive_at" not in body
    assert body["scored_photos"] == 0
    assert body["last_scored_at"] is None
    assert create(admin, "lustigkeit", "Wie lustig?").status_code == 201
    names = [p["name"] for p in admin.get(BASE).json()["properties"]]
    assert names == ["coolness", "lustigkeit"]
    assert admin.get(f"{BASE}/coolness").json()["id"] == body["id"]
    entry = core.repos.audit.list(5)[1]
    assert entry.action == "llm.property.create" and entry.target == "property:coolness"


def test_duplicate_is_409(admin):
    create(admin)
    r = create(admin, prompt="anders")
    assert r.status_code == 409 and r.json()["error"] == "property_exists"


@pytest.mark.parametrize(
    ("name", "prompt"),
    [
        ("Coolness", "x"),
        ("c", "x"),
        ("1cool", "x"),
        ("cool-ness", "x"),
        ("a" * 32, "x"),
        ("coolness", ""),
        ("coolness", "   "),
        ("coolness", "x" * 2001),
    ],
)
def test_invalid_is_400(admin, name, prompt):
    r = create(admin, name, prompt)
    assert r.status_code == 400 and r.json()["error"] == "invalid_property", (name, prompt)


def test_no_edit_and_the_database_guards(admin, core):
    create(admin)
    r = admin.put(f"{BASE}/coolness", json={"name": "coolness", "prompt": "neu"}, headers=ORIGIN)
    assert r.status_code == 405
    assert admin.get(f"{BASE}/coolness").json()["prompt"] == "Wie cool ist jedes Objekt?"
    # the database refuses too: no edit, no delete outside the Papierkorb
    import sqlite3

    with pytest.raises(sqlite3.DatabaseError), core.db.tx() as c:
        c.execute("UPDATE llm_properties SET prompt='neu'")
    with pytest.raises(sqlite3.DatabaseError), core.db.tx() as c:
        c.execute("DELETE FROM llm_properties")


def set_active(admin, name, active):
    return admin.put(f"{BASE}/{name}/active", json={"active": active}, headers=ORIGIN)


def test_the_switch_is_gone(admin, core):
    create(admin)
    r = set_active(admin, "coolness", False)
    assert r.status_code == 410 and r.json()["error"] == "gone"
    assert set_active(admin, "nope", True).status_code == 410


def use(core, name, cid="nutzt", *, enabled=True):
    from ..llm_fakes import add_category, property_spec

    add_category(core, cid, property_spec(name, title=f"Nutzt {name}"), enabled=enabled)


def test_status_follows_the_categories_and_the_ai(admin, core):
    from ..llm_fakes import setup_llm

    create(admin)
    use(core, "coolness", "aus", enabled=False)

    def status():
        return admin.get(f"{BASE}/coolness").json()

    assert status()["status"] == "idle"  # „ruht“: only a switched-off category reads it
    assert status()["used_by"] == [{"id": "aus", "title": "Nutzt coolness", "enabled": False}]
    use(core, "coolness", "an")
    assert status()["status"] == "paused"  # the external AI is off
    svc = setup_llm(core)
    assert status()["status"] == "polled"
    admin.post(f"{BASE}/coolness/trash", headers=ORIGIN)
    assert status()["status"] == "trashed"
    del svc


def score(core, name, value=0.5):
    """A scored photo for the property (the poll's row, written directly)."""
    from ..llm_fakes import add_guest, add_photo

    pid, _ = add_photo(core, add_guest(core), labels=("hat",))
    prop = core.db.one("SELECT id FROM llm_properties WHERE name=?", (name,))["id"]
    with core.db.tx() as c:
        c.execute(
            "INSERT INTO property_scores (property_id, photo_id, scores, poll_id, updated_at) "
            "VALUES (?, ?, ?, 1, 'now')",
            (prop, pid, f"[{value}]"),
        )
    return pid


def test_trash_restore_and_the_name_stays_taken(admin, core):
    create(admin)
    create(admin, "lustigkeit", "x")
    use(core, "lustigkeit", "lustig")
    score(core, "lustigkeit")
    r = admin.post(f"{BASE}/lustigkeit/trash", headers=ORIGIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted_at"] is not None and body["scored_photos"] == 1  # scores kept
    # the category that read it is switched off, with the reason
    row = core.db.one("SELECT enabled, off_reason, off_detail FROM wall_categories")
    assert tuple(row) == (0, "property_trashed", "lustigkeit")
    # listed last; the name stays taken, the error says where it is
    props = admin.get(BASE).json()["properties"]
    assert [p["name"] for p in props] == ["coolness", "lustigkeit"]
    r = create(admin, "lustigkeit", "neu")
    assert r.status_code == 409 and r.json()["error"] == "property_exists"
    assert "Papierkorb" in r.json()["message"]
    # trash again: nothing new
    admin.post(f"{BASE}/lustigkeit/trash", headers=ORIGIN)
    actions = [e.action for e in core.repos.audit.list(20)]
    assert actions.count("llm.property.trash") == 1
    # restore: back, scores still there; the category stays off (with its reason)
    r = admin.post(f"{BASE}/lustigkeit/restore", headers=ORIGIN)
    assert r.status_code == 200 and r.json()["deleted_at"] is None
    assert r.json()["status"] == "idle" and r.json()["scored_photos"] == 1
    row = core.db.one("SELECT enabled, off_reason FROM wall_categories")
    assert tuple(row) == (0, "property_trashed")
    assert "llm.property.restore" in [e.action for e in core.repos.audit.list(20)]
    assert admin.post(f"{BASE}/nope/trash", headers=ORIGIN).status_code == 404
    assert admin.post(f"{BASE}/nope/restore", headers=ORIGIN).status_code == 404


def test_delete_for_good_only_from_the_trash(admin, core):
    create(admin)
    create(admin, "lustigkeit", "x")
    score(core, "coolness")
    r = admin.delete(f"{BASE}/coolness", headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"] == "property_not_in_trash"
    admin.post(f"{BASE}/coolness/trash", headers=ORIGIN)
    r = admin.delete(f"{BASE}/coolness", headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert [p["name"] for p in r.json()["properties"]] == ["lustigkeit"]
    assert core.db.one("SELECT COUNT(*) FROM property_scores")[0] == 0
    entry = core.repos.audit.list(1)[0]
    assert entry.action == "llm.property.delete" and entry.target == "property:coolness"
    assert entry.details == {"name": "coolness", "scores": 1}
    assert admin.get(f"{BASE}/coolness").status_code == 404
    assert admin.delete(f"{BASE}/coolness", headers=ORIGIN).status_code == 404
    # the name is free again
    assert create(admin, "coolness", "neu").status_code == 201


def test_delete_for_good_refuses_while_a_category_uses_it(admin, core):
    from virtubooth.extensions.wall.enrich import engine

    create(admin)
    spec = {
        "emoji": "😎", "title": "Coolstes Objekt", "line": "", "where": [],
        "select": {"by": "prop.coolness.max", "order": "top", "then_by": []},
    }  # fmt: skip
    engine.insert(core.db, "coolstes", engine.validate(spec), enabled=False, preset=None, by="t")
    admin.post(f"{BASE}/coolness/trash", headers=ORIGIN)
    r = admin.delete(f"{BASE}/coolness", headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"] == "property_in_use"
    assert "„Coolstes Objekt“" in r.json()["message"]
    assert admin.get(f"{BASE}/coolness").status_code == 200
    with core.db.tx() as c:
        c.execute("DELETE FROM wall_categories")
    assert admin.delete(f"{BASE}/coolness", headers=ORIGIN).status_code == 200


def test_the_trash_is_left_out_of_the_value_pickers(admin, core):
    from virtubooth.extensions.wall.enrich import values

    create(admin)
    create(admin, "lustigkeit", "x")
    fields = [f.field for f in values.catalogue(core.db, set()).object_fields]
    assert fields == ["confidence", "prop:coolness", "prop:lustigkeit"]
    admin.post(f"{BASE}/coolness/trash", headers=ORIGIN)
    out = values.catalogue(core.db, set())
    assert [f.field for f in out.object_fields] == ["confidence", "prop:lustigkeit"]
    # its scores stay readable: a category using it keeps its data
    assert values.properties_of(core.db) == {"coolness": True, "lustigkeit": False}


def test_admin_only(client):
    assert client.get(BASE).status_code == 401
    assert create(client).status_code == 401
    assert client.post(f"{BASE}/x/trash", headers=ORIGIN).status_code == 401
    assert client.put(f"{BASE}/x/active", json={"active": False}, headers=ORIGIN).status_code == 401
    assert client.delete(f"{BASE}/x", headers=ORIGIN).status_code == 401
