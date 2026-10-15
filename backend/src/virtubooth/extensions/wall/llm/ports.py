"""D1's ports (PLAN-NIGHT §4.1) as the LLM code calls them.

D1 builds `enrich/objects.py`, `enrich/engine.py` and `enrich/testjobs.py` in
parallel. Until INT2 merges both, every function here uses D1's module when it
is importable and otherwise a minimal fallback on the migration-11 tables (the
tests run on these). INT2: replace the bodies with plain calls into D1's
modules and delete everything marked FALLBACK.

Nothing here sends anything anywhere: these are database reads and writes.
"""

from __future__ import annotations

import importlib
import json
import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal

from ....core.clock import now_iso
from ....db.database import Database

if TYPE_CHECKING:
    from ....runtime import Core

log = logging.getLogger("virtubooth.llm")

_ENRICH = "virtubooth.extensions.wall.enrich"


def _d1(name: str) -> ModuleType | None:
    """D1's module `enrich.<name>`, None while it does not exist."""
    try:
        return importlib.import_module(f"{_ENRICH}.{name}")
    except ModuleNotFoundError as exc:
        if exc.name != f"{_ENRICH}.{name}":
            raise
        return None


# ------------------------------------------------------------------ types


@dataclass(frozen=True)
class DetectedObject:
    label: str  # canonical lower-case English, singular
    label_de: str
    score: float  # 0..1
    box: tuple[float, float, float, float] | None  # x, y, w, h in 0..1, top-left origin


@dataclass(frozen=True)
class StoredObject(DetectedObject):
    idx: int = 0
    source: str = ""
    model: str = ""


class FrozenError(Exception):
    """The source already ran for this photo."""


class WorkerOff(Exception):
    """The analysis worker is not running (test image: 409 `worker_off`)."""


@dataclass(frozen=True)
class Winner:
    photo_id: int
    value: float | None
    label: str
    object_idx: int | None


@dataclass
class TestRun:
    __test__ = False  # not a pytest class

    width: int
    height: int
    facts: dict[str, float] = field(default_factory=dict)
    boxes: list[dict[str, Any]] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)
    objects: list[DetectedObject] = field(default_factory=list)
    durations_ms: dict[str, int] = field(default_factory=dict)
    error: str | None = None


RunState = Literal["done", "failed", "skipped"]


def _is_frozen(exc: BaseException) -> bool:
    return isinstance(exc, FrozenError) or type(exc).__name__ == "FrozenError"


# ---------------------------------------------------------------- objects


def append(
    db: Database, photo_id: int, source: str, model: str, objs: Sequence[DetectedObject]
) -> list[int]:
    """Append `objs` to the photo's list (idx continues) and record the run as
    done. Raises FrozenError when `source` already ran for the photo."""
    d1 = _d1("objects")
    if d1 is not None:
        theirs = [d1.DetectedObject(o.label, o.label_de, o.score, o.box) for o in objs]
        try:
            return list(d1.append(db, photo_id, source, model, theirs))
        except Exception as exc:
            if _is_frozen(exc):
                raise FrozenError(str(exc)) from exc
            raise
    # FALLBACK
    at = now_iso()
    with db.tx() as c:
        if c.execute(
            "SELECT 1 FROM photo_detection_runs WHERE photo_id=? AND source=?", (photo_id, source)
        ).fetchone():
            raise FrozenError(f"{source} already ran for photo {photo_id}")
        start = c.execute(
            "SELECT COALESCE(MAX(idx) + 1, 0) FROM photo_objects WHERE photo_id=?", (photo_id,)
        ).fetchone()[0]
        idxs = []
        for n, o in enumerate(objs):
            x, y, w, h = o.box if o.box is not None else (None, None, None, None)
            c.execute(
                "INSERT INTO photo_objects (photo_id, idx, label, label_de, score, x, y, w, h, "
                "source, model, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (photo_id, start + n, o.label, o.label_de, o.score, x, y, w, h, source, model, at),
            )
            idxs.append(start + n)
        c.execute(
            "INSERT INTO photo_detection_runs (photo_id, source, state, model, error, objects, "
            "created_at) VALUES (?,?,?,?,?,?,?)",
            (photo_id, source, "done", model, None, len(objs), at),
        )
        # walls refetch the photo (rev is bookkeeping, not frozen data)
        c.execute(
            "UPDATE wall_analysis SET rev=(SELECT COALESCE(MAX(rev), 0) + 1 FROM wall_analysis) "
            "WHERE photo_id=?",
            (photo_id,),
        )
    return idxs


