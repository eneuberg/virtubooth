"""Rule-based Live-Wall categories (PLAN-NIGHT N13, §4.2): validate a
CategorySpec, evaluate it, and keep the specs in `wall_categories`.

A spec is conditions (`where`, all must hold) on a photo's values
(`values.py`), a selection (`select`: top/bottom N by a value, tie-breakers,
one photo per guest) and a label. Evaluation runs in Python over a snapshot
of every photo's analysis (facts, objects, property scores) that is cached
until the analysis, the polls or the categories change; visibility and the
guests' opt-out flags are read fresh each time.

Rules:
- winners are visible photos (not hidden, not deleted, from the wall's
  sources, past the delay) of guests without the analysis opt-out (live);
- a condition on a missing value fails (also `ne` and `not_contains`);
- the displayed value (`label.value`, else `select.by`) must exist; missing
  `select.by` / `then_by` values rank last;
- ties: the newer photo first.
"""

from __future__ import annotations

import json
import math
import threading
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ....core.clock import now_iso
from ....db.database import Database
from . import clock
from .values import ValueRef, availability, has_external_objects, parse, properties_of

CATEGORY_ID_RE_TEXT = r"^[a-z][a-z0-9_]{1,40}$"
RESERVED_IDS = frozenset({"order", "preview"})
NUMERIC_OPS = ("gt", "lt", "gte", "lte", "eq", "ne")
OPS = (*NUMERIC_OPS, "between", "exists", "not_exists", "contains", "not_contains",
       "contains_any")  # fmt: skip
LABEL_OPS = ("contains", "not_contains", "contains_any")
STYLES = ("count", "percent", "number", "time", "fixed", "object")
MAX_WHERE = 8
MAX_THEN_BY = 2
MAX_COUNT = 10
MAX_ANY = 20
EPS = 1e-9


@dataclass(frozen=True)
class PhotoFilter:
    """Which photos may win: from these sources (extension ids; None or empty
    = all), created no later than `not_after` (ISO; now − the wall's delay)."""

    sources: tuple[str, ...] | None
    not_after: str


class HasDb(Protocol):
    @property
    def db(self) -> Database: ...


# ------------------------------------------------------------ validation


class InvalidCategory(ValueError):
    """A spec field is invalid; `field` is its German name for the 400."""

    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


def _str(value: Any, field: str, lo: int, hi: int) -> str:
    if not isinstance(value, str):
        raise InvalidCategory(field)
    text = " ".join(value.split())
    if not lo <= len(text) <= hi or any(unicodedata.category(ch) in ("Cc", "Cs") for ch in text):
        raise InvalidCategory(field)
    return text


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise InvalidCategory(field)
    return float(value)


def _is_emoji_part(ch: str) -> bool:
    """A modifier that belongs to the character before it (no own grapheme)."""
    cp = ord(ch)
    return (
        unicodedata.category(ch) in ("Mn", "Me")
        or 0xFE00 <= cp <= 0xFE0F  # variation selectors
        or 0x1F3FB <= cp <= 0x1F3FF  # skin tones
        or 0xE0020 <= cp <= 0xE007F  # tag characters (subdivision flags)
        or cp == 0x20E3  # keycap
    )


def one_grapheme(text: str) -> bool:
    """Roughly one user-perceived character: one base character per ZWJ part
    (or a regional-indicator pair, a flag), no letters or spaces."""
    if not text or len(text) > 32 or text.isspace():
        return False
    if any(ch.isspace() or unicodedata.category(ch) in ("Cc", "Co", "Cs") for ch in text):
        return False
    if all(0x1F1E6 <= ord(ch) <= 0x1F1FF for ch in text):
        return len(text) == 2
    for part in text.split("‍"):
        bases = [ch for ch in part if not _is_emoji_part(ch)]
        if len(bases) != 1:
            return False
        if bases[0].isalpha() and ord(bases[0]) < 0x2000:
            return False  # a letter, not a symbol
    return True


