"""The API key at rest (PLAN-NIGHT N11): AES-GCM under a key derived from
VB_SECRET_KEY, never returned, never in an archive."""

from __future__ import annotations

import sqlite3

import pytest

from virtubooth.extensions.wall.llm import admin_api, crypto
from virtubooth.tools import export as export_tool

from ..conftest import ORIGIN, SECRET_KEY
from ..llm_fakes import API_KEY

BASE = "/api/x/wall/admin/llm"


@pytest.fixture(autouse=True)
def mounted(app):
    app.include_router(admin_api.router, prefix="/api/x/wall")


def test_round_trip():
    record = crypto.encrypt(SECRET_KEY, "anthropic", API_KEY)
    assert set(record) == {"v", "provider", "nonce", "ct"}
    assert API_KEY not in str(record)
    assert crypto.decrypt(SECRET_KEY, record) == API_KEY
    # a fresh nonce every time
    assert crypto.encrypt(SECRET_KEY, "anthropic", API_KEY)["ct"] != record["ct"]


def test_wrong_secret_or_tampering_is_unreadable():
    record = crypto.encrypt(SECRET_KEY, "anthropic", API_KEY)
    with pytest.raises(crypto.KeyUnreadable):
        crypto.decrypt("another-secret-key-0123456789abcdef0123", record)
    # the provider is authenticated (AAD): relabelling the record breaks it
    with pytest.raises(crypto.KeyUnreadable):
        crypto.decrypt(SECRET_KEY, {**record, "provider": "mistral"})
    with pytest.raises(crypto.KeyUnreadable):
        crypto.decrypt(SECRET_KEY, {**record, "ct": record["ct"][:-4] + "AAAA"})
    with pytest.raises(crypto.KeyUnreadable):
        crypto.decrypt(SECRET_KEY, {**record, "v": 2})


def test_changed_secret_shows_invalid(core):
    store = crypto.KeyStore(core.repos.app_settings, SECRET_KEY)
    store.put("anthropic", API_KEY, by="admin:x", at="2026-10-15T20:00:00.000+00:00")
    assert store.status("anthropic") == crypto.KeyStatus(
        set=True, set_at="2026-10-15T20:00:00.000+00:00", provider="anthropic", valid=True
    )
    assert store.load("anthropic") == API_KEY
    assert store.load("mistral") is None
    assert store.status("mistral") == crypto.KeyStatus(
        set=False, set_at=None, provider="mistral", valid=False
    )
    other = crypto.KeyStore(core.repos.app_settings, "a-new-secret-key-0123456789abcdef01234")
    assert other.status("anthropic").set is True and other.status("anthropic").valid is False
    assert other.load("anthropic") is None


def test_one_key_per_provider(core):
    """Each provider keeps its own key: switching the provider loses none."""
    store = crypto.KeyStore(core.repos.app_settings, SECRET_KEY)
    store.put("anthropic", API_KEY, by="t", at="2026-10-15T20:00:00.000+00:00")
    store.put("scaleway", "scw-secret-0123456789", by="t", at="2026-10-15T21:00:00.000+00:00")
    assert store.load("anthropic") == API_KEY
    assert store.load("scaleway") == "scw-secret-0123456789"
    assert crypto.stored_providers(core.repos.app_settings) == {"anthropic", "scaleway"}
    # replacing one leaves the other
    store.put("scaleway", "scw-new-0123456789", by="t", at="2026-10-15T22:00:00.000+00:00")
    assert store.load("anthropic") == API_KEY and store.load("scaleway") == "scw-new-0123456789"
    assert store.clear("anthropic") and not store.clear("anthropic")
    assert store.load("anthropic") is None and store.load("scaleway") == "scw-new-0123456789"
    assert store.clear("scaleway")
    assert core.repos.app_settings.get(crypto.KEY_KEY) == {}


