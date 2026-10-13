"""Fotobox filters on and off: the booth's admin routes (Extension.admin_router at
/api/admin/x/booth/), the guest catalogue, and uploads of switched-off filters."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import pytest

from virtubooth.domain.models import PhotoQuery
from virtubooth.extensions import booth
from virtubooth.extensions.sdk import discover_extensions

from ..conftest import JPEG, ORIGIN, jpeg

IDS = list(booth.FILTERS)
PATH = "/api/admin/x/booth/filters"


@pytest.fixture
def extensions():
    return discover_extensions(["booth"])


@pytest.fixture
def published(core, monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []
    real = core.bus.publish

    def spy(type_: str, data: dict[str, Any]) -> None:
        seen.append((type_, data))
        real(type_, data)

    monkeypatch.setattr(core.bus, "publish", spy)
    return seen


def put(client, enabled, headers=ORIGIN):
    return client.put(PATH, json={"enabled": enabled}, headers=headers)


def enabled_ids(body: dict[str, Any]) -> list[str]:
    return [f["id"] for f in body["filters"] if f["enabled"]]


def guest_ids(client) -> list[str]:
    r = client.get("/api/x/booth/filters")
    assert r.status_code == 200
    return [f["id"] for f in r.json()["filters"]]


def test_all_on_by_default(admin, guest):
    body = admin.get(PATH).json()
    assert [f["id"] for f in body["filters"]] == IDS
    assert all(f["enabled"] for f in body["filters"])
    assert body["filters"][0] == {"id": "normal", "name": "Normal", "icon": "✨", "enabled": True}
    assert guest_ids(guest()) == IDS


def test_switch_off_and_on(admin, guest, core, published):
    g = guest()
    on = [f for f in IDS if f not in ("neon", "comic")]
    # any order and duplicates: the strip order stays the catalogue's
    r = put(admin, [*reversed(on), "normal"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert [f["id"] for f in body["filters"]] == IDS
    assert enabled_ids(body) == on
    assert admin.get(PATH).json() == body
    assert guest_ids(g) == on

    entry = core.repos.audit.list()[0]
    assert (entry.action, entry.target) == ("extension.settings", "x:booth")
    assert entry.details == {"disabled": ["neon", "comic"]}
    assert entry.actor.startswith("admin:")
    assert core.repos.app_settings.get("x.booth.filters") == {
        "disabled": ["neon", "comic"],
        "by": entry.actor,
    }
    assert [d for t, d in published if t == "extension.settings"] == [{"id": "booth"}]

    # the same again: nothing written, no event
    assert put(admin, on).status_code == 200
    assert len([e for e in core.repos.audit.list() if e.action == "extension.settings"]) == 1
    assert len([t for t, _ in published if t == "extension.settings"]) == 1

    assert enabled_ids(put(admin, IDS).json()) == IDS
    assert guest_ids(g) == IDS
    assert core.repos.audit.list()[0].details == {"disabled": []}


def test_one_filter_is_enough(admin, guest):
    assert enabled_ids(put(admin, ["sepia"]).json()) == ["sepia"]
    assert guest_ids(guest()) == ["sepia"]


def test_at_least_one_stays_on(admin, core):
    r = put(admin, [])
    assert r.status_code == 400
    assert r.json() == {
        "error": "no_filter_enabled",
        "message": "Mindestens ein Filter muss an bleiben.",
    }
    assert core.repos.app_settings.get("x.booth.filters") == {}


def test_unknown_and_malformed_ids(admin, core):
    r = put(admin, ["normal", "glitter"])
    assert r.status_code == 400
    assert r.json() == {"error": "unknown_filter", "message": "Unbekannter Filter: glitter."}
    assert put(admin, ["<b>"]).status_code == 422
    assert put(admin, ["normal"] * 51).status_code == 422
    assert admin.put(PATH, json={}, headers=ORIGIN).status_code == 422
    assert core.repos.app_settings.get("x.booth.filters") == {}


def test_new_catalogue_filters_start_enabled(admin, guest, core):
    # stored: an id the catalogue no longer has; every current filter stays on
    core.repos.app_settings.put(
        "x.booth.filters", {"disabled": ["gone"], "by": "admin:x"}, at="2026-10-13T20:00:00Z"
    )
    assert guest_ids(guest()) == IDS
    assert all(f["enabled"] for f in admin.get(PATH).json()["filters"])


def test_everything_off_in_the_db_falls_back_to_the_catalogue(guest, core):
    core.repos.app_settings.put(
        "x.booth.filters", {"disabled": IDS, "by": "admin:x"}, at="2026-10-13T20:00:00Z"
    )
    assert guest_ids(guest()) == IDS


def test_upload_with_a_switched_off_filter_is_still_accepted(admin, guest, core):
    g = guest()
    put(admin, [f for f in IDS if f != "neon"])
    meta = quote(json.dumps({"filter": "neon", "facing": "user"}))
    r = g.post("/api/x/booth/upload", content=jpeg(1080, 1440), headers=JPEG | {"X-VB-Meta": meta})
    assert r.status_code == 201, r.text
    [photo] = core.repos.photos.list(PhotoQuery(extension="booth"))
    assert photo.meta == {"filter": "neon", "facing": "user"}


def test_admin_only(client, guest, admin):
    assert client.get(PATH).status_code == 401
    g = guest()
    assert g.get(PATH).status_code == 401
    r = put(g, ["normal"])
    assert r.status_code == 401 and r.json()["error"] == "admin_required"
    r = put(admin, ["normal"], headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"
    # the guest catalogue still needs party access
    assert client.get("/api/x/booth/filters").status_code == 404
