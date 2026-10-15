"""Einstellungen: the event name (GET /api/admin/settings, PUT /api/admin/settings/event)
and where guests and exports see it."""

from __future__ import annotations

from typing import Any

import pytest

from virtubooth.repositories.app_settings import EVENT_KEY
from virtubooth.services.host_settings import event_name

from ..conftest import ORIGIN, fp, scan


@pytest.fixture
def published(core, monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []
    real = core.bus.publish

    def spy(type_: str, data: dict[str, Any]) -> None:
        seen.append((type_, data))
        real(type_, data)

    monkeypatch.setattr(core.bus, "publish", spy)
    return seen


def put_name(client, name, headers=ORIGIN):
    return client.put("/api/admin/settings/event", json={"name": name}, headers=headers)


def test_defaults(admin):
    r = admin.get("/api/admin/settings")
    assert r.status_code == 200
    assert r.json() == {
        "event": {
            "name": "Testparty",
            "default_name": "Testparty",
            "custom": False,
            "updated_at": None,
            "by": None,
        },
        "password": {"source": "env", "changed_at": None},
        "public_address": {
            "address": None,
            "effective": "http://testserver",
            "source": "auto",
            "check": {
                "status": "auto",
                "url": None,
                "at": None,
                "message": "Die QR-Codes nehmen die Adresse, unter der die Verwaltung offen ist.",
            },
        },
    }


def test_set_normalises_and_audits(admin, core, published):
    r = put_name(admin, "  Sommer \n\t Fest   2026 ")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Sommer Fest 2026"
    assert body["default_name"] == "Testparty"
    assert body["custom"] is True and body["changed"] is True
    assert body["by"].startswith("admin:") and body["updated_at"]
    assert admin.get("/api/admin/settings").json()["event"] == {
        k: v for k, v in body.items() if k != "changed"
    }

    entry = core.repos.audit.list()[0]
    assert entry.action == "settings.event"
    assert entry.details == {"event_name": "Sommer Fest 2026", "previous": "Testparty"}
    [data] = [d for t, d in published if t == "settings.event"]
    assert data == {"event": {k: v for k, v in body.items() if k != "changed"}}

    # the same name again changes nothing (no audit row, no event)
    again = put_name(admin, "Sommer Fest 2026").json()
    assert again["changed"] is False
    assert len([e for e in core.repos.audit.list() if e.action == "settings.event"]) == 1
    assert len([t for t, _ in published if t == "settings.event"]) == 1


@pytest.mark.parametrize("name", [None, "", "   \n "])
def test_reset_with_null_or_blank(admin, core, published, name):
    put_name(admin, "Sommerfest")
    r = put_name(admin, name)
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "name": "Testparty",
        "default_name": "Testparty",
        "custom": False,
        "updated_at": None,
        "by": None,
        "changed": True,
    }
    assert core.repos.app_settings.get(EVENT_KEY) == {}
    entry = core.repos.audit.list()[0]
    assert entry.details == {"event_name": "Testparty", "previous": "Sommerfest"}
    assert put_name(admin, None).json()["changed"] is False


@pytest.mark.parametrize(
    "name",
    [
        "x" * 61,
        "Party\x00",
        "Party \x1b[31m rot",
        "Fest‮moc.evil",  # bidi override
        "​​",  # only invisible characters
    ],
)
def test_invalid_names(admin, core, name):
    r = put_name(admin, name)
    assert r.status_code == 400
    assert r.json() == {
        "error": "invalid_event_name",
        "message": "Der Name braucht 1 bis 60 Zeichen.",
    }
    assert core.repos.app_settings.event_name() is None


def test_limits_of_the_body(admin):
    assert put_name(admin, "x" * 60).status_code == 200
    # emoji and umlauts are fine; whitespace inside a 60-char name collapses
    assert put_name(admin, "Ömers 🎉 " + " " * 100 + "Feier").json()["name"] == "Ömers 🎉 Feier"
    assert put_name(admin, "x" * 201).status_code == 422
    assert admin.put("/api/admin/settings/event", json={}, headers=ORIGIN).status_code == 422


def test_guests_see_the_new_name(admin, client, core):
    put_name(admin, "Gartenparty")
    scan(client)
    consent = client.post("/api/identify", json={"fp": fp()}, headers=ORIGIN).json()["consent"]
    assert consent["title"] == "Willkommen bei Gartenparty!"
    assert consent["party_name"] == "Gartenparty"
    assert client.get("/api/extensions").json()["party_name"] == "Gartenparty"
    # export runners read it without the services
    assert event_name(core.settings, core.repos) == "Gartenparty"
    put_name(admin, None)
    assert client.get("/api/extensions").json()["party_name"] == "Testparty"
    assert event_name(core.settings, core.repos) == "Testparty"


def test_needs_an_admin_session_and_same_origin(client, admin):
    assert client.get("/api/admin/settings").status_code == 401
    r = put_name(client, "Fremd")
    assert r.status_code == 401 and r.json()["error"] == "admin_required"
    r = put_name(admin, "Fremd", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"
    assert put_name(admin, "Fremd", headers={}).status_code == 403
    assert admin.get("/api/admin/settings").json()["event"]["custom"] is False
