"""Properties over HTTP (PLAN-NIGHT §4.4, N7): create, list, archive and
unarchive; never edited (no PUT), never deleted (no DELETE)."""

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
    assert body["archived_at"] is None and body["scored_photos"] == 0
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


def test_no_edit_no_delete(admin, core):
    create(admin)
    r = admin.put(f"{BASE}/coolness", json={"name": "coolness", "prompt": "neu"}, headers=ORIGIN)
    assert r.status_code == 405
    assert admin.delete(f"{BASE}/coolness", headers=ORIGIN).status_code == 405
    assert admin.get(f"{BASE}/coolness").json()["prompt"] == "Wie cool ist jedes Objekt?"
    # the database refuses too
    import sqlite3

    with pytest.raises(sqlite3.DatabaseError), core.db.tx() as c:
        c.execute("UPDATE llm_properties SET prompt='neu'")
    with pytest.raises(sqlite3.DatabaseError), core.db.tx() as c:
        c.execute("DELETE FROM llm_properties")


def test_archive_and_unarchive(admin, core):
    create(admin)
    r = admin.post(f"{BASE}/coolness/archive", headers=ORIGIN)
    assert r.status_code == 200 and r.json()["archived_at"] is not None
    # again: stays archived, no second audit entry
    admin.post(f"{BASE}/coolness/archive", headers=ORIGIN)
    actions = [e.action for e in core.repos.audit.list(10)]
    assert actions.count("llm.property.archive") == 1
    # archived ones are listed after the active ones
    create(admin, "lustigkeit", "x")
    names = [p["name"] for p in admin.get(BASE).json()["properties"]]
    assert names == ["lustigkeit", "coolness"]
    r = admin.post(f"{BASE}/coolness/unarchive", headers=ORIGIN)
    assert r.status_code == 200 and r.json()["archived_at"] is None
    assert "llm.property.unarchive" in [e.action for e in core.repos.audit.list(10)]
    assert admin.post(f"{BASE}/nope/archive", headers=ORIGIN).status_code == 404
    assert admin.get(f"{BASE}/nope").status_code == 404


def test_admin_only(client):
    assert client.get(BASE).status_code == 401
    assert create(client).status_code == 401
    assert client.post(f"{BASE}/x/archive", headers=ORIGIN).status_code == 401
