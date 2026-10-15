"""A photo's object lists (migrations 11, 14, 15): frozen, append-only.

Since v15 object detection is either/or: a new photo gets the local detector's
list OR the external AI's (whichever was active when the pipeline finished it),
so its merged list is exactly that one source's list (the merge has nothing to
link). Photos from before that may have both lists, merged as below; they stay
as they are, and so do their idx and the property scores that index them.

Each source keeps its own list as it found it (`photo_source_objects`: the
local model's, the external AI's), and the photo has ONE merged list
(`photo_objects`, idx 0, 1, 2, …) that the poller, the categories and the wall
work on (merge.py): the first source's objects become its entries; a later
source's object that is the same thing as an entry (label, frame overlap)
links to it, any other is appended — so an idx never changes and the property
scores (indexed by it) stay valid. The local detector writes when the worker
finishes the photo; an external source (Claude, an EU provider) later. Each
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
from typing import TYPE_CHECKING, Literal

from ....core.clock import now_iso
from ....db.database import Database

if TYPE_CHECKING:
    from .merge import Entry

RunState = Literal["done", "failed", "skipped"]
SOURCES = ("local", "claude", "mistral", "deutschlandgpt")
_CHUNK = 500


@dataclass(frozen=True)
class DetectedObject:
    label: str  # canonical lower-case English, singular ("wine glass")
    label_de: str  # German display label ("Weinglas")
    score: float  # 0..1
    box: tuple[float, float, float, float] | None  # x, y, w, h in 0..1, top-left origin


@dataclass(frozen=True)
class StoredObject(DetectedObject):
    """An entry of the merged list. `source`/`model`: the source that added it;
    `sources`: every source whose object is (linked to) this entry."""

    idx: int
    source: str
    model: str
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceObject(DetectedObject):
    """An object as its source found it, and the merged entry it is."""

    pos: int
    source: str
    model: str
    merged_idx: int


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


def _box(o: DetectedObject) -> tuple[float | None, ...]:
    return tuple(_clip01(v) for v in o.box) if o.box is not None else (None,) * 4


def append(
    db: Database, photo_id: int, source: str, model: str, objs: Sequence[DetectedObject]
) -> list[int]:
    """Store `objs` (in this order) as the source's list, merge them into the
    photo's merged list and record the source's `done` run. Returns, per object,
    the merged idx it became or was linked to. FrozenError when the source ran."""
    from . import merge

    with db.tx() as c:
        _check_new(c, photo_id, source)
        entries = _entries(c, photo_id)
        links = merge.plan(entries, objs, source)
        start = len(entries)
        at = now_iso()
        merged_rows: list[tuple[object, ...]] = []
        source_rows: list[tuple[object, ...]] = []
        out: list[int] = []
        for pos, (o, link) in enumerate(zip(objs, links, strict=True)):
            if link is None:
                link = start + len(merged_rows)
                label, label_de = merge.canonical(o.label, o.label_de)
                merged_rows.append(
                    (photo_id, link, label, label_de, _clip01(o.score), *_box(o), source,
                     model, at)
                )  # fmt: skip
            out.append(link)
            source_rows.append(
                (photo_id, source, pos, o.label, o.label_de, _clip01(o.score), *_box(o), model,
                 link, at)
            )  # fmt: skip
        c.executemany(
            "INSERT INTO photo_objects (photo_id, idx, label, label_de, score, x, y, w, h, "
            "source, model, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            merged_rows,
        )
        c.executemany(
            "INSERT INTO photo_source_objects (photo_id, source, pos, label, label_de, score, "
            "x, y, w, h, model, merged_idx, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            source_rows,
        )
        c.execute(
            "INSERT INTO photo_detection_runs (photo_id, source, state, model, error, objects, "
            "created_at) VALUES (?, ?, 'done', ?, NULL, ?, ?)",
            (photo_id, source, model, len(source_rows), at),
        )
        _bump_rev(c, photo_id)
    return out


def _entries(c: sqlite3.Connection, photo_id: int) -> list[Entry]:
    """The photo's merged list as the merge sees it (with the linked sources)."""
    from .merge import Entry

    linked: dict[int, set[str]] = {}
    for r in c.execute(
        "SELECT merged_idx, source FROM photo_source_objects WHERE photo_id=?", (photo_id,)
    ):
        linked.setdefault(int(r[0]), set()).add(r[1])
    out = []
    for r in c.execute(
        "SELECT idx, label, label_de, x, y, w, h, source FROM photo_objects WHERE photo_id=? "
        "ORDER BY idx",
        (photo_id,),
    ):
        box = None if r[3] is None else (r[3], r[4], r[5], r[6])
        sources = frozenset(linked.get(int(r[0]), {r[7]}))
        out.append(Entry(int(r[0]), r[1], r[2], box, sources))
    return out


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