def record_run(
    db: Database,
    photo_id: int,
    source: str,
    state: RunState,
    model: str | None,
    error: str | None,
) -> None:
    d1 = _d1("objects")
    if d1 is not None:
        try:
            d1.record_run(db, photo_id, source, state, model, error)
        except Exception as exc:
            if _is_frozen(exc):
                raise FrozenError(str(exc)) from exc
            raise
        return
    # FALLBACK
    with db.tx() as c:
        if c.execute(
            "SELECT 1 FROM photo_detection_runs WHERE photo_id=? AND source=?", (photo_id, source)
        ).fetchone():
            raise FrozenError(f"{source} already ran for photo {photo_id}")
        c.execute(
            "INSERT INTO photo_detection_runs (photo_id, source, state, model, error, objects, "
            "created_at) VALUES (?,?,?,?,?,0,?)",
            (photo_id, source, state, model, error, now_iso()),
        )


def objects_of(db: Database, photo_ids: Sequence[int]) -> dict[int, list[StoredObject]]:
    """Each photo's objects in idx order (photos without objects are left out)."""
    d1 = _d1("objects")
    if d1 is not None:
        found: dict[int, list[Any]] = d1.objects_of(db, photo_ids)
        return {
            pid: [
                StoredObject(o.label, o.label_de, o.score, o.box, o.idx, o.source, o.model)
                for o in objs
            ]
            for pid, objs in found.items()
        }
    # FALLBACK
    out: dict[int, list[StoredObject]] = {}
    ids = list(dict.fromkeys(int(i) for i in photo_ids))
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        marks = ",".join("?" for _ in chunk)
        for r in db.all(
            f"SELECT * FROM photo_objects WHERE photo_id IN ({marks}) ORDER BY photo_id, idx",
            chunk,
        ):
            box = None if r["x"] is None else (r["x"], r["y"], r["w"], r["h"])
            out.setdefault(r["photo_id"], []).append(
                StoredObject(
                    r["label"], r["label_de"], r["score"], box, r["idx"], r["source"], r["model"]
                )
            )
    return out


# Photos an external source may still see: not deleted or hidden, the local
# pipeline finished, the guest opted out of neither the analysis nor external AI.
# (Same rule as D1's eligible_for_external; also used for counting.)
_ELIGIBLE_SQL = (
    "FROM photos p JOIN users u ON u.id = p.user_id "
    "JOIN wall_analysis a ON a.photo_id = p.id "
    "WHERE p.deleted_at IS NULL AND p.hidden_at IS NULL "
    "AND a.state IN ('done', 'failed', 'skipped') "
    "AND u.analysis_opt_out = 0 AND u.ai_opt_out = 0 AND u.banned_at IS NULL "
    "AND NOT EXISTS (SELECT 1 FROM photo_detection_runs r "
    "WHERE r.photo_id = p.id AND r.source = ?)"
)


def eligible_for_external(db: Database, source: str, limit: int) -> list[int]:
    """Photo ids an external detector may still run on, newest first."""
    d1 = _d1("objects")
    if d1 is not None:
        return list(d1.eligible_for_external(db, source, limit))
    # FALLBACK
    rows = db.all(
        f"SELECT p.id {_ELIGIBLE_SQL} ORDER BY p.created_at DESC, p.id DESC LIMIT ?",
        (source, limit),
    )
    return [r["id"] for r in rows]


