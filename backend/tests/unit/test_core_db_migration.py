"""Schema migrations: a database created by the v1 code (the host's local DB,
production) upgrades in place, keeps every row, and the new columns work."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from virtubooth.core.clock import now_iso
from virtubooth.core.events import EventBus
from virtubooth.db import migrations as dbmod
from virtubooth.db.database import Database
from virtubooth.db.migrations import SCHEMA, SCHEMA_VERSION
from virtubooth.domain.constants import PAUSE_ADMIN, PAUSE_NEW_GUEST_LOCK
from virtubooth.repositories.container import Repositories
from virtubooth.services.events import AdminEvents
from virtubooth.services.identity import create_user
from virtubooth.services.upload_controls import UploadControlsService
from virtubooth.services.views import AdminViews


def open_services(db: Database, data_dir: Path) -> tuple[Repositories, UploadControlsService]:
    repos = Repositories.create(db, data_dir)
    controls = UploadControlsService(db, repos, AdminEvents(db, EventBus()), AdminViews(repos))
    return repos, controls


# columns added after v1 (the upgrade test compares the v1 columns only)
LATER_USER_COLS = ("code_id", "analysis_opt_out", "display_name", "ai_opt_out", "is_host")
TABLES = ["users", "user_fingerprints", "fingerprint_bans", "photos", "admin_sessions", "audit_log"]


def make_v1_db(path: Path) -> None:
    """Exactly what the v1 code did on first start, plus a party's worth of data."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA user_version=1")
    ts = "2026-10-10T20:00:00.000+00:00"
    users = [
        (1, "pubid-anna-0001", "Tanzende Giraffe #1", ts, ts, ts, "1", "anna", "aa" * 32,
         json.dumps({"ua": "iPhone", "screen": "390x844@3"}), "10.0.0.2", "10.0.0.3", "UA 1", None, None),
        (2, "pubid-ben-00002", "Durstiger Waschbär #2", ts, ts, ts, "1", None, "bb" * 32,
         "{}", "10.0.0.4", "10.0.0.4", "UA 2", ts, "Spam"),
    ]  # fmt: skip
    conn.executemany("INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", users)
    conn.executemany(
        "INSERT INTO user_fingerprints VALUES (?,?,?,?)",
        [(1, "aa" * 32, ts, ts), (2, "bb" * 32, ts, ts)],
    )
    conn.execute("INSERT INTO fingerprint_bans VALUES (?,?,?,?)", ("bb" * 32, ts, "Spam", 2))
    photos = [
        (1, "photo-aaaaaaaa1", "beer", 1, 1, "a.jpg", "thumbs/a.jpg", ts, 1080, 1440, 1234, '{"vessel": "cup"}', None, None, None),
        (2, "photo-bbbbbbbb2", "beer", 2, 2, "b.jpg", "thumbs/b.jpg", ts, 1080, 1440, 999, "{}", ts, "ban", None),
        (3, "photo-cccccccc3", "booth", 1, 1, "c.jpg", "thumbs/c.jpg", ts, 1080, 1440, 555, "{}", None, None, ts),
    ]  # fmt: skip
    conn.executemany("INSERT INTO photos VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", photos)
    conn.execute(
        "INSERT INTO admin_sessions VALUES (?,?,?,?,?,?)",
        ("ff" * 32, ts, "2099-01-01T00:00:00+00:00", "tag", "10.0.0.9", "Firefox"),
    )
    conn.execute(
        "INSERT INTO audit_log (at, actor, action, target, details) VALUES (?,?,?,?,?)",
        (ts, "admin:abcd", "user.ban", "user:2", '{"reason": "Spam"}'),
    )
    conn.close()


def dump(path: Path) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(path)
    try:
        out = {}
        for table in TABLES:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            v1_cols = [
                c
                for c in cols
                if not c.startswith(("uploads_", "online_")) and c not in LATER_USER_COLS
            ]
            out[table] = conn.execute(
                f"SELECT {', '.join(v1_cols)} FROM {table} ORDER BY rowid"
            ).fetchall()
        return out
    finally:
        conn.close()


def test_fresh_database_is_current(tmp_path):
    db = Database(tmp_path / "new.db")
    try:
        assert db.one("PRAGMA user_version")[0] == SCHEMA_VERSION == 12
        cols = {r[1] for r in db.all("PRAGMA table_info(users)")}
        assert {"uploads_paused_at", "uploads_paused_source", "uploads_lock_period"} <= cols
        assert db.one("SELECT COUNT(*) FROM settings")[0] == 0
        # v3: export jobs
        cols = {r[1] for r in db.all("PRAGMA table_info(export_jobs)")}
        assert {"id", "kind", "status", "options", "progress", "file_name", "bytes"} <= cols
        assert db.one("SELECT COUNT(*) FROM export_jobs")[0] == 0
    finally:
        db.close()


