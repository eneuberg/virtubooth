"""Migration 6: online time. A v4 database (the dashboard release) upgrades in
place; its guests start with no online time and no visit."""

from __future__ import annotations

from virtubooth.db import migrations as dbmod
from virtubooth.db.database import Database
from virtubooth.repositories.container import Repositories
from virtubooth.services.identity import create_user

ONLINE_COLS = {"online_seconds", "online_sessions", "online_at"}


def test_migration_6_follows_5():
    versions = [v for v, _ in dbmod.MIGRATIONS]
    assert versions == sorted(set(versions))
    assert versions.index(6) == versions.index(5) + 1


def test_v4_database_upgrades_with_online_columns(tmp_path, monkeypatch):
    path = tmp_path / "virtubooth.db"
    v4 = tuple(step for step in dbmod.MIGRATIONS if step[0] <= 4)
    monkeypatch.setattr(dbmod, "MIGRATIONS", v4)
    monkeypatch.setattr(dbmod, "SCHEMA_VERSION", 4)
    db = Database(path)
    try:
        assert db.one("PRAGMA user_version")[0] == 4
        cols = {r[1] for r in db.all("PRAGMA table_info(users)")}
        assert not cols & ONLINE_COLS
        with db.tx() as c:
            c.execute(
                "INSERT INTO users (public_id, name, created_at, last_seen_at, consent_at, "
                "consent_version) VALUES ('pubid-anna-0001', 'Anna', 't', 't', 't', '1')"
            )
    finally:
        db.close()

    monkeypatch.undo()
    db = Database(path)
    try:
        assert db.one("PRAGMA user_version")[0] == dbmod.SCHEMA_VERSION
        cols = {r[1] for r in db.all("PRAGMA table_info(users)")}
        assert ONLINE_COLS <= cols
        row = db.one("SELECT online_seconds, online_sessions, online_at FROM users")
        assert tuple(row) == (0, 0, None)
        repos = Repositories.create(db, tmp_path)
        anna = repos.users.get_by_public_id("pubid-anna-0001")
        assert anna is not None and anna.name == "Anna"
        assert (anna.online_seconds, anna.online_sessions, anna.online_at) == (0, 0, None)
        # a guest created after the upgrade starts the same
        new = create_user(
            db, repos, consent_version="1", instagram=None, fp_hash=None, fp_components={},
            ip="10.0.0.5", user_agent="UA",
        )  # fmt: skip
        assert (new.online_seconds, new.online_sessions, new.online_at) == (0, 0, None)
    finally:
        db.close()

    # reopening changes nothing
    again = Database(path)
    try:
        assert again.one("PRAGMA user_version")[0] == dbmod.SCHEMA_VERSION
    finally:
        again.close()