def count_eligible(db: Database, source: str) -> int:
    row = db.one(f"SELECT COUNT(*) AS n {_ELIGIBLE_SQL}", (source,))
    return int(row["n"]) if row else 0


# ------------------------------------------------------------- categories


def category_specs(db: Database) -> list[tuple[str, bool, dict[str, Any]]]:
    """(id, enabled, spec) of every category, in wall order."""
    d1 = _d1("engine")
    if d1 is not None:
        return list(d1.category_specs(db))
    # FALLBACK
    out = []
    for r in db.all("SELECT id, enabled, spec FROM wall_categories ORDER BY position, id"):
        try:
            spec = json.loads(r["spec"])
        except ValueError:
            continue
        if isinstance(spec, dict):
            out.append((r["id"], bool(r["enabled"]), spec))
    return out


def evaluate(core: Core, spec: Mapping[str, Any], limit: int | None = None) -> list[Winner]:
    """The category's current winners as the wall shows them (its filter)."""
    from .. import config as wall_config
    from .. import feed

    flt = feed.photo_filter(core, wall_config.load_config(core.repos.app_settings))
    d1 = _d1("engine")
    if d1 is not None:
        return [
            Winner(w.photo_id, w.value, w.label, w.object_idx)
            for w in d1.evaluate(core, dict(spec), flt, limit)
        ]
    # FALLBACK: enough of PLAN §4.2 for the verdict tests (no label styles)
    return _fallback_evaluate(core.db, spec, flt.sources, flt.not_after, limit)


def _fallback_evaluate(
    db: Database,
    spec: Mapping[str, Any],
    sources: Sequence[str] | None,
    not_after: str,
    limit: int | None,
) -> list[Winner]:
    where = ["p.deleted_at IS NULL", "p.hidden_at IS NULL", "p.created_at <= ?"]
    params: list[Any] = [not_after]
    if sources:
        where.append(f"p.extension IN ({','.join('?' for _ in sources)})")
        params.extend(sources)
    rows = db.all(
        "SELECT p.id, p.user_id, p.created_at FROM photos p JOIN users u ON u.id = p.user_id "
        "JOIN wall_analysis a ON a.photo_id = p.id AND a.state = 'done' "
        f"WHERE {' AND '.join(where)} AND u.analysis_opt_out = 0",
        params,
    )
    ids = [r["id"] for r in rows]
    objs = objects_of(db, ids)
    scores: dict[tuple[str, int], list[float | None]] = {}
    for r in db.all(
        "SELECT lp.name, s.photo_id, s.scores FROM property_scores s "
        "JOIN llm_properties lp ON lp.id = s.property_id"
    ):
        scores[(r["name"], r["photo_id"])] = json.loads(r["scores"])

    def value(key: str, pid: int) -> tuple[Any, int | None]:
        labels = [o.label for o in objs.get(pid, [])]
        if key == "objects":
            return labels, None
        if key == "objects.count":
            return float(len(labels)), None
        if key.startswith("objects.count:"):
            return float(labels.count(key.split(":", 1)[1])), None
        if key.startswith("prop."):
            name, _, agg = key[5:].partition(".")
            arr = scores.get((name, pid))
            if arr is None or len(arr) != len(labels):
                return None, None
            pairs = [(v, i) for i, v in enumerate(arr) if isinstance(v, int | float)]
            if agg.startswith("at:"):
                pairs = [(v, i) for v, i in pairs if labels[i] == agg[3:]]
                agg = "max"
            if not pairs:
                return None, None
            if agg == "max":
                v, i = max(pairs, key=lambda t: (t[0], -t[1]))
                return float(v), i
            if agg == "min":
                v, i = min(pairs, key=lambda t: (t[0], t[1]))
                return float(v), i
            vals = [float(v) for v, _ in pairs]
            if agg == "sum":
                return sum(vals), None
            if agg == "mean":
                return sum(vals) / len(vals), None
            if agg == "count":
                return float(len(vals)), None
            return None, None
        row = db.one("SELECT value FROM wall_facts WHERE photo_id=? AND key=?", (pid, key))
        return (float(row["value"]) if row else None), None

    def holds(cond: Mapping[str, Any], pid: int) -> bool:
        v, _ = value(str(cond.get("value", "")), pid)
        op, operand = cond.get("op"), cond.get("operand")
        if op == "exists":
            return v is not None
        if op == "not_exists":
            return v is None
        if v is None:
            return False
        if op in ("contains", "not_contains", "contains_any"):
            labels = v if isinstance(v, list) else []
            if op == "contains":
                return operand in labels
            if op == "not_contains":
                return operand not in labels
            return any(x in labels for x in (operand or []))
        if not isinstance(v, float):
            return False
        if op == "between" and isinstance(operand, list) and len(operand) == 2:
            return float(operand[0]) <= v <= float(operand[1])
        if isinstance(operand, bool) or not isinstance(operand, int | float):
            return False
        b = float(operand)
        results = {
            "gt": v > b,
            "lt": v < b,
            "gte": v >= b,
            "lte": v <= b,
            "eq": v == b,
            "ne": v != b,
        }
        return results.get(str(op), False)

    select = spec.get("select") or {}
    by = str(select.get("by", ""))
    top = select.get("order", "top") == "top"
    count = int(select.get("count", 3))
    conds = [c for c in spec.get("where") or [] if isinstance(c, Mapping)]
    ranked = []
    for r in rows:
        pid = r["id"]
        if not all(holds(c, pid) for c in conds):
            continue
        v, idx = value(by, pid)
        if not isinstance(v, float):
            continue
        ranked.append((v, r["created_at"], pid, r["user_id"], idx))
    # best first, ties: the newer photo first
    ranked.sort(key=lambda t: (t[1], t[2]), reverse=True)
    ranked.sort(key=lambda t: t[0], reverse=top)  # stable: ties stay newest first
    out: list[Winner] = []
    seen_users: set[int] = set()
    for v, _, pid, uid, idx in ranked:
        if select.get("one_per_guest") and uid in seen_users:
            continue
        seen_users.add(uid)
        out.append(Winner(pid, v, f"{v:g}", idx))
        if len(out) >= min(count, limit or count):
            break
    return out