def test_v1_database_upgrades_in_place_without_data_loss(tmp_path):
    path = tmp_path / "virtubooth.db"
    make_v1_db(path)
    before = dump(path)
    assert sum(len(rows) for rows in before.values()) == 10

    db = Database(path)
    try:
        assert db.one("PRAGMA user_version")[0] == SCHEMA_VERSION
        repos, controls = open_services(db, tmp_path)
        # every v1 row is still there, unchanged
        assert dump(path) == before
        anna, ben = repos.users.get(1), repos.users.get(2)
        assert anna.name == "Tanzende Giraffe #1" and anna.instagram == "anna"
        assert anna.fp_components == {"ua": "iPhone", "screen": "390x844@3"}
        assert anna.photo_count == 1 and not anna.banned
        assert ben.banned and ben.ban_reason == "Spam"
        # the new columns start empty: nobody is paused by the upgrade
        assert not anna.uploads_paused and anna.uploads_paused_source is None
        assert anna.uploads_lock_period is None
        # v12: nobody is the admin guest after the upgrade
        assert not anna.is_host and not ben.is_host and repos.users.host() is None
        assert repos.photos.get("photo-aaaaaaaa1").meta == {"vessel": "cup"}
        assert repos.photos.get("photo-bbbbbbbb2").hidden_reason == "ban"
        assert repos.bans.is_banned("bb" * 32)
        assert repos.admin_sessions.get("ff" * 32, now=now_iso()).user_agent == "Firefox"
        assert repos.audit.list()[0].details == {"reason": "Spam"}

        # ... and they work
        assert controls.set_user_paused(1, True, actor="pytest")[1]
        assert repos.users.get(1).uploads_paused_source == PAUSE_ADMIN
        assert controls.set_pause(True, restore=None, actor="pytest").changed
        assert repos.app_settings.upload_lock().period == 1
        new = create_user(
            db, repos, consent_version="1", instagram=None, fp_hash=None, fp_components={},
            ip="10.0.0.5", user_agent="UA 3",
        )  # fmt: skip
        assert new.id == 3 and new.uploads_paused_source == PAUSE_NEW_GUEST_LOCK
        assert controls.set_pause(False, restore=True, actor="pytest").restored == [3]
        assert repos.users.get(1).uploads_paused  # paused by hand: stays paused
        assert controls.set_stop(True, actor="pytest")[1] and controls.uploads_stopped()
        assert repos.photos.get("photo-aaaaaaaa1").user_uploads_paused
    finally:
        db.close()

    # reopening an upgraded database changes nothing
    again = Database(path)
    try:
        assert again.one("PRAGMA user_version")[0] == SCHEMA_VERSION
        repos, controls = open_services(again, tmp_path)
        assert repos.users.get(1).uploads_paused and controls.uploads_stopped()
        assert len(repos.users.list()) == 3
    finally:
        again.close()


def test_failed_step_rolls_back_to_the_version_before(tmp_path, monkeypatch):
    path = tmp_path / "virtubooth.db"
    make_v1_db(path)
    broken = "ALTER TABLE users ADD COLUMN half_done TEXT;\nTHIS IS NOT SQL;\n"
    monkeypatch.setattr(dbmod, "MIGRATIONS", ((1, SCHEMA), (2, broken)))
    monkeypatch.setattr(dbmod, "SCHEMA_VERSION", 2)
    with pytest.raises(sqlite3.OperationalError):
        Database(path)
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        assert "half_done" not in cols
    finally:
        conn.close()
    assert dump(path)["users"]  # data untouched
    monkeypatch.undo()
    db = Database(path)  # the real migration still runs afterwards
    try:
        assert db.one("PRAGMA user_version")[0] == SCHEMA_VERSION
    finally:
        db.close()


def test_newer_database_is_left_alone(tmp_path):
    path = tmp_path / "virtubooth.db"
    Database(path).close()
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    conn.close()
    db = Database(path)
    try:
        assert db.one("PRAGMA user_version")[0] == SCHEMA_VERSION + 1
    finally:
        db.close()


def test_v12_allows_one_admin_guest_only(tmp_path):
    path = tmp_path / "virtubooth.db"
    make_v1_db(path)
    db = Database(path)
    try:
        repos = Repositories.create(db, tmp_path)
        args = dict(at=now_iso(), consent_version="1", instagram=None, fp_hash=None,
                    fp_components={}, ip="", user_agent="")  # fmt: skip
        uid = repos.users.create(public_id="host-0000001", is_host=True, **args)
        host = repos.users.host()
        assert host is not None and host.id == uid and host.is_host
        assert repos.users.create(public_id="guest-000002", **args)  # normal guests: any number
        with pytest.raises(sqlite3.IntegrityError):
            repos.users.create(public_id="host-0000003", is_host=True, **args)
        assert [u.id for u in repos.users.list() if u.is_host] == [uid]
    finally:
        db.close()