def _chunks(ids: Sequence[int]) -> list[list[int]]:
    unique = list(dict.fromkeys(int(i) for i in ids))
    return [unique[i : i + _CHUNK] for i in range(0, len(unique), _CHUNK)]


def objects_of(db: Database, photo_ids: Sequence[int]) -> dict[int, list[StoredObject]]:
    """Each photo's MERGED list in idx order, with the sources of each entry
    (photos without any are left out)."""
    out: dict[int, list[StoredObject]] = {}
    for chunk in _chunks(photo_ids):
        marks = ", ".join("?" for _ in chunk)
        linked: dict[tuple[int, int], list[str]] = {}
        for r in db.all(
            "SELECT photo_id, merged_idx, source FROM photo_source_objects "
            f"WHERE photo_id IN ({marks}) ORDER BY photo_id, merged_idx, rowid",
            chunk,
        ):
            linked.setdefault((int(r[0]), int(r[1])), []).append(r[2])
        for r in db.all(
            "SELECT photo_id, idx, label, label_de, score, x, y, w, h, source, model "
            f"FROM photo_objects WHERE photo_id IN ({marks}) ORDER BY photo_id, idx",
            chunk,
        ):
            box = None if r["x"] is None else (r["x"], r["y"], r["w"], r["h"])
            pid, idx = int(r["photo_id"]), int(r["idx"])
            out.setdefault(pid, []).append(
                StoredObject(
                    label=r["label"],
                    label_de=r["label_de"],
                    score=float(r["score"]),
                    box=box,
                    idx=idx,
                    source=r["source"],
                    model=r["model"],
                    sources=tuple(linked.get((pid, idx), [r["source"]])),
                )
            )
    return out


def source_objects_of(db: Database, photo_id: int) -> dict[str, list[SourceObject]]:
    """The photo's list per source (source → objects in its own order)."""
    out: dict[str, list[SourceObject]] = {}
    for r in db.all(
        "SELECT source, pos, label, label_de, score, x, y, w, h, model, merged_idx "
        "FROM photo_source_objects WHERE photo_id=? ORDER BY rowid",
        (photo_id,),
    ):
        box = None if r["x"] is None else (r["x"], r["y"], r["w"], r["h"])
        out.setdefault(r["source"], []).append(
            SourceObject(
                label=r["label"],
                label_de=r["label_de"],
                score=float(r["score"]),
                box=box,
                pos=int(r["pos"]),
                source=r["source"],
                model=r["model"],
                merged_idx=int(r["merged_idx"]),
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


# Photos the external AI may still see (also counted for the admin): the pipeline
# finished them WHILE the AI detector was active (`ai_detect`, v15: no backfill of
# older photos), no external source has run for them yet (one AI list per photo,
# also after a provider change), they are visible and their guest is not banned
# and has neither opt-out on (live flags). The `source` parameter is kept for the
# callers; any non-local run counts.
_ELIGIBLE_SQL = (
    "FROM photos p JOIN users u ON u.id = p.user_id "
    "JOIN wall_analysis a ON a.photo_id = p.id "
    "WHERE a.state = 'done' AND a.ai_detect = 1 AND ? IS NOT NULL "
    "AND p.hidden_at IS NULL AND p.deleted_at IS NULL "
    "AND u.analysis_opt_out = 0 AND u.ai_opt_out = 0 AND u.banned_at IS NULL "
    "AND NOT EXISTS (SELECT 1 FROM photo_detection_runs r "
    "                WHERE r.photo_id = p.id AND r.source != 'local') "
)


def eligible_for_external(db: Database, source: str, limit: int) -> list[int]:
    """Photo ids the external AI may still analyse, newest first: the pipeline
    finished them while the AI detector was active (`wall_analysis.ai_detect`),
    no external source ran for them, they are visible (not hidden, not deleted)
    and their guest is not banned and has neither the analysis opt-out nor the
    external-AI opt-out on (live flags)."""
    rows = db.all(
        f"SELECT p.id {_ELIGIBLE_SQL} ORDER BY p.id DESC LIMIT ?", (source, max(0, int(limit)))
    )
    return [int(r[0]) for r in rows]


def count_eligible_for_external(db: Database, source: str) -> int:
    """How many photos `eligible_for_external` would still hand out."""
    row = db.one(f"SELECT COUNT(*) {_ELIGIBLE_SQL}", (source,))
    return int(row[0]) if row is not None else 0
