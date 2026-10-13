"""Schema migrations: an append-only list of (version, script) steps.

Never edit a released step: add a new one to MIGRATIONS, so existing databases
(local, production) upgrade in place. `PRAGMA user_version` holds the version.
`Database` reads MIGRATIONS and SCHEMA_VERSION from this module at call time
(tests monkeypatch them).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

# v1: the original schema. Never edit a released step: add a new one to
# MIGRATIONS below, so existing databases (local, production) upgrade in place.
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

# v2: upload pauses. A guest's uploads can be paused by an admin ('admin') or,
# while the new-guest lock is on, from the moment they join ('new_guest_lock',
# tagged with the lock period that paused them). Global switches live in
# `settings` (JSON values).
SCHEMA_V2 = """
ALTER TABLE users ADD COLUMN uploads_paused_at TEXT;
ALTER TABLE users ADD COLUMN uploads_paused_source TEXT;
ALTER TABLE users ADD COLUMN uploads_lock_period INTEGER;
CREATE INDEX users_lock_period ON users(uploads_lock_period)
    WHERE uploads_lock_period IS NOT NULL;

CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

# (version, script): each step upgrades the database from the version before.
MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, SCHEMA),
    (2, SCHEMA_V2),
)
SCHEMA_VERSION = MIGRATIONS[-1][0]


def statements(script: str) -> Iterator[str]:
    """Split an SQL script into complete statements (comments stay attached)."""
    buf = ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            yield buf.strip()
            buf = ""
    if buf.strip():
        raise ValueError(f"incomplete SQL statement: {buf.strip()[:80]}")
