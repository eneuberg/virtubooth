"""SQLite access: one shared connection, serialized by a lock.

Party scale (tens of guests, a few writes per second at peak) never needs more.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY,
    public_id        TEXT    NOT NULL UNIQUE,
    name             TEXT    NOT NULL DEFAULT '',
    created_at       TEXT    NOT NULL,
    last_seen_at     TEXT    NOT NULL,
    consent_at       TEXT    NOT NULL,
    consent_version  TEXT    NOT NULL,
    instagram        TEXT,
    fp_hash          TEXT,
    fp_components    TEXT    NOT NULL DEFAULT '{}',
    first_ip         TEXT    NOT NULL DEFAULT '',
    last_ip          TEXT    NOT NULL DEFAULT '',
    user_agent       TEXT    NOT NULL DEFAULT '',
    banned_at        TEXT,
    ban_reason       TEXT
);
CREATE INDEX IF NOT EXISTS users_fp ON users(fp_hash);

-- every fingerprint a user has shown (phones update, browsers change)
CREATE TABLE IF NOT EXISTS user_fingerprints (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fp_hash     TEXT    NOT NULL,
    first_seen  TEXT    NOT NULL,
    last_seen   TEXT    NOT NULL,
    PRIMARY KEY (user_id, fp_hash)
);
CREATE INDEX IF NOT EXISTS user_fingerprints_fp ON user_fingerprints(fp_hash);

CREATE TABLE IF NOT EXISTS fingerprint_bans (
    fp_hash         TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    reason          TEXT NOT NULL DEFAULT '',
    source_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS photos (
    id              INTEGER PRIMARY KEY,
    public_id       TEXT    NOT NULL UNIQUE,
    extension       TEXT    NOT NULL,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    seq             INTEGER NOT NULL,
    filename        TEXT    NOT NULL,
    thumb_filename  TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    width           INTEGER NOT NULL,
    height          INTEGER NOT NULL,
    bytes           INTEGER NOT NULL,
    meta            TEXT    NOT NULL DEFAULT '{}',
    hidden_at       TEXT,
    hidden_reason   TEXT,
    deleted_at      TEXT,
    UNIQUE (extension, seq)
);
CREATE INDEX IF NOT EXISTS photos_ext_created ON photos(extension, created_at);
CREATE INDEX IF NOT EXISTS photos_user ON photos(user_id);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash   TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    pw_tag       TEXT NOT NULL,
    ip           TEXT NOT NULL DEFAULT '',
    user_agent   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (
    id       INTEGER PRIMARY KEY,
    at       TEXT NOT NULL,
    actor    TEXT NOT NULL,
    action   TEXT NOT NULL,
    target   TEXT NOT NULL DEFAULT '',
    details  TEXT NOT NULL DEFAULT '{}'
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        for pragma in (
            "journal_mode=WAL",
            "synchronous=NORMAL",
            "foreign_keys=ON",
            "busy_timeout=5000",
        ):
            self._conn.execute(f"PRAGMA {pragma}")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version < SCHEMA_VERSION:
                self._conn.executescript(SCHEMA)
                self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Write transaction. Holds the lock for its whole duration."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
