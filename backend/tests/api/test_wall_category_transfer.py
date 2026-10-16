"""„Exportieren / Importieren“ of categories (categories v2, PLAN §2/§6):
the file with the properties by name, import as a copy or replacing, a
property created from the file, a prompt conflict (theirs stays), a missing
property (`property_missing`, off), a locked category imported off, v1 files,
and a file that is not one (400 `invalid_import`)."""

from __future__ import annotations

from typing import Any

import pytest

from virtubooth.extensions.wall import make_extension
from virtubooth.extensions.wall.enrich import presets

from ..conftest import ORIGIN
from ..llm_fakes import add_property, property_spec, setup_llm
from .wall_support import FakeEnrichment, audit_actions, with_wall_page

BASE = "/api/x/wall/admin/categories"


@pytest.fixture
def extensions(demo_extension):
    return [demo_extension, make_extension(enrichment=FakeEnrichment())]


@pytest.fixture
def web_dir(web_dir):
    return with_wall_page(web_dir)


def cats(admin) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in admin.get(BASE).json()["categories"]}


def do_import(admin, file: Any, on_conflict: str | None = None):
    body: dict[str, Any] = {"file": file}
    if on_conflict:
        body["on_conflict"] = on_conflict
    return admin.post(f"{BASE}/import", json=body, headers=ORIGIN)


def test_admin_only(client):
    assert client.get(f"{BASE}/export").status_code == 401
    assert client.post(f"{BASE}/import", json={}, headers=ORIGIN).status_code == 401


def test_export_has_the_properties_by_name(admin, core):
    svc = setup_llm(core)
    add_property(core, "glitzer", "Wie glitzernd?")
    r = admin.get(f"{BASE}/export", params=[("ids", "uses_glitzer"), ("ids", "volles_haus")])
    assert r.status_code == 200, r.text
    file = r.json()
    assert file["format"] == "virtubooth-categories" and file["version"] == 2
    assert [c["id"] for c in file["categories"]] == ["volles_haus", "uses_glitzer"]
    assert file["properties"] == [{"name": "glitzer", "prompt": "Wie glitzernd?"}]
    volles = file["categories"][0]
    assert volles["preset"] == "volles_haus" and volles["enabled"] is True
    assert volles["spec"]["rank"]["by"] == {"kind": "value", "key": "people"}
    # every category without ids; a preset property not created yet: the preset's prompt
    everything = admin.get(f"{BASE}/export").json()
    assert len(everything["categories"]) == len(presets.PRESETS) + 1
    names = [p["name"] for p in everything["properties"]]
    assert names == ["coolness", "goofiness", "unexpectedness", "glitzer"]
    del svc


def test_round_trip_as_a_copy_and_replacing(admin, core):
    file = admin.get(f"{BASE}/export", params={"ids": "volles_haus"}).json()
    # an id that exists: a copy under a free id, not a preset any more
    r = do_import(admin, file)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["imported"] == [{"id": "volles_haus_2", "title": "Volles Haus", "enabled": True,
                                "from_id": "volles_haus", "replaced": False}]  # fmt: skip
    assert out["skipped"] == [] and out["switched_off"] == []
    again = do_import(admin, file).json()
    assert again["imported"][0]["id"] == "volles_haus_3"
    items = cats(admin)
    assert items["volles_haus_2"]["preset"] is None
    assert items["volles_haus_2"]["spec"] == items["volles_haus"]["spec"]
    # replace: the existing one gets the file's spec, its position stays
    file["categories"][0]["spec"]["title"] = "Rappelvoll"
    file["categories"][0]["enabled"] = False
    pos = items["volles_haus"]["position"]
    out = do_import(admin, file, "replace").json()
    assert out["imported"] == [{"id": "volles_haus", "title": "Rappelvoll", "enabled": False,
                                "from_id": None, "replaced": True}]  # fmt: skip
    item = cats(admin)["volles_haus"]
    assert item["spec"]["title"] == "Rappelvoll" and item["enabled"] is False
    assert item["position"] == pos and item["preset"] == "volles_haus"
    assert (
        "wall.category",
        "",
        {"action": "import", "imported": ["volles_haus"], "skipped": [], "properties_created": []},
    ) in audit_actions(core)