def test_a_key_from_before_is_filed_under_its_provider(core):
    """Before v2 the row held one record: it reads as its provider's key, and the
    service's start rewrites it into the per-provider shape."""
    from virtubooth.extensions.wall.llm.service import LlmService

    old = crypto.encrypt(SECRET_KEY, "scaleway", API_KEY)
    old.update({"set_at": "2026-10-15T21:05:47.947+00:00", "by": "admin:x"})
    core.repos.app_settings.put(crypto.KEY_KEY, old, at="x")
    store = crypto.KeyStore(core.repos.app_settings, SECRET_KEY)
    assert store.load("scaleway") == API_KEY and store.load("anthropic") is None
    assert store.status("scaleway").set_at == "2026-10-15T21:05:47.947+00:00"
    svc = LlmService.of(core)
    svc.start()
    try:
        raw = core.repos.app_settings.get(crypto.KEY_KEY)
        assert raw["v"] == 2 and set(raw["keys"]) == {"scaleway"}
        assert raw["keys"]["scaleway"]["set_at"] == "2026-10-15T21:05:47.947+00:00"
        assert store.load("scaleway") == API_KEY
        assert store.migrate() is None  # idempotent
    finally:
        svc.stop()


def test_stored_row_holds_no_plain_key(core):
    crypto.KeyStore(core.repos.app_settings, SECRET_KEY).put(
        "anthropic", API_KEY, by="t", at="2026-10-15T20:00:00.000+00:00"
    )
    row = core.db.one("SELECT value FROM settings WHERE key=?", (crypto.KEY_KEY,))
    assert row is not None and API_KEY not in row["value"]
    assert API_KEY[8:24] not in row["value"]


def test_api_never_returns_the_key(admin, core):
    r = admin.put(f"{BASE}/key", json={"provider": "anthropic", "key": API_KEY}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "set": True,
        "set_at": r.json()["set_at"],
        "provider": "anthropic",
        "valid": True,
    }
    for path in ("", "/usage", "/properties"):
        body = admin.get(f"{BASE}{path}").text
        assert API_KEY not in body and API_KEY[-12:] not in body, path
    status = admin.get(BASE).json()
    assert status["key"]["set"] is True and status["key"]["valid"] is True
    keys = {k["provider"]: k["set"] for k in status["keys"]}
    assert keys == {"anthropic": True, "mistral": False, "deutschlandgpt": False,
                    "scaleway": False}  # fmt: skip
    # the audit entry says what happened, never the key
    entry = core.repos.audit.list(5)[0]
    assert entry.action == "llm.key" and entry.details == {"mode": "set", "provider": "anthropic"}
    assert API_KEY not in str(core.repos.audit.list(50))

    # another provider's key: stored beside it, deleted on its own
    r = admin.put(f"{BASE}/key", json={"provider": "scaleway", "key": "scw-0123456789"},
                  headers=ORIGIN)  # fmt: skip
    assert r.json()["provider"] == "scaleway" and r.json()["set"] is True
    r = admin.delete(f"{BASE}/key?provider=scaleway", headers=ORIGIN)
    assert r.json() == {"set": False, "set_at": None, "provider": "scaleway", "valid": False}
    assert admin.get(BASE).json()["key"]["set"] is True  # anthropic's stays
    r = admin.delete(f"{BASE}/key", headers=ORIGIN)  # the configured provider's
    assert r.json()["set"] is False and r.json()["provider"] == "anthropic"
    assert core.repos.audit.list(1)[0].details == {"mode": "clear", "provider": "anthropic"}


@pytest.mark.parametrize(
    "key",
    ["", "sk-ant with space", "sk-ant-x\nnext", "x" * 401],
)
def test_malformed_keys_are_refused(admin, key):
    r = admin.put(f"{BASE}/key", json={"provider": "anthropic", "key": key}, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["error"] == "llm_key_invalid"


def test_key_routes_are_admin_only(client):
    r = client.put(f"{BASE}/key", json={"provider": "anthropic", "key": API_KEY}, headers=ORIGIN)
    assert r.status_code == 401
    assert client.get(BASE).status_code == 401


def test_archive_copy_drops_the_key(core, tmp_path):
    crypto.KeyStore(core.repos.app_settings, SECRET_KEY).put(
        "anthropic", API_KEY, by="t", at="2026-10-15T20:00:00.000+00:00"
    )
    snap = export_tool.take_snapshot(core.settings.data_dir, tmp_path, include_hidden=True)
    conn = sqlite3.connect(snap.db_file)
    try:
        keys = [r[0] for r in conn.execute("SELECT key FROM settings")]
    finally:
        conn.close()
    assert crypto.KEY_KEY not in keys
    raw = snap.db_file.read_bytes()
    record = core.repos.app_settings.get(crypto.KEY_KEY)
    ct = record["keys"]["anthropic"]["ct"]
    assert ct.encode() not in raw and API_KEY.encode() not in raw