def _value(key: Any, field: str, *, numeric: bool) -> ValueRef:
    ref = parse(key)
    if ref is None or (numeric and ref.is_labels):
        raise InvalidCategory(field)
    return ref


def _label_operand(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidCategory(field)
    label = value.strip().lower()
    if not 1 <= len(label) <= 60 or any(ord(ch) < 32 for ch in label):
        raise InvalidCategory(field)
    return label


def _where(raw: Any, i: int) -> dict[str, Any]:
    n = i + 1
    if not isinstance(raw, dict):
        raise InvalidCategory(f"Bedingung {n}")
    op = raw.get("op")
    if op not in OPS:
        raise InvalidCategory(f"Bedingung {n}: Operator")
    ref = _value(raw.get("value"), f"Bedingung {n}: Wert", numeric=op in (*NUMERIC_OPS, "between"))
    operand_field = f"Bedingung {n}: Vergleichswert"
    operand: Any = raw.get("operand")
    if op in NUMERIC_OPS:
        operand = _number(operand, operand_field)
    elif op == "between":
        if not isinstance(operand, list) or len(operand) != 2:
            raise InvalidCategory(operand_field)
        a, b = (_number(v, operand_field) for v in operand)
        if a > b:
            raise InvalidCategory(operand_field)
        operand = [a, b]
    elif op in ("exists", "not_exists"):
        if operand is not None:
            raise InvalidCategory(operand_field)
    else:
        if not ref.is_labels:
            raise InvalidCategory(f"Bedingung {n}: Wert")
        if op == "contains_any":
            if not isinstance(operand, list) or not 1 <= len(operand) <= MAX_ANY:
                raise InvalidCategory(operand_field)
            operand = list(dict.fromkeys(_label_operand(v, operand_field) for v in operand))
        else:
            operand = _label_operand(operand, operand_field)
    return {"value": ref.key, "op": op, "operand": operand}


def _then_by(raw: Any, i: int) -> dict[str, str]:
    field = f"Auswahl: danach {i + 1}"
    if isinstance(raw, str):
        raw = {"by": raw, "order": "top"}
    if not isinstance(raw, dict):
        raise InvalidCategory(field)
    order = raw.get("order", "top")
    if order not in ("top", "bottom"):
        raise InvalidCategory(field)
    return {"by": _value(raw.get("by"), field, numeric=True).key, "order": order}


def validate(spec: Any) -> dict[str, Any]:
    """The normalised spec, or InvalidCategory naming the field (German)."""
    if not isinstance(spec, dict):
        raise InvalidCategory("Kategorie")
    emoji = spec.get("emoji")
    if not isinstance(emoji, str) or not one_grapheme(emoji.strip()):
        raise InvalidCategory("Emoji")
    title = _str(spec.get("title"), "Titel", 1, 40)
    line = _str(spec.get("line", ""), "Untertitel", 0, 80)
    where_raw = spec.get("where", [])
    if not isinstance(where_raw, list) or len(where_raw) > MAX_WHERE:
        raise InvalidCategory("Bedingungen")
    where = [_where(w, i) for i, w in enumerate(where_raw)]

    sel = spec.get("select")
    if not isinstance(sel, dict):
        raise InvalidCategory("Auswahl")
    by = _value(sel.get("by"), "Auswahl: Wert", numeric=True).key
    order = sel.get("order", "top")
    if order not in ("top", "bottom"):
        raise InvalidCategory("Auswahl: Top / Bottom")
    count = sel.get("count", 3)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_COUNT:
        raise InvalidCategory("Anzahl")
    then_raw = sel.get("then_by", [])
    if not isinstance(then_raw, list) or len(then_raw) > MAX_THEN_BY:
        raise InvalidCategory("Auswahl: danach")
    then_by = [_then_by(t, i) for i, t in enumerate(then_raw)]
    one_per_guest = sel.get("one_per_guest", True)
    if not isinstance(one_per_guest, bool):
        raise InvalidCategory("Ein Foto pro Gast")

    lab = spec.get("label", {})
    if lab is None:
        lab = {}
    if not isinstance(lab, dict):
        raise InvalidCategory("Beschriftung")
    lvalue = lab.get("value")
    if lvalue is not None:
        lvalue = _value(lvalue, "Beschriftung: Wert", numeric=True).key
    style = lab.get("style", "count")
    if style not in STYLES:
        raise InvalidCategory("Beschriftung: Stil")
    one = _str(lab.get("one", ""), "Beschriftung: Einzahl", 0, 40)
    many = _str(lab.get("many", ""), "Beschriftung: Mehrzahl", 0, 40)

    verdict_raw = spec.get("verdict")
    verdict: dict[str, str] | None = None
    if verdict_raw is not None:
        if not isinstance(verdict_raw, dict):
            raise InvalidCategory("Urteil der KI (Prompt)")
        prompt = verdict_raw.get("prompt")
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 1000:
            raise InvalidCategory("Urteil der KI (Prompt)")
        verdict = {"prompt": prompt.strip()}
    return {
        "emoji": emoji.strip(), "title": title, "line": line, "where": where,
        "select": {"by": by, "order": order, "count": count, "then_by": then_by,
                   "one_per_guest": one_per_guest},
        "label": {"value": lvalue, "style": style, "one": one, "many": many},
        "verdict": verdict,
    }  # fmt: skip


def spec_values(spec: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(required value keys: conditions and the displayed value; optional:
    the ranking values when a label value is set)."""
    required = [w["value"] for w in spec["where"]]
    shown = spec["label"]["value"] or spec["select"]["by"]
    required.append(shown)
    optional = [spec["select"]["by"], *(t["by"] for t in spec["select"]["then_by"])]
    return list(dict.fromkeys(required)), [k for k in dict.fromkeys(optional) if k not in required]


def spec_availability(
    spec: Mapping[str, Any], active: Collection[str], properties: Mapping[str, bool],
    external_objects: bool,
) -> str | None:  # fmt: skip
    """None when every required value can have data, else a German reason."""
    required, _ = spec_values(spec)
    for key in required:
        ref = parse(key)
        if ref is None:
            return "Ungültiger Wert."
        reason = availability(ref, active, properties, external_objects)
        if reason:
            return reason
    return None


# -------------------------------------------------------------- snapshot


@dataclass
class PhotoData:
    facts: dict[str, float] = field(default_factory=dict)
    # (idx, label, label_de, score), idx order
    objects: list[tuple[int, str, str, float]] = field(default_factory=list)
    detected: bool = False  # a detection source ran (an empty list is data)
    props: dict[str, list[float | None]] = field(default_factory=dict)


@dataclass
class Snapshot:
    key: tuple[Any, ...]
    photos: dict[int, PhotoData]


_KEY_SQL = (
    "SELECT (SELECT COALESCE(MAX(rev), 0) FROM wall_analysis), "
    "(SELECT COUNT(*) FROM wall_analysis), "
    "(SELECT COALESCE(MAX(id), 0) FROM llm_polls), "
    "(SELECT COUNT(*) FROM property_scores), "
    "(SELECT MAX(updated_at) FROM property_scores), "
    "(SELECT MAX(updated_at) FROM wall_categories), "
    "(SELECT COUNT(*) FROM llm_properties WHERE archived_at IS NULL)"
)
_cache: dict[str, Snapshot] = {}
_cache_lock = threading.Lock()
_loads = [0]  # for tests: how often a snapshot was built


def _db_key(db: Database) -> str:
    return f"{id(db)}:{getattr(db, 'path', '')}"


def snapshot(db: Database) -> Snapshot:
    """Every photo's analysis (not deleted ones), rebuilt when it changed."""
    row = db.one(_KEY_SQL)
    key = tuple(row) if row is not None else ()
    dbk = _db_key(db)
    with _cache_lock:
        cached = _cache.get(dbk)
        if cached is not None and cached.key == key:
            return cached
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
        try:
            raw = json.loads(r[2])
        except ValueError:
            continue
        if not isinstance(raw, list):
            continue
        photos.setdefault(int(r[0]), PhotoData()).props[r[1]] = [
            float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None
            for v in raw
        ]
    snap = Snapshot(key, photos)
    with _cache_lock:
        _cache[dbk] = snap
        _loads[0] += 1
    return snap


# ------------------------------------------------------------ evaluation


@dataclass(frozen=True)
class Winner:
    photo_id: int
    value: float | None
    label: str
    object_idx: int | None


@dataclass(frozen=True)
class Evaluation:
    winners: list[Winner]
    matched: int  # photos that meet every condition (before the selection)


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
    """Visible photos per guest (the opt-out does not matter here)."""
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
            found = [s for i, s in enumerate(scores) if s is not None and labels.get(i) == ref.label]
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
        """The object the value points at: the best-scoring one for a
        property (lowest for `min`), the surest one with the label for a
        label count, else the detector's surest object."""
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
    if op == "gt":
        return value > operand + EPS
    if op == "lt":
        return value < operand - EPS
    if op == "gte":
        return value >= operand - EPS
    if op == "lte":
        return value <= operand + EPS
    if op == "eq":
        return abs(value - operand) <= EPS
    if op == "ne":
        return abs(value - operand) > EPS
    if op == "between":
        return operand[0] - EPS <= value <= operand[1] + EPS
    return False


def label_text(style: str, value: float | None, one: str, many: str,
               object_label: str | None = None) -> str:  # fmt: skip
    """The German label: „7 Personen“, „82 % Drama“, „Farbwert 73“, „um 19:42“."""
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


def run(core: HasDb, spec: Mapping[str, Any], flt: PhotoFilter, limit: int | None = None) -> Evaluation:
    """Winners of a (validated) spec plus how many photos met the conditions."""
    db = core.db
    snap = snapshot(db)
    rows = _visible_rows(db, flt)
    sel = spec["select"]
    lab = spec["label"]
    where = [(parse(w["value"]), w["op"], w["operand"]) for w in spec["where"]]
    by = parse(sel["by"])
    then = [(parse(t["by"]), t["order"]) for t in sel["then_by"]]
    shown = parse(lab["value"]) if lab["value"] else by
    refs = [r for r, _, _ in where] + [by, shown] + [r for r, _ in then]
    if any(r is None for r in refs):
        return Evaluation([], 0)
    assert by is not None and shown is not None
    needs_guests = any(r is not None and r.kind == "guest_photos" for r in refs)
    ctx = _Ctx(snap.photos, _guest_counts(db, flt) if needs_guests else {})

    matched: list[_Row] = []
    for row in rows:
        if all(_holds(op, ctx.value(row, ref), operand) for ref, op, operand in where if ref):
            matched.append(row)
    candidates = [r for r in matched if ctx.value(r, shown) is not None]
    # ties: the newer photo first (a stable sort keeps this order below)
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
    return Evaluation(winners, len(matched))


def evaluate(
    core: HasDb, spec: Mapping[str, Any], flt: PhotoFilter, limit: int | None = None
) -> list[Winner]:
    """The winners of a spec, best first (at most `select.count`, or `limit`)."""
    return run(core, spec, flt, limit).winners


# ---------------------------------------------------------------- storage


@dataclass(frozen=True)
class StoredCategory:
    id: str
    position: int
    enabled: bool
    preset: str | None
    spec: dict[str, Any]
    updated_at: str


def _load_spec(raw: str) -> dict[str, Any] | None:
    try:
        return validate(json.loads(raw))
    except (ValueError, InvalidCategory):
        return None


def stored(db: Database) -> list[StoredCategory]:
    """Every category in position order (a stored spec that no longer
    validates is left out)."""
    out: list[StoredCategory] = []
    for r in db.all(
        "SELECT id, position, enabled, preset, spec, updated_at FROM wall_categories "
        "ORDER BY position, id"
    ):
        spec = _load_spec(r["spec"])
        if spec is None:
            continue
        out.append(StoredCategory(r["id"], int(r["position"]), bool(r["enabled"]), r["preset"],
                                  spec, r["updated_at"]))  # fmt: skip
    return out


def category_specs(db: Database) -> list[tuple[str, bool, dict[str, Any]]]:
    """(id, enabled, spec) in position order (PLAN-NIGHT §4.1)."""
    return [(c.id, c.enabled, c.spec) for c in stored(db)]


def get(db: Database, cid: str) -> StoredCategory | None:
    return next((c for c in stored(db) if c.id == cid), None)


def has_enabled(db: Database) -> bool:
    return db.one("SELECT 1 FROM wall_categories WHERE enabled = 1 LIMIT 1") is not None


def insert(db: Database, cid: str, spec: Mapping[str, Any], *, enabled: bool,
           preset: str | None, by: str | None, position: int | None = None) -> None:  # fmt: skip
    with db.tx() as c:
        if position is None:
            position = int(
                c.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM wall_categories").fetchone()[0]
            )
        c.execute(
            "INSERT INTO wall_categories (id, position, enabled, preset, spec, updated_at, "
            "updated_by) VALUES (?,?,?,?,?,?,?)",
            (cid, position, int(enabled), preset, json.dumps(spec, ensure_ascii=False),
             now_iso(), by),  # fmt: skip
        )


def update(db: Database, cid: str, spec: Mapping[str, Any], *, enabled: bool, by: str) -> bool:
    with db.tx() as c:
        return (
            c.execute(
                "UPDATE wall_categories SET spec=?, enabled=?, updated_at=?, updated_by=? "
                "WHERE id=?",
                (json.dumps(spec, ensure_ascii=False), int(enabled), now_iso(), by, cid),
            ).rowcount
            > 0
        )


def delete(db: Database, cid: str) -> bool:
    with db.tx() as c:
        gone = c.execute("DELETE FROM wall_categories WHERE id=?", (cid,)).rowcount > 0
        if gone:
            c.execute("DELETE FROM wall_category_verdicts WHERE category_id=?", (cid,))
        return gone


def reorder(db: Database, ids: Sequence[str], *, by: str) -> None:
    """`ids` first in this order, the others after them in their old order."""
    current = [r[0] for r in db.all("SELECT id FROM wall_categories ORDER BY position, id")]
    order = [i for i in dict.fromkeys(ids) if i in current] + [i for i in current if i not in ids]
    at = now_iso()
    with db.tx() as c:
        for pos, cid in enumerate(order):
            c.execute(
                "UPDATE wall_categories SET position=?, updated_at=?, updated_by=? "
                "WHERE id=? AND position != ?",
                (pos, at, by, cid, pos),
            )


# ---------------------------------------------------------------- verdicts


@dataclass(frozen=True)
class Verdict:
    text: str
    emoji: str | None
    photo_id: int | None
    object_idx: int | None
    created_at: str


def verdicts(db: Database) -> dict[str, Verdict]:
    return {
        r["category_id"]: Verdict(r["text"], r["emoji"], r["photo_id"], r["object_idx"],
                                  r["created_at"])  # fmt: skip
        for r in db.all(
            "SELECT category_id, text, emoji, photo_id, object_idx, created_at "
            "FROM wall_category_verdicts"
        )
    }


def last_poll(db: Database) -> int:
    """The newest finished LLM poll (the hub announces new verdicts with it)."""
    row = db.one("SELECT COALESCE(MAX(id), 0) FROM llm_polls WHERE state = 'done'")
    return int(row[0]) if row is not None else 0


def availability_context(db: Database) -> tuple[dict[str, bool], bool]:
    """(property name → archived, an external source added objects)."""
    return properties_of(db), has_external_objects(db)
