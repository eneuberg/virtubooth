"""A photo's object list (`photo_objects`, migration 11): frozen, append-only.

The local detector writes idx 0..n-1 when the worker finishes the photo; an
external source (Claude, an EU provider) appends later, idx continuing. Each
source runs at most once per photo: `photo_detection_runs` holds one row per
(photo, source) — `done` (with its objects), `failed` or `skipped`. A second
run of the same source raises `FrozenError`; UPDATEs abort in the database
(triggers), so nothing written here ever changes. Rows only go when their
photo is deleted (`jobs.purge_deleted`).

Every write bumps the photo's `wall_analysis.rev` (bookkeeping, not frozen),
so open walls get a `photo.update` and the category snapshot is rebuilt.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ....core.clock import now_iso
from ....db.database import Database

RunState = Literal["done", "failed", "skipped"]
SOURCES = ("local", "claude", "mistral")
_CHUNK = 500


@dataclass(frozen=True)
class DetectedObject:
    label: str  # canonical lower-case English, singular ("wine glass")
    label_de: str  # German display label ("Weinglas")
    score: float  # 0..1
    box: tuple[float, float, float, float] | None  # x, y, w, h in 0..1, top-left origin


@dataclass(frozen=True)
class StoredObject(DetectedObject):
    idx: int
    source: str
    model: str


class FrozenError(Exception):
    """This source already ran for this photo (its result is frozen)."""


def _bump_rev(c: sqlite3.Connection, photo_id: int) -> None:
    c.execute(
        "UPDATE wall_analysis SET rev = (SELECT COALESCE(MAX(rev), 0) + 1 FROM wall_analysis) "
        "WHERE photo_id=?",
        (photo_id,),
    )


def _check_new(c: sqlite3.Connection, photo_id: int, source: str) -> None:
    if not source or len(source) > 20:
        raise ValueError(f"bad source {source!r}")
    if c.execute(
        "SELECT 1 FROM photo_detection_runs WHERE photo_id=? AND source=?", (photo_id, source)
    ).fetchone():
        raise FrozenError(f"source {source} already ran for photo {photo_id}")


def _clip01(v: float) -> float:
    return min(1.0, max(0.0, float(v)))


def append(
    db: Database, photo_id: int, source: str, model: str, objs: Sequence[DetectedObject]
) -> list[int]:
    """Append `objs` (in this order) to the photo's list and record the source's
    `done` run. Returns the new idx values. FrozenError when the source ran."""
    with db.tx() as c:
        _check_new(c, photo_id, source)
        start = int(
            c.execute(
                "SELECT COALESCE(MAX(idx) + 1, 0) FROM photo_objects WHERE photo_id=?",
                (photo_id,),
            ).fetchone()[0]
        )
        at = now_iso()
        rows = []
        for i, o in enumerate(objs):
            x, y, w, h = (_clip01(v) for v in o.box) if o.box is not None else (None,) * 4
            rows.append(
                (
                    photo_id,
                    start + i,
                    o.label,
                    o.label_de,
                    _clip01(o.score),
                    x,
                    y,
                    w,
                    h,
                    source,
                    model,
                    at,
                )
            )
        c.executemany(
            "INSERT INTO photo_objects (photo_id, idx, label, label_de, score, x, y, w, h, "
            "source, model, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        c.execute(
            "INSERT INTO photo_detection_runs (photo_id, source, state, model, error, objects, "
            "created_at) VALUES (?, ?, 'done', ?, NULL, ?, ?)",
            (photo_id, source, model, len(rows), at),
        )
        _bump_rev(c, photo_id)
    return [start + i for i in range(len(objs))]


def record_run(
    db: Database, photo_id: int, source: str, state: RunState, model: str | None,
    error: str | None,
) -> None:  # fmt: skip
    """Record a run without objects (`failed`, `skipped`; `done` with none).
    `append` records `done` itself. FrozenError when the source ran."""
    if state not in ("done", "failed", "skipped"):
        raise ValueError(f"bad state {state!r}")
    with db.tx() as c:
        _check_new(c, photo_id, source)
        c.execute(
            "INSERT INTO photo_detection_runs (photo_id, source, state, model, error, objects, "
            "created_at) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (photo_id, source, state, model, (error or None) and error[:200], now_iso()),
        )
        _bump_rev(c, photo_id)


def has_run(db: Database, photo_id: int, source: str) -> bool:
    return (
        db.one(
            "SELECT 1 FROM photo_detection_runs WHERE photo_id=? AND source=?", (photo_id, source)
        )
        is not None
    )


def objects_of(db: Database, photo_ids: Sequence[int]) -> dict[int, list[StoredObject]]:
    """Each photo's objects in idx order (photos without any are left out)."""
    ids = list(dict.fromkeys(int(i) for i in photo_ids))
    out: dict[int, list[StoredObject]] = {}
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start : start + _CHUNK]
        marks = ", ".join("?" for _ in chunk)
        for r in db.all(
            "SELECT photo_id, idx, label, label_de, score, x, y, w, h, source, model "
            f"FROM photo_objects WHERE photo_id IN ({marks}) ORDER BY photo_id, idx",
            chunk,
        ):
            box = None if r["x"] is None else (r["x"], r["y"], r["w"], r["h"])
            out.setdefault(int(r["photo_id"]), []).append(
                StoredObject(
                    label=r["label"],
                    label_de=r["label_de"],
                    score=float(r["score"]),
                    box=box,
                    idx=int(r["idx"]),
                    source=r["source"],
                    model=r["model"],
                )
            )
    return out


def runs_of(db: Database, photo_id: int) -> list[dict[str, str | int | None]]:
    """The photo's detection runs: {source, state, model, error, objects}."""
    return [
        {
            "source": r["source"],
            "state": r["state"],
            "model": r["model"],
            "error": r["error"],
            "objects": int(r["objects"]),
        }
        for r in db.all(
            "SELECT source, state, model, error, objects FROM photo_detection_runs "
            "WHERE photo_id=? ORDER BY rowid",
            (photo_id,),
        )
    ]


def eligible_for_external(db: Database, source: str, limit: int) -> list[int]:
    """Photo ids an external source may still analyse, newest first: the local
    pipeline finished them (`done`/`failed`/`skipped`), `source` has no run
    for them, they are visible (not hidden, not deleted) and their guest has
    neither the analysis opt-out nor the external-AI opt-out on (live flags)."""
    rows = db.all(
        "SELECT p.id FROM photos p JOIN users u ON u.id = p.user_id "
        "JOIN wall_analysis a ON a.photo_id = p.id "
        "WHERE a.state IN ('done', 'failed', 'skipped') "
        "AND p.hidden_at IS NULL AND p.deleted_at IS NULL "
        "AND u.analysis_opt_out = 0 AND u.ai_opt_out = 0 "
        "AND NOT EXISTS (SELECT 1 FROM photo_detection_runs r "
        "                WHERE r.photo_id = p.id AND r.source = ?) "
        "ORDER BY p.id DESC LIMIT ?",
        (source, max(0, int(limit))),
    )
    return [int(r[0]) for r in rows]
