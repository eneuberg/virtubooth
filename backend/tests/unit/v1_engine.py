"""The v1 category engine, frozen (main 8916f49, enrich/engine.py before
categories v2) as a test fixture: the golden test compares the v2 engine on
converted specs with exactly this. Never change it."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from virtubooth.db.database import Database
from virtubooth.extensions.wall.enrich import clock
from virtubooth.extensions.wall.enrich.engine import PhotoFilter
from virtubooth.extensions.wall.enrich.spec_v1 import ValueRef
from virtubooth.extensions.wall.enrich.spec_v1 import parse_key as parse

LABEL_OPS = ("contains", "not_contains", "contains_any")
EPS = 1e-9


@dataclass
class PhotoData:
    facts: dict[str, float] = field(default_factory=dict)
    objects: list[tuple[int, str, str, float]] = field(default_factory=list)
    detected: bool = False
    props: dict[str, list[float | None]] = field(default_factory=dict)


def snapshot(db: Database) -> dict[int, PhotoData]:
    photos: dict[int, PhotoData] = {}
    alive = "SELECT id FROM photos WHERE deleted_at IS NULL"
    for r in db.all(f"SELECT photo_id, key, value FROM wall_facts WHERE photo_id IN ({alive})"):
        photos.setdefault(int(r[0]), PhotoData()).facts[r[1]] = float(r[2])
    for r in db.all(
        "SELECT photo_id, idx, label, label_de, score FROM photo_objects "
        f"WHERE photo_id IN ({alive}) ORDER BY photo_id, idx"
    ):
        photos.setdefault(int(r[0]), PhotoData()).objects.append(
            (int(r[1]), r[2], r[3], float(r[4]))
        )
    for r in db.all(
        f"SELECT DISTINCT photo_id FROM photo_detection_runs WHERE photo_id IN ({alive})"
    ):
        photos.setdefault(int(r[0]), PhotoData()).detected = True
    for r in db.all(
        "SELECT s.photo_id, p.name, s.scores FROM property_scores s "
        f"JOIN llm_properties p ON p.id = s.property_id WHERE s.photo_id IN ({alive})"
    ):
        raw = json.loads(r[2])
        photos.setdefault(int(r[0]), PhotoData()).props[r[1]] = [
            float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None
            for v in raw
        ]
    return photos


@dataclass(frozen=True)
class Winner:
    photo_id: int
    value: float | None
    label: str
    object_idx: int | None


@dataclass(frozen=True)
class _Row:
    id: int
    user_id: int
    created_at: str


def _visible_rows(db: Database, flt: PhotoFilter) -> list[_Row]:
    sql = (
        "SELECT p.id, p.user_id, p.created_at FROM photos p JOIN users u ON u.id = p.user_id "
        "WHERE p.hidden_at IS NULL AND p.deleted_at IS NULL AND p.created_at <= ? "
        "AND u.analysis_opt_out = 0"
    )
    params: list[Any] = [flt.not_after]
    if flt.sources:
        sql += f" AND p.extension IN ({', '.join('?' for _ in flt.sources)})"
        params += list(flt.sources)
    return [_Row(int(r[0]), int(r[1]), r[2]) for r in db.all(sql, params)]


def _guest_counts(db: Database, flt: PhotoFilter) -> dict[int, int]:
    sql = (
        "SELECT p.user_id, COUNT(*) FROM photos p WHERE p.hidden_at IS NULL "
        "AND p.deleted_at IS NULL AND p.created_at <= ?"
    )
    params: list[Any] = [flt.not_after]
    if flt.sources:
        sql += f" AND p.extension IN ({', '.join('?' for _ in flt.sources)})"
        params += list(flt.sources)
    return {int(r[0]): int(r[1]) for r in db.all(sql + " GROUP BY p.user_id", params)}


class _Ctx:
    def __init__(self, data: Mapping[int, PhotoData], guests: Mapping[int, int]) -> None:
        self.data = data
        self.guests = guests

    def value(self, row: _Row, ref: ValueRef) -> float | list[str] | None:
        d = self.data.get(row.id)
        if ref.kind == "created":
            return clock.unix(row.created_at)
        if ref.kind == "guest_photos":
            return float(self.guests.get(row.user_id, 0))
        if d is None:
            return None
        if ref.kind == "fact":
            assert ref.fact is not None
            return d.facts.get(ref.fact)
        if ref.kind in ("labels", "count", "count_label"):
            if not d.detected and not d.objects:
                return None
            if ref.kind == "labels":
                return [o[1] for o in d.objects]
            if ref.kind == "count":
                return float(len(d.objects))
            return float(sum(1 for o in d.objects if o[1] == ref.label))
        assert ref.prop is not None
        scores = d.props.get(ref.prop)
        if scores is None:
            return None
        if ref.kind == "prop_at":
            labels = {o[0]: o[1] for o in d.objects}
            found = [
                s for i, s in enumerate(scores) if s is not None and labels.get(i) == ref.label
            ]
            return max(found) if found else None
        present = [s for s in scores if s is not None]
        if ref.agg == "count":
            return float(len(present))
        if not present:
            return None
        if ref.agg == "max":
            return max(present)
        if ref.agg == "min":
            return min(present)
        if ref.agg == "sum":
            return float(sum(present))
        return sum(present) / len(present)

    def best_object(self, row: _Row, ref: ValueRef) -> int | None:
        d = self.data.get(row.id)
        if d is None or not d.objects:
            return None
        if ref.kind in ("prop", "prop_at") and ref.prop in d.props:
            scores = d.props[ref.prop]
            labels = {o[0]: o[1] for o in d.objects}
            cands = [
                (s, i) for i, s in enumerate(scores)
                if s is not None and i in labels and (ref.kind == "prop" or labels[i] == ref.label)
            ]  # fmt: skip
            if cands:
                pick = min(cands) if ref.agg == "min" else max(cands, key=lambda c: (c[0], -c[1]))
                return pick[1]
        if ref.kind == "count_label":
            cands2 = [(o[3], -o[0]) for o in d.objects if o[1] == ref.label]
            if cands2:
                return -max(cands2)[1]
        return max(d.objects, key=lambda o: (o[3], -o[0]))[0]

    def label_de(self, row: _Row, idx: int | None) -> str | None:
        d = self.data.get(row.id)
        if d is None or idx is None:
            return None
        return next((o[2] for o in d.objects if o[0] == idx), None)


def _holds(op: str, value: float | list[str] | None, operand: Any) -> bool:
    if op == "exists":
        return value is not None
    if op == "not_exists":
        return value is None
    if value is None:
        return False
    if op in LABEL_OPS:
        if not isinstance(value, list):
            return False
        if op == "contains":
            return operand in value
        if op == "not_contains":
            return operand not in value
        return any(o in value for o in operand)
    if isinstance(value, list):
        return False
    if op == "between":
        lo, hi = float(operand[0]), float(operand[1])
        return lo - EPS <= value <= hi + EPS
    x = float(operand)
    if op == "gt":
        return value > x + EPS
    if op == "lt":
        return value < x - EPS
    if op == "gte":
        return value >= x - EPS
    if op == "lte":
        return value <= x + EPS
    if op == "eq":
        return abs(value - x) <= EPS
    if op == "ne":
        return abs(value - x) > EPS
    return False


def label_text(style: str, value: float | None, one: str, many: str,
               object_label: str | None = None) -> str:  # fmt: skip
    if style == "fixed":
        return one
    if style == "object":
        return object_label or one or "Objekt"
    if value is None:
        return one
    if style == "count":
        n = round(value)
        return f"{n} {one if n == 1 else many}".strip()
    if style == "percent":
        return f"{round(value * 100)} % {one}".strip()
    if style == "number":
        return f"{one} {value:.0f}".strip()
    return f"um {clock.local(value):%H:%M}"


def _sort_key(v: float | list[str] | None, order: str) -> tuple[int, float]:
    if v is None or isinstance(v, list):
        return (1, 0.0)
    return (0, -v if order == "top" else v)


def evaluate(db: Database, spec: Mapping[str, Any], flt: PhotoFilter,
             limit: int | None = None) -> list[Winner]:  # fmt: skip
    """The winners of a validated v1 spec, exactly as v1 picked them."""
    rows = _visible_rows(db, flt)
    sel = spec["select"]
    lab = spec["label"]
    where = [(parse(w["value"]), w["op"], w["operand"]) for w in spec["where"]]
    by = parse(sel["by"])
    then = [(parse(t["by"]), t["order"]) for t in sel["then_by"]]
    shown = parse(lab["value"]) if lab["value"] else by
    assert by is not None and shown is not None
    refs = [r for r, _, _ in where] + [by, shown] + [r for r, _ in then]
    needs_guests = any(r is not None and r.kind == "guest_photos" for r in refs)
    ctx = _Ctx(snapshot(db), _guest_counts(db, flt) if needs_guests else {})
    matched = [
        row for row in rows
        if all(_holds(op, ctx.value(row, ref), operand) for ref, op, operand in where if ref)
    ]  # fmt: skip
    candidates = [r for r in matched if ctx.value(r, shown) is not None]
    candidates.sort(key=lambda r: (r.created_at, r.id), reverse=True)
    candidates.sort(
        key=lambda r: (
            _sort_key(ctx.value(r, by), sel["order"]),
            *(_sort_key(ctx.value(r, ref), order) for ref, order in then if ref),
        )
    )
    want = sel["count"] if limit is None else max(0, min(limit, sel["count"]))
    winners: list[Winner] = []
    guests: set[int] = set()
    for row in candidates:
        if len(winners) >= want:
            break
        if sel["one_per_guest"]:
            if row.user_id in guests:
                continue
            guests.add(row.user_id)
        raw = ctx.value(row, shown)
        value = raw if isinstance(raw, float) else None
        idx: int | None = None
        if lab["style"] == "object" or by.kind in ("prop", "prop_at", "count_label"):
            idx = ctx.best_object(row, by)
        text = label_text(lab["style"], value, lab["one"], lab["many"], ctx.label_de(row, idx))
        winners.append(Winner(row.id, value, text, idx))
    return winners