def test_property_from_the_file_and_a_prompt_conflict(admin, core):
    svc = setup_llm(core)
    add_property(core, "glitzer", "Unser Prompt", used=False)
    file = {
        "format": "virtubooth-categories", "version": 2, "exported_at": "2026-10-16T21:00:00Z",
        "properties": [{"name": "glitzer", "prompt": "Ihr Prompt"},
                       {"name": "funkeln", "prompt": "Wie funkelnd ist das?", "active": False}],
        "categories": [
            {"id": "glitzerfoto", "enabled": True, "preset": None,
             "spec": property_spec("glitzer", title="Am glitzerndsten")},
            {"id": "funkelfoto", "enabled": True, "preset": None,
             "spec": property_spec("funkeln", title="Funkeln")},
        ],
    }  # fmt: skip
    out = do_import(admin, file).json()
    assert [i["id"] for i in out["imported"]] == ["glitzerfoto", "funkelfoto"]
    assert all(i["enabled"] for i in out["imported"])
    assert out["properties_created"] == ["funkeln"]
    assert out["prompt_conflicts"] == ["glitzer"]
    assert any("active" in n for n in out["notes"])
    rows = {r["name"]: r["prompt"] for r in core.db.all("SELECT name, prompt FROM llm_properties")}
    assert rows == {"glitzer": "Unser Prompt", "funkeln": "Wie funkelnd ist das?"}
    del svc


def test_missing_property_and_locked_categories_come_in_off(admin, core):
    # the AI is not ready: a category with a property is imported off (ai_off)
    file = {
        "format": "virtubooth-categories", "version": 2, "exported_at": "x",
        "properties": [{"name": "funkeln", "prompt": "Wie funkelnd?"}],
        "categories": [
            {"id": "ohne", "enabled": True, "spec": property_spec("unbekannt", title="Ohne")},
            {"id": "funkel", "enabled": True, "spec": property_spec("funkeln", title="Funkel")},
            {"id": "aus", "enabled": False, "spec": property_spec("funkeln", title="Aus")},
        ],
    }  # fmt: skip
    out = do_import(admin, file).json()
    assert [(i["id"], i["enabled"]) for i in out["imported"]] == [
        ("ohne", False), ("funkel", False), ("aus", False)]  # fmt: skip
    off = {s["id"]: (s["reason"], s["detail"]) for s in out["switched_off"]}
    assert off == {"ohne": ("property_missing", "unbekannt"), "funkel": ("ai_off", None)}
    items = cats(admin)
    assert items["ohne"]["off_reason"] == "property_missing"
    assert items["ohne"]["off_detail"] == "unbekannt"
    assert items["ohne"]["locked"]["reason"] == "property_missing"
    assert items["funkel"]["off_reason"] == "ai_off"
    assert items["aus"]["off_reason"] is None
    assert out["properties_created"] == ["funkeln"]


def test_a_v1_file_and_bad_entries(admin):
    v1 = {
        "version": 1,
        "categories": [
            {"id": "huete", "enabled": True,
             "spec": {"emoji": "🎩", "title": "Hutträger", "line": "",
                      "where": [{"value": "objects", "op": "contains", "operand": "hat"}],
                      "select": {"by": "objects.count:hat", "order": "top", "count": 2},
                      "label": {"style": "count", "one": "Hut", "many": "Hüte"}}},
            {"spec": {"emoji": "🎉", "title": "Ohne Kennung", "line": "",
                      "where": [], "select": {"by": "people", "order": "top", "count": 1},
                      "label": {"style": "count", "one": "Person", "many": "Personen"}}},
            {"id": "kaputt", "spec": {"emoji": "x", "title": ""}},
            {"id": "Böse Kennung", "spec": {"emoji": "🎉", "title": "T", "where": [],
                                            "select": {"by": "people"}}},
            "kein Objekt",
        ],
    }  # fmt: skip
    out = do_import(admin, v1).json()
    assert [i["id"] for i in out["imported"]] == ["huete", "ohne_kennung"]
    assert [s["id"] for s in out["skipped"]] == ["kaputt", "Böse Kennung", "Eintrag 5"]
    item = cats(admin)["huete"]
    assert item["spec"]["version"] == 2
    assert item["spec"]["rank"]["by"]["where"]["labels"] == ["hat"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"file": []}, "kein JSON-Objekt"),
        ({"file": {"format": "andere", "version": 2, "categories": []}}, "Unbekanntes Format"),
        ({"file": {"format": "virtubooth-categories", "version": 3, "categories": []}},
         "Unbekannte Version"),
        ({"file": {"format": "virtubooth-categories", "version": 2}}, "categories"),
        ({"file": {"version": 1, "categories": []}, "on_conflict": "merge"}, "on_conflict"),
    ],
)  # fmt: skip
def test_not_a_file_is_a_400(admin, body, message):
    r = admin.post(f"{BASE}/import", json=body, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["error"] == "invalid_import"
    assert message in r.json()["message"]
