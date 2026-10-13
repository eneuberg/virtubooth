"""Clean shutdown: the app empties the SQLite WAL, so a copied data folder
holds everything in virtubooth.db (`Database.checkpoint`, run at lifespan end)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from virtubooth.db import database
from virtubooth.db.database import Database

from ..conftest import BASE_URL, accept_consent, scan


def wal_size(db_file: Path) -> int:
    wal = db_file.with_name(db_file.name + "-wal")
    return wal.stat().st_size if wal.exists() else 0


def test_clean_shutdown_leaves_everything_in_the_db_file(app: FastAPI, tmp_path: Path) -> None:
    db_file = app.state.core.db.path
    with TestClient(app, base_url=BASE_URL, follow_redirects=False) as client:
        scan(client)
        accept_consent(client)
        assert wal_size(db_file) > 0  # the new guest sits in the WAL

    assert wal_size(db_file) == 0
    # only the database file, as when someone copies it without the -wal file
    copy = tmp_path / "copy.db"
    copy.write_bytes(db_file.read_bytes())
    conn = sqlite3.connect(copy)
    try:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    finally:
        conn.close()


def test_checkpoint_never_raises_and_keeps_the_db_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(database, "CHECKPOINT_BUSY_MS", 50)
    db = Database(tmp_path / "virtubooth.db")
    reader = sqlite3.connect(db.path, isolation_level=None)
    try:
        # a CLI tool in the middle of a read keeps the WAL busy
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM users").fetchone()
        assert db.checkpoint() is False
        assert db.one("PRAGMA busy_timeout")[0] == database.BUSY_TIMEOUT_MS
        reader.execute("COMMIT")

        assert db.checkpoint() is True
        assert wal_size(db.path) == 0
    finally:
        reader.close()
        db.close()
    assert db.checkpoint() is False  # closed: logged, not raised
