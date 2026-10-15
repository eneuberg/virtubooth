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

# v5: QR codes. A code's number is its id (never reused: AUTOINCREMENT, rows are
# never deleted; "Löschen" sets revoked_at). Its name is "<animal> <id>". Every token
# a code ever had stays in party_code_tokens, so no token is ever handed out twice.
# users.code_id: the code a guest joined through. code_visitors: which browser
# (vb_vid) opened which code, how often.
SCHEMA_V5 = """
CREATE TABLE party_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    animal      TEXT    NOT NULL,
    token       TEXT    NOT NULL,
    token_gen   INTEGER NOT NULL DEFAULT 1,
    target      TEXT    NOT NULL DEFAULT '',
    note        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL,
    created_by  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    revoked_at  TEXT,
    revoked_by  TEXT
);
CREATE TABLE party_code_tokens (
    token_hash  TEXT    PRIMARY KEY,
    code_id     INTEGER NOT NULL REFERENCES party_codes(id),
    set_at      TEXT    NOT NULL,
    retired_at  TEXT
);
CREATE INDEX party_code_tokens_code ON party_code_tokens(code_id);
CREATE TABLE code_visitors (
    code_id        INTEGER NOT NULL REFERENCES party_codes(id),
    visitor_id     TEXT    NOT NULL,
    first_seen_at  TEXT    NOT NULL,
    last_seen_at   TEXT    NOT NULL,
    scans          INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (code_id, visitor_id)
);
CREATE INDEX code_visitors_visitor ON code_visitors(visitor_id);
ALTER TABLE users ADD COLUMN code_id INTEGER REFERENCES party_codes(id);
CREATE INDEX users_code ON users(code_id);
"""

# v6: online time. The guest page reports every minute while it is visible
# (POST /api/here). online_at: the last beat of the visit that is open right now
# (NULL: none); online_seconds: the visible time added up; online_sessions: visits
# (a beat after more than 150 s without one starts a new visit).
SCHEMA_V6 = """
ALTER TABLE users ADD COLUMN online_seconds  INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN online_sessions INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN online_at       TEXT;
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

# v10: the guest's „Meine Fotos nicht automatisch auswerten“ (Live-Wall photo
# analysis): 1 = only image values (brightness, colour, sharpness), no faces,
# hands or expressions; such photos never win a category that needs them.
SCHEMA_V10 = """
ALTER TABLE users ADD COLUMN analysis_opt_out INTEGER NOT NULL DEFAULT 0;
"""

# v11 (night batch): frozen object lists, rule-based wall categories, guest display
# names and the external-AI opt-out, LLM properties/scores/verdicts/usage. "Frozen"
# = never UPDATEd (triggers); rows only go when their photo is deleted (purge).
SCHEMA_V11 = """
-- guests (UI2 writes, D1/D2 read)
ALTER TABLE users ADD COLUMN display_name TEXT;                       -- NULL = default: @instagram, else pseudonym
ALTER TABLE users ADD COLUMN ai_opt_out INTEGER NOT NULL DEFAULT 0;   -- 1 = never send anything to an external AI

