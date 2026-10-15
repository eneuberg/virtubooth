"""Analysis jobs: rows in `wall_analysis` (migration 9), found by a DB scan.

A photo needs analysis when it has no row or its row is `pending` (backfill
needs no queue). The worker claims the newest such photo, marks it `running`,
and finishes it as `done`, `failed` (after MAX_ATTEMPTS crashed or failed
attempts) or `skipped` (no file). Every write sets `rev = MAX(rev) + 1`, a
global change counter the app polls (`changes_since`).

Frozen (PLAN-NIGHT N3): a photo is analysed ONCE. `finish` only inserts its
facts (`wall_facts`) and its local object list (`photo_objects`, with the
`local` run in `photo_detection_runs`); the database aborts any UPDATE of
those tables. There is no re-run: a new analyzer version, an analyzer switched
on or a guest's opt-out change only affect photos analysed afterwards. Rows
go only when their photo is deleted (`purge_deleted`).

Which file: a Fotobox photo's unfiltered original when one is stored
(`photos.raw_filename`, migration v13), else the photo. Photos taken before
originals were kept were analysed on the filtered image; being frozen, they
stay so.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ....core.clock import now_iso
from ....db.database import Database
from ....domain.codes import code_name
from ....repositories.app_settings import AppSettingsRepo
from . import objects
from .analyzers import ALWAYS_ON, BY_NAME, DEFAULT_DISABLED, SETTINGS, settings_defaults
from .objects import DetectedObject
from .pipeline import PhotoInfo, SourceLabels

# attempts per photo: a crashed or failed attempt is retried while attempts < 3
MAX_ATTEMPTS = 3
STATES = ("pending", "running", "done", "failed", "skipped")
ABORTED = "Analyse abgebrochen"

# settings keys: {disabled: [names], settings: {analyzer: {key: value}}, by}
# (the complete disabled set; absent = DEFAULT_DISABLED) and the worker's
# heartbeat {pid, beat_at, ml, models_missing, load_errors, processed, rss_mb, stats}
ANALYZERS_KEY = "x.wall.analyzers"
WORKER_KEY = "x.wall.worker"
# {ext id: {title, labels, values}} of the loaded extensions, written by the
# app at the wall's start: the worker names sources and meta values with it
# without importing the extensions (and FastAPI)
SOURCES_KEY = "x.wall.sources"

_NEEDS_WORK = "p.deleted_at IS NULL AND (a.photo_id IS NULL OR a.state = 'pending')"


@dataclass(frozen=True)
class AnalysisRow:
    photo_id: int
    state: str
    attempts: int
    error: str | None
    versions: dict[str, str]
    data: dict[str, Any]
    rev: int
    started_at: str | None
    finished_at: str | None


def _next_rev(c: sqlite3.Connection) -> int:
    return int(c.execute("SELECT COALESCE(MAX(rev), 0) + 1 FROM wall_analysis").fetchone()[0])


def _upsert(c: sqlite3.Connection, photo_id: int, **cols: Any) -> None:
    """Insert or update one row; always with a fresh rev."""
    cols["rev"] = _next_rev(c)
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{k}=excluded.{k}" for k in cols)
    c.execute(
        f"INSERT INTO wall_analysis (photo_id, {names}) VALUES (?, {marks}) "
        f"ON CONFLICT(photo_id) DO UPDATE SET {updates}",
        (photo_id, *cols.values()),
    )


def has_work(db: Database) -> bool:
    return (
        db.one(
            "SELECT 1 FROM photos p LEFT JOIN wall_analysis a ON a.photo_id = p.id "
            f"WHERE {_NEEDS_WORK} LIMIT 1"
        )
        is not None
    )


def claim(db: Database) -> PhotoInfo | None:
    """Take the newest photo that needs analysis: `running`, attempts + 1."""
    with db.tx() as c:
        row = c.execute(
            # the unfiltered original when there is one (Fotobox, v13): the analysis
            # sees the guests, not the filter; same size and crop, so the boxes fit both
            "SELECT p.id, p.public_id, p.extension, "
            "COALESCE(p.raw_filename, p.filename) AS filename, p.created_at, p.width, "
            "p.height, p.meta, u.name AS user_name, u.analysis_opt_out, "
            "c.id AS code_id, c.animal AS code_animal, COALESCE(a.attempts, 0) AS attempts "
            "FROM photos p JOIN users u ON u.id = p.user_id "
            "LEFT JOIN party_codes c ON c.id = u.code_id "
            "LEFT JOIN wall_analysis a ON a.photo_id = p.id "
            f"WHERE {_NEEDS_WORK} ORDER BY p.id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        _upsert(
            c, row["id"], state="running", attempts=int(row["attempts"]) + 1, error=None,
            started_at=now_iso(), finished_at=None,
        )  # fmt: skip
    return PhotoInfo(
        id=row["id"], public_id=row["public_id"], extension=row["extension"],
        filename=row["filename"], created_at=row["created_at"], width=row["width"],
        height=row["height"], meta=json.loads(row["meta"] or "{}"), user_name=row["user_name"],
        code_name=code_name(row["code_animal"], row["code_id"]) if row["code_id"] else None,
        opt_out=bool(row["analysis_opt_out"]),
    )  # fmt: skip


def finish(
    db: Database, photo_id: int, *, facts: Mapping[str, float], data: Mapping[str, Any],
    versions: Mapping[str, str], objects_found: Sequence[DetectedObject] = (),
    objects_model: str | None = None, objects_skipped: str | None = None,
) -> bool:  # fmt: skip
    """Store a finished analysis, once: facts, data, and the local object list
    (`objects_model` set: the detector ran; else a `skipped` local run with the
    reason `objects_skipped`), all in one transaction. False (nothing written)
    when the row is no longer `running` (purged meanwhile)."""
    with db.tx() as c:
        row = c.execute("SELECT state FROM wall_analysis WHERE photo_id=?", (photo_id,)).fetchone()
        if row is None or row["state"] != "running":
            return False
        c.executemany(
            "INSERT INTO wall_facts (photo_id, key, value) VALUES (?,?,?)",
            [(photo_id, k, float(v)) for k, v in sorted(facts.items())],
        )
        _upsert(
            c, photo_id, state="done", error=None, data=json.dumps(data, ensure_ascii=False),
            versions=json.dumps(dict(versions)), finished_at=now_iso(),
        )  # fmt: skip
        if not objects.has_run(db, photo_id, "local"):
            if objects_model is not None:
                objects.append(db, photo_id, "local", objects_model, objects_found)
            else:
                objects.record_run(
                    db, photo_id, "local", "skipped", None, objects_skipped or "nicht gelaufen"
                )
    return True


def fail(db: Database, photo_id: int, error: str) -> str:
    """An attempt failed: back to `pending` until MAX_ATTEMPTS, then `failed`.
    Returns the new state."""
    with db.tx() as c:
        row = c.execute(
            "SELECT state, attempts FROM wall_analysis WHERE photo_id=?", (photo_id,)
        ).fetchone()
        if row is None:
            return "gone"
        state = "failed" if int(row["attempts"]) >= MAX_ATTEMPTS else "pending"
        _upsert(c, photo_id, state=state, error=error[:200], finished_at=now_iso())
        if state == "failed":
            _final_local_run(db, photo_id, "failed", error)
    return state


def skip(db: Database, photo_id: int, reason: str) -> None:
    with db.tx() as c:
        _upsert(c, photo_id, state="skipped", error=reason[:200], finished_at=now_iso())
        _final_local_run(db, photo_id, "skipped", reason)


def _final_local_run(db: Database, photo_id: int, state: objects.RunState, error: str) -> None:
    """The photo is final without objects: record the `local` run as such."""
    if not objects.has_run(db, photo_id, "local"):
        objects.record_run(db, photo_id, "local", state, None, error)


def recover_stale(db: Database) -> int:
    """At worker start: rows left `running` by a worker that died are retried
    (or `failed` once they used up their attempts)."""
    with db.tx() as c:
        rows = c.execute(
            "SELECT photo_id, attempts FROM wall_analysis WHERE state='running'"
        ).fetchall()
        for row in rows:
            state = "failed" if int(row["attempts"]) >= MAX_ATTEMPTS else "pending"
            _upsert(c, row["photo_id"], state=state, error=ABORTED, finished_at=now_iso())
            if state == "failed":
                _final_local_run(db, row["photo_id"], "failed", ABORTED)
    return len(rows)


_DELETED = "SELECT id FROM photos WHERE deleted_at IS NOT NULL"
# per table: what a deleted photo may still have there
_LEFTOVERS = (
    f"SELECT 1 FROM wall_facts WHERE photo_id IN ({_DELETED}) LIMIT 1",
    f"SELECT 1 FROM photo_objects WHERE photo_id IN ({_DELETED}) LIMIT 1",
    f"SELECT 1 FROM photo_detection_runs WHERE photo_id IN ({_DELETED}) LIMIT 1",
    f"SELECT 1 FROM property_scores WHERE photo_id IN ({_DELETED}) LIMIT 1",
    f"SELECT 1 FROM wall_category_verdicts WHERE photo_id IN ({_DELETED}) LIMIT 1",
)


def purge_deleted(db: Database) -> int:
    """Drop everything the analysis keeps of deleted photos: facts, objects,
    detection runs, property scores, rows; verdicts keep their text but lose
    the photo. The row holding the highest rev stays until a later write (a
    reused rev would hide a change from pollers); its data is emptied already."""
    if db.one(
        "SELECT 1 FROM wall_analysis a JOIN photos p ON p.id = a.photo_id "
        "WHERE p.deleted_at IS NOT NULL AND (a.data != '{}' OR a.rev < "
        "(SELECT MAX(rev) FROM wall_analysis)) LIMIT 1"
    ) is None and all(db.one(sql) is None for sql in _LEFTOVERS):  # fmt: skip
        return 0
    deleted = _DELETED
    with db.tx() as c:
        c.execute(f"DELETE FROM wall_facts WHERE photo_id IN ({deleted})")
        c.execute(f"DELETE FROM photo_objects WHERE photo_id IN ({deleted})")
        c.execute(f"DELETE FROM photo_detection_runs WHERE photo_id IN ({deleted})")
        c.execute(f"DELETE FROM property_scores WHERE photo_id IN ({deleted})")
        c.execute(
            "UPDATE wall_category_verdicts SET photo_id = NULL, object_idx = NULL "
            f"WHERE photo_id IN ({deleted})"
        )
        n = c.execute(
            f"DELETE FROM wall_analysis WHERE photo_id IN ({deleted}) "
            "AND rev < (SELECT MAX(rev) FROM wall_analysis)"
        ).rowcount
        c.execute(
            f"UPDATE wall_analysis SET data='{{}}', versions='{{}}' WHERE photo_id IN ({deleted})"
        )
    return int(n)


def get(db: Database, photo_id: int) -> AnalysisRow | None:
    row = db.one("SELECT * FROM wall_analysis WHERE photo_id=?", (photo_id,))
    if row is None:
        return None
    return AnalysisRow(
        photo_id=row["photo_id"], state=row["state"], attempts=row["attempts"],
        error=row["error"], versions=json.loads(row["versions"] or "{}"),
        data=json.loads(row["data"] or "{}"), rev=row["rev"], started_at=row["started_at"],
        finished_at=row["finished_at"],
    )  # fmt: skip


def facts(db: Database, photo_id: int) -> dict[str, float]:
    rows = db.all("SELECT key, value FROM wall_facts WHERE photo_id=? ORDER BY key", (photo_id,))
    return {r["key"]: float(r["value"]) for r in rows}


def counts(db: Database) -> dict[str, int]:
    """Photos per state (photos without a row count as pending); deleted ones never."""
    rows = db.all(
        "SELECT COALESCE(a.state, 'pending') AS state, COUNT(*) AS n FROM photos p "
        "LEFT JOIN wall_analysis a ON a.photo_id = p.id WHERE p.deleted_at IS NULL "
        "GROUP BY 1"
    )
    out = dict.fromkeys(STATES, 0)
    for r in rows:
        out[r["state"]] = out.get(r["state"], 0) + int(r["n"])
    out["total"] = sum(out[s] for s in STATES)
    return out


def queue(db: Database) -> dict[str, Any]:
    """The work queue: photos waiting (no row or `pending`), the one running,
    and how long the oldest waiting photo has waited (seconds; None: none)."""
    row = db.one(
        "SELECT COUNT(*) AS n, MIN(p.created_at) AS oldest FROM photos p "
        f"LEFT JOIN wall_analysis a ON a.photo_id = p.id WHERE {_NEEDS_WORK}"
    )
    running = db.one(
        "SELECT COUNT(*) FROM wall_analysis a JOIN photos p ON p.id = a.photo_id "
        "WHERE a.state = 'running' AND p.deleted_at IS NULL"
    )
    oldest: float | None = None
    if row is not None and row["oldest"]:
        try:
            oldest = max(
                0.0, (datetime.now(UTC) - datetime.fromisoformat(row["oldest"])).total_seconds()
            )
        except ValueError:
            oldest = None
    return {
        "pending": int(row["n"]) if row is not None else 0,
        "running": int(running[0]) if running is not None else 0,
        "oldest_pending_s": round(oldest) if oldest is not None else None,
    }


# ------------------------------------------------------------ settings keys


def disabled_analyzers(app_settings: AppSettingsRepo) -> set[str]:
    raw = app_settings.get(ANALYZERS_KEY)
    if "disabled" not in raw or not isinstance(raw["disabled"], list):
        return set(DEFAULT_DISABLED)
    return {str(n) for n in raw["disabled"] if n in BY_NAME and n not in ALWAYS_ON}


def analyzer_settings(app_settings: AppSettingsRepo) -> dict[str, dict[str, float]]:
    """Every analyzer's settings with the defaults filled in (stored values
    outside the allowed range are ignored)."""
    raw = app_settings.get(ANALYZERS_KEY).get("settings")
    stored = raw if isinstance(raw, dict) else {}
    out: dict[str, dict[str, float]] = {}
    for name, specs in SETTINGS.items():
        values = settings_defaults(name)
        mine = stored.get(name)
        if isinstance(mine, dict):
            for spec in specs:
                v = mine.get(spec.key)
                if (
                    isinstance(v, int | float)
                    and not isinstance(v, bool)
                    and spec.min <= v <= spec.max
                ):
                    values[spec.key] = int(v) if spec.integer else float(v)
        out[name] = values
    return out


def save_source_labels(app_settings: AppSettingsRepo, labels: Mapping[str, SourceLabels]) -> None:
    value = {
        ext_id: {
            "title": s.title,
            "labels": dict(s.labels),
            "values": {k: dict(v) for k, v in s.values.items()},
        }
        for ext_id, s in labels.items()
    }
    if app_settings.get(SOURCES_KEY) != value:
        app_settings.put(SOURCES_KEY, value, at=now_iso())


def source_labels(app_settings: AppSettingsRepo) -> dict[str, SourceLabels]:
    out: dict[str, SourceLabels] = {}
    for ext_id, raw in app_settings.get(SOURCES_KEY).items():
        if not isinstance(raw, dict) or not isinstance(raw.get("title"), str):
            continue
        labels = raw.get("labels")
        values = raw.get("values")
        labels = labels if isinstance(labels, dict) else {}
        values = values if isinstance(values, dict) else {}
        out[str(ext_id)] = SourceLabels(
            title=raw["title"],
            labels={str(k): str(v) for k, v in labels.items()},
            values={
                str(k): {str(a): str(b) for a, b in v.items()}
                for k, v in values.items()
                if isinstance(v, dict)
            },
        )
    return out


def save_disabled(
    app_settings: AppSettingsRepo, names: set[str], *, by: str,
    settings: Mapping[str, Mapping[str, float]] | None = None,
) -> None:  # fmt: skip
    """Store the complete disabled set (and, when given, every analyzer's
    settings; else the stored ones stay)."""
    raw = app_settings.get(ANALYZERS_KEY).get("settings")
    kept = settings if settings is not None else (raw if isinstance(raw, dict) else {})
    app_settings.put(
        ANALYZERS_KEY,
        {
            "disabled": sorted(names - ALWAYS_ON),
            "settings": {k: dict(v) for k, v in kept.items()},
            "by": by,
        },
        at=now_iso(),
    )
