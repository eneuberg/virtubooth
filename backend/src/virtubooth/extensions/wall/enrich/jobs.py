"""Analysis jobs: rows in `wall_analysis` (migration 9), found by a DB scan.

A photo needs analysis when it has no row or its row is `pending` (backfill and
„neu analysieren“ need no queue). The worker claims the newest such photo,
marks it `running`, and finishes it as `done` (facts replaced), `failed` (after
MAX_ATTEMPTS) or `skipped` (no file). Every write sets `rev = MAX(rev) + 1`, a
global change counter the app polls (`changes_since`).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ....core.clock import now_iso
from ....db.database import Database
from ....repositories.app_settings import AppSettingsRepo
from .analyzers import ALWAYS_ON, BY_NAME, DEFAULT_DISABLED
from .pipeline import PhotoInfo

MAX_ATTEMPTS = 2
STATES = ("pending", "running", "done", "failed", "skipped")
ABORTED = "Analyse abgebrochen"

# settings keys: {disabled: [names], by} (the complete disabled set; absent =
# DEFAULT_DISABLED) and the worker's heartbeat {pid, beat_at, ml, models_missing}
ANALYZERS_KEY = "x.wall.analyzers"
WORKER_KEY = "x.wall.worker"

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
            "SELECT p.id, p.public_id, p.extension, p.filename, p.created_at, p.width, "
            "p.height, p.meta, u.name AS user_name, COALESCE(a.attempts, 0) AS attempts "
            "FROM photos p JOIN users u ON u.id = p.user_id "
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
    )  # fmt: skip


def finish(
    db: Database, photo_id: int, *, facts: Mapping[str, float], data: Mapping[str, Any],
    versions: Mapping[str, str],
) -> bool:  # fmt: skip
    """Store a finished analysis. False (nothing written) when the row is no
    longer `running` (rerun requested meanwhile, or purged)."""
    with db.tx() as c:
        row = c.execute("SELECT state FROM wall_analysis WHERE photo_id=?", (photo_id,)).fetchone()
        if row is None or row["state"] != "running":
            return False
        c.execute("DELETE FROM wall_facts WHERE photo_id=?", (photo_id,))
        c.executemany(
            "INSERT INTO wall_facts (photo_id, key, value) VALUES (?,?,?)",
            [(photo_id, k, float(v)) for k, v in sorted(facts.items())],
        )
        _upsert(
            c, photo_id, state="done", error=None, data=json.dumps(data, ensure_ascii=False),
            versions=json.dumps(dict(versions)), finished_at=now_iso(),
        )  # fmt: skip
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
    return state


def skip(db: Database, photo_id: int, reason: str) -> None:
    with db.tx() as c:
        _upsert(c, photo_id, state="skipped", error=reason[:200], finished_at=now_iso())


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
    return len(rows)


def purge_deleted(db: Database) -> int:
    """Drop facts and rows of deleted photos. The row holding the highest rev
    stays until a later write (a reused rev would hide a change from pollers);
    its data is emptied already."""
    if db.one(
        "SELECT 1 FROM wall_analysis a JOIN photos p ON p.id = a.photo_id "
        "WHERE p.deleted_at IS NOT NULL AND (a.data != '{}' OR a.rev < "
        "(SELECT MAX(rev) FROM wall_analysis)) LIMIT 1"
    ) is None and db.one(
        "SELECT 1 FROM wall_facts f JOIN photos p ON p.id = f.photo_id "
        "WHERE p.deleted_at IS NOT NULL LIMIT 1"
    ) is None:  # fmt: skip
        return 0
    deleted = "SELECT id FROM photos WHERE deleted_at IS NOT NULL"
    with db.tx() as c:
        c.execute(f"DELETE FROM wall_facts WHERE photo_id IN ({deleted})")
        n = c.execute(
            f"DELETE FROM wall_analysis WHERE photo_id IN ({deleted}) "
            "AND rev < (SELECT MAX(rev) FROM wall_analysis)"
        ).rowcount
        c.execute(
            f"UPDATE wall_analysis SET data='{{}}', versions='{{}}' WHERE photo_id IN ({deleted})"
        )
    return int(n)


def request(db: Database, photo_id: int) -> None:
    """Analyse this photo again („Neu analysieren“)."""
    with db.tx() as c:
        _upsert(c, photo_id, state="pending", attempts=0, error=None)


def rerun(db: Database, scope: Literal["failed", "all"]) -> int:
    """Queue every failed (or every analysed) photo again. Each row gets its
    own rev, so pollers that read in pages never skip one."""
    where = "state='failed'" if scope == "failed" else "state != 'pending'"
    with db.tx() as c:
        ids = [
            r[0]
            for r in c.execute(
                "SELECT a.photo_id FROM wall_analysis a JOIN photos p ON p.id = a.photo_id "
                f"WHERE p.deleted_at IS NULL AND a.{where} ORDER BY a.photo_id"
            )
        ]
        base = _next_rev(c)
        c.executemany(
            "UPDATE wall_analysis SET state='pending', attempts=0, error=NULL, rev=? "
            "WHERE photo_id=?",
            [(base + i, pid) for i, pid in enumerate(ids)],
        )
    return len(ids)


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


# ------------------------------------------------------------ settings keys


def disabled_analyzers(app_settings: AppSettingsRepo) -> set[str]:
    raw = app_settings.get(ANALYZERS_KEY)
    if "disabled" not in raw or not isinstance(raw["disabled"], list):
        return set(DEFAULT_DISABLED)
    return {str(n) for n in raw["disabled"] if n in BY_NAME and n not in ALWAYS_ON}


def save_disabled(app_settings: AppSettingsRepo, names: set[str], *, by: str) -> None:
    app_settings.put(ANALYZERS_KEY, {"disabled": sorted(names - ALWAYS_ON), "by": by}, at=now_iso())