-- the frozen object list (D1 owns; D2 appends source 'claude'/'mistral' via D1's objects.append)
CREATE TABLE photo_objects (
    photo_id   INTEGER NOT NULL REFERENCES photos(id),
    idx        INTEGER NOT NULL,          -- 0-based position in the photo's list; append-only
    label      TEXT    NOT NULL,          -- canonical lower-case English, singular ("wine glass")
    label_de   TEXT    NOT NULL,          -- German display label ("Weinglas")
    score      REAL    NOT NULL,          -- 0..1
    x REAL, y REAL, w REAL, h REAL,       -- 0..1, top-left origin; all NULL = no box
    source     TEXT    NOT NULL,          -- local | claude | mistral
    model      TEXT    NOT NULL,          -- e.g. "dfine_s_obj365@1", "claude-haiku-5-5"
    created_at TEXT    NOT NULL,
    PRIMARY KEY (photo_id, idx)
);
CREATE INDEX photo_objects_label ON photo_objects(label);
CREATE TABLE photo_detection_runs (      -- a source runs at most once per photo
    photo_id   INTEGER NOT NULL REFERENCES photos(id),
    source     TEXT    NOT NULL,          -- local | claude | mistral
    state      TEXT    NOT NULL,          -- done | failed | skipped
    model      TEXT,
    error      TEXT,                      -- short, never contains secrets
    objects    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL,
    PRIMARY KEY (photo_id, source)
);
CREATE TRIGGER photo_objects_frozen BEFORE UPDATE ON photo_objects
BEGIN SELECT RAISE(ABORT, 'photo_objects are frozen'); END;
CREATE TRIGGER photo_detection_runs_frozen BEFORE UPDATE ON photo_detection_runs
BEGIN SELECT RAISE(ABORT, 'detection runs are frozen'); END;
CREATE TRIGGER wall_facts_frozen BEFORE UPDATE ON wall_facts
BEGIN SELECT RAISE(ABORT, 'wall_facts are frozen'); END;

-- rule-based categories (D1)
CREATE TABLE wall_categories (
    id         TEXT    PRIMARY KEY,       -- ^[a-z][a-z0-9_]{1,40}$
    position   INTEGER NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    preset     TEXT,                      -- preset id it came from; NULL = made by the host
    spec       TEXT    NOT NULL,          -- JSON CategorySpec (PLAN-NIGHT §4.2)
    updated_at TEXT    NOT NULL,
    updated_by TEXT
);

-- LLM (D2 writes; D1 reads property_scores, wall_category_verdicts, llm_polls)
CREATE TABLE llm_properties (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,  -- ^[a-z][a-z0-9_]{1,30}$
    prompt      TEXT    NOT NULL,         -- 1..2000 chars
    created_at  TEXT    NOT NULL,
    created_by  TEXT,
    archived_at TEXT                      -- NULL = active (polled)
);
CREATE TRIGGER llm_properties_immutable BEFORE UPDATE OF name, prompt ON llm_properties
BEGIN SELECT RAISE(ABORT, 'property name and prompt are immutable'); END;
CREATE TRIGGER llm_properties_no_delete BEFORE DELETE ON llm_properties
BEGIN SELECT RAISE(ABORT, 'properties are archived, never deleted'); END;
CREATE TABLE llm_polls (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT    NOT NULL,
    finished_at TEXT,
    state       TEXT    NOT NULL,         -- running | done | failed | skipped
    model       TEXT,
    photos      INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);
CREATE TABLE property_scores (           -- latest scores only; overwritten by each poll
    property_id INTEGER NOT NULL REFERENCES llm_properties(id),
    photo_id    INTEGER NOT NULL REFERENCES photos(id),
    scores      TEXT    NOT NULL,         -- JSON [number 0..1 | null], index = photo_objects.idx
    poll_id     INTEGER NOT NULL,
    updated_at  TEXT    NOT NULL,
    PRIMARY KEY (property_id, photo_id)
);
CREATE TABLE wall_category_verdicts (    -- latest verdict per category
    category_id TEXT    PRIMARY KEY,
    text        TEXT    NOT NULL,         -- ≤ 160 chars, German, shown on the wall
    emoji       TEXT,
    photo_id    INTEGER REFERENCES photos(id),
    object_idx  INTEGER,
    poll_id     INTEGER NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE TABLE llm_usage (
    id             INTEGER PRIMARY KEY,
    at             TEXT    NOT NULL,
    day            TEXT    NOT NULL,      -- local date YYYY-MM-DD (party time zone) for the daily limit
    kind           TEXT    NOT NULL,      -- detect | property | verdict | test
    ref            TEXT,                  -- property name, category id or photo public_id
    provider       TEXT    NOT NULL,      -- anthropic | mistral
    model          TEXT    NOT NULL,
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_micro_usd INTEGER NOT NULL DEFAULT 0,
    ok             INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX llm_usage_day ON llm_usage(day);
"""

# v12: the admin guest („Als Gast teilnehmen“ in the admin, POST /api/admin/guest).
# is_host = 1: the host's own guest identity, created from an admin session, never
# through a QR code (code_id stays NULL, so no code's scans, joins or photos count
# it). At most one per party (the admin password is shared: there is no admin
# identity to tell two hosts apart): the partial unique index makes a second one
# impossible even when two admin tabs press the button at the same time.
SCHEMA_V12 = """
ALTER TABLE users ADD COLUMN is_host INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX users_one_host ON users(is_host) WHERE is_host = 1;
"""

# (version, script): each step upgrades the database from the version before.
MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, SCHEMA),
    (2, SCHEMA_V2),
    (3, SCHEMA_V3),
    (4, SCHEMA_V4),
    (5, SCHEMA_V5),
    (6, SCHEMA_V6),
    (9, SCHEMA_V9),
    (10, SCHEMA_V10),
    (11, SCHEMA_V11),
    (12, SCHEMA_V12),
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