# ------------------------------------------------------------ test image


def analyzer_names() -> set[str]:
    from ..enrich.analyzers import BY_NAME

    return set(BY_NAME)


def submit_test(
    core: Core, image: bytes, analyzers: Collection[str] | None, timeout_s: float = 30
) -> TestRun:
    """The local pipeline on a test image (never stored). Raises WorkerOff."""
    d1 = _d1("testjobs")
    if d1 is None:
        # FALLBACK: D1's worker side does not exist on this branch
        raise WorkerOff("no test-image worker")
    try:
        run = d1.submit(core, image, analyzers, timeout_s)
    except Exception as exc:
        if type(exc).__name__ == "WorkerOff":
            raise WorkerOff(str(exc)) from exc
        raise
    return TestRun(
        width=run.width,
        height=run.height,
        facts=dict(run.facts),
        boxes=list(run.boxes),
        details=list(run.details),
        objects=[DetectedObject(o.label, o.label_de, o.score, o.box) for o in run.objects],
        durations_ms=dict(run.durations_ms),
        error=run.error,
    )


# ------------------------------------------------------- analyzer switch


def set_local_objects(core: Core, enabled: bool, *, by: str) -> None:
    """`detect.local`: switch D1's `objects` analyzer in `x.wall.analyzers`
    (only the `disabled` list changes; D1's other fields stay)."""
    from ..enrich import jobs

    repo = core.repos.app_settings
    raw = repo.get(jobs.ANALYZERS_KEY)
    disabled = set(jobs.disabled_analyzers(repo))
    if enabled:
        disabled.discard("objects")
    else:
        disabled.add("objects")
    if raw.get("disabled") is not None and set(raw["disabled"]) == disabled:
        return
    repo.put(jobs.ANALYZERS_KEY, {**raw, "disabled": sorted(disabled), "by": by}, at=now_iso())
