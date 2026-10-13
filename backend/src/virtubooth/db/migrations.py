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

# v3: export jobs the admin starts (archive, timelapse, QR codes). One worker
# runs them one at a time; the files live in <data>/exports/. `options` is the
# job's JSON options, `progress` 0..1 (NULL while queued).
SCHEMA_V3 = """
CREATE TABLE export_jobs (
    id           TEXT    PRIMARY KEY,
    kind         TEXT    NOT NULL,
    status       TEXT    NOT NULL,
    options      TEXT    NOT NULL DEFAULT '{}',
    progress     REAL,
    created_at   TEXT    NOT NULL,
    created_by   TEXT    NOT NULL DEFAULT '',
    started_at   TEXT,
    finished_at  TEXT,
    error        TEXT,
    file_name    TEXT,
    bytes        INTEGER
);
CREATE INDEX export_jobs_status ON export_jobs(status);
"""

# v4: the dashboard's live overview. `visitors` has one row per browser that
# opened a valid QR link: the random id of its `vb_vid` cookie, when it was
# first and last seen, and the guest it became once it joined (NULL: never
# joined). Only random ids and timestamps: no IP, no user agent. Guests from
# before v4 have no row until their browser comes back. The indexes serve the
# "last N minutes" counters (users.last_seen_at is refreshed, throttled, on
# guest API requests).
SCHEMA_V4 = """
CREATE TABLE visitors (
    id             TEXT    PRIMARY KEY,
    first_seen_at  TEXT    NOT NULL,
    last_seen_at   TEXT    NOT NULL,
    user_id        INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX visitors_user ON visitors(user_id);
CREATE INDEX visitors_last_seen ON visitors(last_seen_at);
CREATE INDEX users_last_seen ON users(last_seen_at);
CREATE INDEX photos_created ON photos(created_at);
"""

# v9: the Live-Wall's photo analysis (extensions/wall/enrich). A separate worker
# process fills it; `rev` lets the app poll for changes. Facts are plain numbers
# per photo, so the wall's categories are cheap SQL. (5 = QR codes, 6 = tracking,
# 7/8 reserved: gaps are fine.)
SCHEMA_V9 = """
-- v9: Live-Wall photo analysis. One row per analysed photo; facts are numbers per photo for cheap
-- category queries. No face embeddings, nothing that identifies a person.
CREATE TABLE wall_analysis (
    photo_id    INTEGER PRIMARY KEY REFERENCES photos(id),
    state       TEXT    NOT NULL,            -- pending | running | done | failed | skipped
    attempts    INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    versions    TEXT    NOT NULL DEFAULT '{}',  -- {analyzer: version}
    data        TEXT    NOT NULL DEFAULT '{}',  -- JSON: boxes, details (admin only)
    rev         INTEGER NOT NULL DEFAULT 0,     -- global change counter (MAX(rev)+1 on every write)
    started_at  TEXT,
    finished_at TEXT
);
CREATE INDEX wall_analysis_state ON wall_analysis(state);
CREATE INDEX wall_analysis_rev ON wall_analysis(rev);
CREATE TABLE wall_facts (
    photo_id INTEGER NOT NULL REFERENCES photos(id),
    key      TEXT    NOT NULL,
    value    REAL    NOT NULL,
    PRIMARY KEY (photo_id, key)
);
CREATE INDEX wall_facts_key_value ON wall_facts(key, value);
"""

# (version, script): each step upgrades the database from the version before.
MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, SCHEMA),
    (2, SCHEMA_V2),
    (3, SCHEMA_V3),
    (4, SCHEMA_V4),
    (9, SCHEMA_V9),
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
