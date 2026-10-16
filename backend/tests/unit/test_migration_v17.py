"""Migration 17: properties get the switch „aktiv“ and the Papierkorb. A v16
database's archived properties come out inactive (not polled, scores kept),
none is in the Papierkorb, and only one in the Papierkorb can be deleted."""

from __future__ import annotations

import sqlite3

import pytest

from virtubooth.db import migrations as dbmod
from virtubooth.db.database import Database


def test_migration_17_follows_16():
    versions = [v for v, _ in dbmod.MIGRATIONS]
    assert versions.index(17) == versions.index(16) + 1


def test_v16_archived_properties_become_inactive(tmp_path, monkeypatch):
    path = tmp_path / "virtubooth.db"
    v16 = tuple(step for step in dbmod.MIGRATIONS if step[0] <= 16)
    monkeypatch.setattr(dbmod, "MIGRATIONS", v16)
    monkeypatch.setattr(dbmod, "SCHEMA_VERSION", 16)
    db = Database(path)
    try:
        with db.tx() as c:
            c.execute(
                "INSERT INTO llm_properties (id, name, prompt, created_at, archived_at) VALUES "
                "(1, 'coolness', 'p', 't', NULL), (2, 'old_one', 'q', 't', 'at')"
            )
    finally:
        db.close()

    monkeypatch.undo()
    db = Database(path)
    try:
        assert db.one("PRAGMA user_version")[0] == dbmod.SCHEMA_VERSION
        cols = {r[1] for r in db.all("PRAGMA table_info(llm_properties)")}
        assert {"inactive_at", "deleted_at"} <= cols and "archived_at" not in cols
        rows = db.all("SELECT name, inactive_at, deleted_at FROM llm_properties ORDER BY id")
        assert [tuple(r) for r in rows] == [("coolness", None, None), ("old_one", "at", None)]
        # still immutable; deleting needs the Papierkorb first
        with pytest.raises(sqlite3.DatabaseError), db.tx() as c:
            c.execute("UPDATE llm_properties SET prompt='neu'")
        with pytest.raises(sqlite3.DatabaseError), db.tx() as c:
            c.execute("DELETE FROM llm_properties WHERE id=2")
        with db.tx() as c:
            c.execute("UPDATE llm_properties SET deleted_at='now' WHERE id=2")
            c.execute("DELETE FROM llm_properties WHERE id=2")
        assert db.one("SELECT COUNT(*) FROM llm_properties")[0] == 1
    finally:
        db.close()
