"""Rule-based Live-Wall categories, spec version 2 (categories v2): validate a
CategorySpec, evaluate it, explain it, and keep the specs in `wall_categories`.

Everything a spec reads is a measure (measures.py). The pipeline:

    P      = visible photos (the wall's sources, past the delay, not hidden, no opt-out)
    Pool   = { p ∈ P | every pool condition holds }       (a missing value fails it)
    Rank   = sort Pool by (rank.by, then[0], then[1], newer photo first)
             a missing rank value ranks last; a missing displayed value drops the photo
    Thresh = optional on rank.by: desc ⇒ m ≥ t, asc ⇒ m ≤ t
    Pick   = one photo per guest (optional) → the first `select.count` (1–10)

Each winner carries the displayed value, its caption (headline, detail, the
composed `label`) and its focus object (idx, German label, value, box).

A v1 spec (no `version`, or `version: 1`) is accepted everywhere a spec is: it is
validated as v1 and converted (spec_v1.upgrade). Evaluation runs in Python over a
snapshot of every photo's analysis (facts, objects, property scores) cached until
the analysis, the polls or the categories change; visibility and the guests'
opt-out flags are read fresh each time.
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
from . import clock, measures, spec_v1
from .measures import InvalidCategory, Measure, Obj, PhotoInput, Result
from .values import availability, has_external_objects, properties_of

__all__ = ["InvalidCategory"]

CATEGORY_ID_RE_TEXT = r"^[a-z][a-z0-9_]{1,40}$"
RESERVED_IDS = frozenset({"order", "preview", "export", "import"})
NUMERIC_OPS = ("gt", "lt", "gte", "lte", "eq", "ne")
OPS = (*NUMERIC_OPS, "between", "exists", "not_exists")
FORMATS = ("count", "percent", "decimal", "number", "time", "text", "none")
ORDERS = ("desc", "asc")
EFFORTS = ("low", "medium", "high")
MAX_POOL = 8
MAX_THEN = 2
MAX_COUNT = 10
MAX_COMMENTS = 5
VERDICT_PROMPT_MAX = 1000
EPS = measures.EPS


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


def _facts() -> frozenset[str]:
    from .values import ALL_FACTS

    return ALL_FACTS


def _measure(raw: Any, field: str) -> dict[str, Any]:
    return measures.parse(raw, field, _facts()).to_json()


def _condition(raw: Any, i: int) -> dict[str, Any]:
    n = i + 1
    if not isinstance(raw, dict) or set(raw) - {"measure", "op", "operand"}:
        raise InvalidCategory(f"Bedingung {n}")
    op = raw.get("op")
    if op not in OPS:
        raise InvalidCategory(f"Bedingung {n}: Operator")
    measure = _measure(raw.get("measure"), f"Bedingung {n}: Messgröße")
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
    elif operand is not None:
        raise InvalidCategory(operand_field)
    return {"measure": measure, "op": op, "operand": operand}


def _then(raw: Any, i: int) -> dict[str, Any]:
    field = f"Rang: danach {i + 1}"
    if not isinstance(raw, dict) or set(raw) - {"by", "order"}:
        raise InvalidCategory(field)
    order = raw.get("order", "desc")
    if order not in ORDERS:
        raise InvalidCategory(field)
    return {"by": _measure(raw.get("by"), field), "order": order}


def _verdict(raw: Any) -> dict[str, Any] | None:
    from ..llm import pricing  # a pure table, no LLM machinery

    if raw is None:
        return None
    field = "KI-Urteil"
    if not isinstance(raw, dict) or set(raw) - {"prompt", "count", "winners", "model", "effort"}:
        raise InvalidCategory(field)
    prompt = raw.get("prompt")
    if prompt is not None:
        if not isinstance(prompt, str) or len(prompt.strip()) > VERDICT_PROMPT_MAX:
            raise InvalidCategory("KI-Urteil: Prompt")
        prompt = prompt.strip() or None
    count = raw.get("count", raw.get("winners", 3))
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_COMMENTS:
        raise InvalidCategory("KI-Urteil: Anzahl")
    model = raw.get("model")
    if model is not None and model not in pricing.VERDICT_MODEL_IDS:
        raise InvalidCategory("KI-Urteil: Modell")
    effort = raw.get("effort", "low")
    if effort not in EFFORTS:
        raise InvalidCategory("KI-Urteil: Denkaufwand")
    return {"prompt": prompt, "count": count, "model": model, "effort": effort}


def validate(spec: Any) -> dict[str, Any]:
    """The normalised v2 spec, or InvalidCategory naming the field (German).
    A v1 spec (no `version` or `version: 1`) is validated as v1 and upgraded."""
    if not isinstance(spec, dict):
        raise InvalidCategory("Kategorie")
    version = spec.get("version", 1)
    if version == 1 and not isinstance(version, bool):
        try:
            v1 = spec_v1.validate(spec)
        except InvalidCategory as exc:
            exc.version = 1
            raise
        spec = spec_v1.upgrade(v1)
    elif version != 2 or isinstance(version, bool):
        raise InvalidCategory("Version")
    known = {"version", "emoji", "title", "line", "pool", "rank", "select", "caption", "verdict"}
    if set(spec) - known:
        raise InvalidCategory("Kategorie")
    emoji = spec.get("emoji")
    if not isinstance(emoji, str) or not one_grapheme(emoji.strip()):
        raise InvalidCategory("Emoji")
    title = _str(spec.get("title"), "Titel", 1, 40)
    line = _str(spec.get("line", ""), "Untertitel", 0, 80)
    pool_raw = spec.get("pool", [])
    if not isinstance(pool_raw, list) or len(pool_raw) > MAX_POOL:
        raise InvalidCategory("Bedingungen")
    pool = [_condition(c, i) for i, c in enumerate(pool_raw)]

    rank_raw = spec.get("rank")
    if not isinstance(rank_raw, dict) or set(rank_raw) - {"by", "order", "threshold", "then"}:
        raise InvalidCategory("Rang")
    by = _measure(rank_raw.get("by"), "Rang: Messgröße")
    order = rank_raw.get("order", "desc")
    if order not in ORDERS:
        raise InvalidCategory("Rang: Richtung")
    threshold = rank_raw.get("threshold")
    if threshold is not None:
        threshold = _number(threshold, "Rang: Schwelle")
    then_raw = rank_raw.get("then", [])
    if not isinstance(then_raw, list) or len(then_raw) > MAX_THEN:
        raise InvalidCategory("Rang: danach")
    then = [_then(t, i) for i, t in enumerate(then_raw)]

    sel = spec.get("select", {})
    if not isinstance(sel, dict) or set(sel) - {"count", "one_per_guest"}:
        raise InvalidCategory("Auswahl")
    count = sel.get("count", 3)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_COUNT:
        raise InvalidCategory("Anzahl")
    one_per_guest = sel.get("one_per_guest", True)
    if not isinstance(one_per_guest, bool):
        raise InvalidCategory("Ein Foto pro Gast")

    cap = spec.get("caption") or {}
    if not isinstance(cap, dict) or set(cap) - {"value", "format", "one", "many", "show_object"}:
        raise InvalidCategory("Beschriftung")
    cvalue = cap.get("value")
    if cvalue is not None:
        cvalue = _measure(cvalue, "Beschriftung: Wert")
    fmt = cap.get("format", "count")
    if fmt not in FORMATS:
        raise InvalidCategory("Beschriftung: Format")
    one = _str(cap.get("one", ""), "Beschriftung: Einzahl", 0, 40)
    many = _str(cap.get("many", ""), "Beschriftung: Mehrzahl", 0, 40)
    show_object = cap.get("show_object", False)
    if not isinstance(show_object, bool):
        raise InvalidCategory("Beschriftung: Objekt zeigen")
    shown = measures.parse(cvalue or by, "Beschriftung: Wert", _facts())
    if show_object and not shown.has_focus:
        raise InvalidCategory("Beschriftung: Objekt zeigen")
    return {
        "version": 2, "emoji": emoji.strip(), "title": title, "line": line, "pool": pool,
        "rank": {"by": by, "order": order, "threshold": threshold, "then": then},
        "select": {"count": count, "one_per_guest": one_per_guest},
        "caption": {"value": cvalue, "format": fmt, "one": one, "many": many,
                    "show_object": show_object},
        "verdict": _verdict(spec.get("verdict")),
    }  # fmt: skip


# ----------------------------------------------------------- the measures


def _parsed(m: Mapping[str, Any]) -> Measure:
    return measures.parse(dict(m), "Messgröße", _facts())


def spec_measures(spec: Mapping[str, Any]) -> tuple[list[Measure], list[Measure]]:
    """(required: the pool's and the displayed one; optional: the ranking ones
    not required)."""
    required = [_parsed(c["measure"]) for c in spec["pool"]]
    cap = spec["caption"]["value"]
    required.append(_parsed(cap or spec["rank"]["by"]))
    optional = [_parsed(spec["rank"]["by"]), *(_parsed(t["by"]) for t in spec["rank"]["then"])]
    req = list(dict.fromkeys(required))
    return req, [m for m in dict.fromkeys(optional) if m not in req]


def all_measures(spec: Mapping[str, Any]) -> list[Measure]:
    req, opt = spec_measures(spec)
    return [*req, *opt]


def references(spec: Mapping[str, Any]) -> list[str]:
    """The property names a (validated) spec reads, in order."""
    return list(dict.fromkeys(m.prop for m in all_measures(spec) if m.prop))


def spec_availability(
    spec: Mapping[str, Any], active: Collection[str], properties: Mapping[str, bool],
    external_objects: bool,
) -> str | None:  # fmt: skip
    """None when every required measure can have data, else a German reason.
    `properties`: name → in the Papierkorb (every property with a row counts:
    its scores stay readable)."""
    required, _ = spec_measures(spec)
    for m in required:
        reason = availability(m, active, properties, external_objects)
        if reason:
            return reason
    return None


# -------------------------------------------------------------- snapshot


@dataclass
class PhotoData:
    facts: dict[str, float] = field(default_factory=dict)
    objects: list[Obj] = field(default_factory=list)  # idx order
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
    "(SELECT COUNT(*) FROM llm_properties WHERE deleted_at IS NULL), "
    "(SELECT COUNT(*) FROM llm_properties)"
)
_cache: dict[str, Snapshot] = {}
_cache_lock = threading.Lock()
_loads = [0]  # for tests: how often a snapshot was built


def _db_key(db: Database) -> str:
    return f"{id(db)}:{getattr(db, 'path', '')}"


def _box(r: Any) -> tuple[float, float, float, float] | None:
    if r["x"] is None or r["y"] is None or r["w"] is None or r["h"] is None:
        return None
    return (float(r["x"]), float(r["y"]), float(r["w"]), float(r["h"]))


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
        "SELECT photo_id, idx, label, label_de, score, x, y, w, h FROM photo_objects "
        f"WHERE photo_id IN ({alive}) ORDER BY photo_id, idx"
    ):
        photos.setdefault(int(r["photo_id"]), PhotoData()).objects.append(
            Obj(int(r["idx"]), r["label"], r["label_de"], float(r["score"]), _box(r))
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
class FocusObject:
    idx: int
    label: str
    label_de: str
    value: float | None  # the measure's x for it (a property's score, else its confidence)
    box: tuple[float, float, float, float] | None


@dataclass(frozen=True)
class Winner:
    photo_id: int
    value: float | None
    label: str  # headline and detail composed („Sonnenbrille · 0,93“)
    object_idx: int | None
    headline: str = ""
    detail: str | None = None
    object: FocusObject | None = None


@dataclass(frozen=True)
class Evaluation:
    winners: list[Winner]
    matched: int  # photos in the pool that pass the threshold (before the selection)


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


def _holds(op: str, value: float | None, operand: Any) -> bool:
    if op == "exists":
        return value is not None
    if op == "not_exists":
        return value is None
    if value is None:
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


def _decimal(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def value_text(fmt: str, value: float | None, one: str, many: str) -> str:
    """„7 Personen“, „82 % Drama“, „0,93 Coolness“, „Farbwert 73“, „um 19:42“."""
    if fmt == "text":
        return one
    if fmt == "none":
        return ""
    if value is None:
        return one
    if fmt == "count":
        n = round(value)
        return f"{n} {one if n == 1 else many}".strip()
    if fmt == "percent":
        return f"{round(value * 100)} % {one}".strip()
    if fmt == "decimal":
        return f"{_decimal(value)} {one}".strip()
    if fmt == "number":
        return f"{one} {value:.0f}".strip()
    return f"um {clock.local(value):%H:%M}"


def caption(cap: Mapping[str, Any], value: float | None, obj: FocusObject | None
            ) -> tuple[str, str | None, str]:  # fmt: skip
    """(headline, detail, label): the object's name with the value as detail
    (`show_object`), else the value text."""
    text = value_text(cap["format"], value, cap["one"], cap["many"])
    if cap["show_object"]:
        headline = obj.label_de if obj is not None else (cap["one"] or "Objekt")
        detail = text if text and text != headline else None
    else:
        headline, detail = text, None
    return headline, detail, f"{headline} · {detail}" if detail else headline


def _sort_key(v: float | None, order: str) -> tuple[int, float]:
    if v is None:
        return (1, 0.0)
    return (0, -v if order == "desc" else v)


class _Photos:
    """Each photo's measure results, computed once per run."""

    def __init__(self, data: Mapping[int, PhotoData], guests: Mapping[int, int]) -> None:
        self.data = data
        self.guests = guests
        self._inputs: dict[int, PhotoInput] = {}
        self._results: dict[tuple[int, Measure], Result] = {}

    def input(self, row: _Row) -> PhotoInput:
        found = self._inputs.get(row.id)
        if found is None:
            d = self.data.get(row.id) or PhotoData()
            values = dict(d.facts)
            values["photo.created_at"] = clock.unix(row.created_at)
            values["photo.guest_photos"] = float(self.guests.get(row.user_id, 0))
            found = PhotoInput(values, d.objects, d.detected, d.props)
            self._inputs[row.id] = found
        return found

    def result(self, row: _Row, m: Measure) -> Result:
        k = (row.id, m)
        found = self._results.get(k)
        if found is None:
            found = measures.evaluate(m, self.input(row))
            self._results[k] = found
        return found

    def value(self, row: _Row, m: Measure) -> float | None:
        return self.result(row, m).value

    def focus(self, row: _Row, m: Measure) -> FocusObject | None:
        res = self.result(row, m)
        if res.focus is None:
            return None
        obj = next((o for o in self.input(row).objects if o.idx == res.focus), None)
        if obj is None:
            return None
        return FocusObject(obj.idx, obj.label, obj.label_de, res.focus_value, obj.box)


def run(
    core: HasDb, spec: Mapping[str, Any], flt: PhotoFilter, limit: int | None = None
) -> Evaluation:
    """Winners of a (validated) spec plus how many photos are in the pool."""
    db = core.db
    snap = snapshot(db)
    rows = _visible_rows(db, flt)
    rank, sel, cap = spec["rank"], spec["select"], spec["caption"]
    pool = [(_parsed(c["measure"]), c["op"], c["operand"]) for c in spec["pool"]]
    by = _parsed(rank["by"])
    then = [(_parsed(t["by"]), t["order"]) for t in rank["then"]]
    shown = _parsed(cap["value"]) if cap["value"] else by
    every = [m for m, _, _ in pool] + [by, shown] + [m for m, _ in then]
    needs_guests = any(m.kind == "value" and m.key == "photo.guest_photos" for m in every)
    ctx = _Photos(snap.photos, _guest_counts(db, flt) if needs_guests else {})
    order = rank["order"]
    threshold = rank["threshold"]
    op = "gte" if order == "desc" else "lte"

    matched: list[_Row] = []
    for row in rows:
        if not all(_holds(o, ctx.value(row, m), operand) for m, o, operand in pool):
            continue
        if threshold is not None and not _holds(op, ctx.value(row, by), threshold):
            continue
        matched.append(row)
    candidates = [r for r in matched if ctx.value(r, shown) is not None]
    # ties: the newer photo first (a stable sort keeps this order below)
    candidates.sort(key=lambda r: (r.created_at, r.id), reverse=True)
    candidates.sort(
        key=lambda r: (
            _sort_key(ctx.value(r, by), order),
            *(_sort_key(ctx.value(r, m), o) for m, o in then),
        )
    )
    want = sel["count"] if limit is None else max(0, min(limit, sel["count"]))
    # the ranking's object (as v1 did), else the displayed measure's
    focus_of = by if by.has_focus else (shown if shown.has_focus else None)
    winners: list[Winner] = []
    guests: set[int] = set()
    for row in candidates:
        if len(winners) >= want:
            break
        if sel["one_per_guest"]:
            if row.user_id in guests:
                continue
            guests.add(row.user_id)
        value = ctx.value(row, shown)
        obj = ctx.focus(row, focus_of) if focus_of is not None else None
        headline, detail, label = caption(cap, value, obj)
        winners.append(Winner(row.id, value, label, obj.idx if obj else None, headline,
                              detail, obj))  # fmt: skip
    return Evaluation(winners, len(matched))


def evaluate(
    core: HasDb, spec: Mapping[str, Any], flt: PhotoFilter, limit: int | None = None
) -> list[Winner]:
    """The winners of a spec, best first (at most `select.count`, or `limit`)."""
    return run(core, spec, flt, limit).winners


# ---------------------------------------------------------------- explain


def _title(m: Measure, titles: Mapping[str, str]) -> str:
    if m.kind == "value":
        assert m.key is not None
        return titles.get(m.key, m.key)
    if m.field == "confidence":
        return "Erkennungssicherheit"
    return m.prop or "Objekte"


def _filter_text(f: measures.ObjectFilter) -> str:
    parts = []
    if f.labels:
        parts.append("nur " + ", ".join(f.labels))
    if f.exclude:
        parts.append("ohne " + ", ".join(f.exclude))
    if f.min_confidence is not None:
        parts.append(f"Sicherheit ab {round(f.min_confidence * 100)} %")
    return f" ({'; '.join(parts)})" if parts else ""


def describe(m: Measure, order: str = "desc") -> str:
    """The measure as a German phrase with its direction: „Höchster
    coolness-Wert unter allen Objekten“, „Die meisten Objekte (ohne person)“."""
    from .values import FACT_TITLES

    hi = order == "desc"
    title = _title(m, FACT_TITLES)
    if m.kind == "value":
        if m.key == "photo.created_at":
            return "Das neueste Foto" if hi else "Das früheste Foto"
        if m.key == "photo.guest_photos":
            return "Die meisten Fotos eines Gasts" if hi else "Die wenigsten Fotos eines Gasts"
        return f"{'Höchster' if hi else 'Niedrigster'} Wert bei „{title}“"
    most = "Die meisten" if hi else "Die wenigsten"
    where = _filter_text(m.where)
    if m.field is None:
        return f"{most} Objekte{where}"
    if m.agg == "count":
        return f"{most} bewerteten Objekte ({title}){where}"
    if m.agg == "count_ge":
        return f"{most} Objekte mit {title} ab {_decimal(m.t or 0.0)}{where}"
    word = {
        "max": ("Höchster", "Niedrigster", f"{title}-Wert unter allen Objekten"),
        "min": ("Niedrigster", "Höchster", f"{title}-Wert unter allen Objekten"),
        "mean": ("Höchster", "Niedrigster", f"Durchschnitt von {title}"),
        "sum": ("Höchste", "Niedrigste", f"Summe von {title}"),
        "top_k_mean": ("Höchster", "Niedrigster",
                       f"Schnitt der besten {m.k} {title}-Werte"),
    }[m.agg or "max"]  # fmt: skip
    return f"{word[0] if hi else word[1]} {word[2]}{where}"


def _number_text(x: float) -> str:
    return f"{x:.0f}" if abs(x - round(x)) < EPS else _decimal(x)


def explain(spec: Mapping[str, Any]) -> str:
    """The ranking in plain German („Höchster Wert bei „Personen“, mindestens 3“):
    the wall's subtitle when the host left `line` empty."""
    rank = spec["rank"]
    text = describe(_parsed(rank["by"]), rank["order"])
    if rank["threshold"] is not None:
        word = "mindestens" if rank["order"] == "desc" else "höchstens"
        text += f", {word} {_number_text(float(rank['threshold']))}"
    return text[:80]


def shown_line(spec: Mapping[str, Any]) -> str:
    return str(spec["line"]) or explain(spec)


# ---------------------------------------------------------------- storage


@dataclass(frozen=True)
class StoredCategory:
    id: str
    position: int
    enabled: bool
    preset: str | None
    spec: dict[str, Any]
    updated_at: str
    off_reason: str | None = None
    off_detail: str | None = None
    off_at: str | None = None


def load_spec(raw: str) -> dict[str, Any] | None:
    try:
        return validate(json.loads(raw))
    except (ValueError, InvalidCategory):
        return None


def stored(db: Database) -> list[StoredCategory]:
    """Every category in position order (a stored spec that no longer
    validates is left out; a v1 row not upgraded yet reads upgraded)."""
    out: list[StoredCategory] = []
    for r in db.all(
        "SELECT id, position, enabled, preset, spec, updated_at, off_reason, off_detail, off_at "
        "FROM wall_categories ORDER BY position, id"
    ):
        spec = load_spec(r["spec"])
        if spec is None:
            continue
        out.append(StoredCategory(r["id"], int(r["position"]), bool(r["enabled"]), r["preset"],
                                  spec, r["updated_at"], r["off_reason"], r["off_detail"],
                                  r["off_at"]))  # fmt: skip
    return out


def category_specs(db: Database) -> list[tuple[str, bool, dict[str, Any]]]:
    """(id, enabled, spec) in position order."""
    return [(c.id, c.enabled, c.spec) for c in stored(db)]


def get(db: Database, cid: str) -> StoredCategory | None:
    return next((c for c in stored(db) if c.id == cid), None)


def auto_off_state(db: Database) -> tuple[int, str]:
    """(enabled categories, the latest automatic switch-off): changes when the
    app switches a category off."""
    row = db.one("SELECT COALESCE(SUM(enabled), 0), COALESCE(MAX(off_at), '') FROM wall_categories")
    return (int(row[0]), str(row[1])) if row is not None else (0, "")


def has_enabled(db: Database) -> bool:
    return db.one("SELECT 1 FROM wall_categories WHERE enabled = 1 LIMIT 1") is not None


def _dump(spec: Mapping[str, Any]) -> str:
    return json.dumps(spec, ensure_ascii=False)


def insert(db: Database, cid: str, spec: Mapping[str, Any], *, enabled: bool,
           preset: str | None, by: str | None, position: int | None = None,
           off_reason: str | None = None, off_detail: str | None = None) -> None:  # fmt: skip
    at = now_iso()
    with db.tx() as c:
        if position is None:
            row = c.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM wall_categories")
            position = int(row.fetchone()[0])
        c.execute(
            "INSERT INTO wall_categories (id, position, enabled, preset, spec, updated_at, "
            "updated_by, spec_version, off_reason, off_detail, off_at) "
            "VALUES (?,?,?,?,?,?,?,2,?,?,?)",
            (cid, position, int(enabled), preset, _dump(spec), at, by, off_reason, off_detail,
             at if off_reason else None),
        )  # fmt: skip


def verdict_key(verdict: Mapping[str, Any] | None) -> tuple[Any, ...] | None:
    """What a cached comment depends on in the spec (its count does not count)."""
    if not verdict:
        return None
    return (verdict.get("prompt"), verdict.get("model"), verdict.get("effort"))


def update(db: Database, cid: str, spec: Mapping[str, Any], *, enabled: bool, by: str) -> bool:
    """A host's change. Switching it on or off clears an automatic switch-off's
    reason; a changed verdict prompt, model or effort drops its cached comments."""
    with db.tx() as c:
        row = c.execute("SELECT enabled, spec FROM wall_categories WHERE id=?", (cid,)).fetchone()
        if row is None:
            return False
        keep_reason = not enabled and not row["enabled"]
        c.execute(
            "UPDATE wall_categories SET spec=?, enabled=?, updated_at=?, updated_by=?, "
            "spec_version=2, off_reason=CASE WHEN ? THEN off_reason END, "
            "off_detail=CASE WHEN ? THEN off_detail END, off_at=CASE WHEN ? THEN off_at END "
            "WHERE id=?",
            (_dump(spec), int(enabled), now_iso(), by, keep_reason, keep_reason, keep_reason, cid),
        )
        old = load_spec(row["spec"])
        if old is None or verdict_key(old.get("verdict")) != verdict_key(spec.get("verdict")):
            c.execute("DELETE FROM wall_category_comments WHERE category_id=?", (cid,))
        if (
            old is not None
            and old["title"] != spec["title"]
            and not (spec.get("verdict") or {}).get("prompt")
        ):
            # the default prompt names the title
            c.execute("DELETE FROM wall_category_comments WHERE category_id=?", (cid,))
        return True


def switch_off(db: Database, cid: str, reason: str, detail: str | None) -> None:
    """Switched off by the app (lifecycle): the reason stays until the host switches."""
    with db.tx() as c:
        c.execute(
            "UPDATE wall_categories SET enabled=0, off_reason=?, off_detail=?, off_at=? "
            "WHERE id=? AND enabled=1",
            (reason, detail, now_iso(), cid),
        )


def delete(db: Database, cid: str) -> bool:
    with db.tx() as c:
        gone = c.execute("DELETE FROM wall_categories WHERE id=?", (cid,)).rowcount > 0
        if gone:
            c.execute("DELETE FROM wall_category_verdicts WHERE category_id=?", (cid,))
            c.execute("DELETE FROM wall_category_comments WHERE category_id=?", (cid,))
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


# ---------------------------------------------------------------- comments


@dataclass(frozen=True)
class Comment:
    """The AI's comment on one winner of one category (cached per pair)."""

    text: str
    emoji: str | None
    object_idx: int | None
    config_hash: str
    created_at: str


def comments(db: Database) -> dict[tuple[str, int], Comment]:
    """(category id, photo id) → its comment."""
    return {
        (r["category_id"], int(r["photo_id"])): Comment(
            r["text"], r["emoji"], r["object_idx"], r["config_hash"], r["created_at"]
        )
        for r in db.all(
            "SELECT category_id, photo_id, text, emoji, object_idx, config_hash, created_at "
            "FROM wall_category_comments"
        )
    }


def last_poll(db: Database) -> int:
    """The newest finished LLM poll (the hub announces new comments with it)."""
    row = db.one("SELECT COALESCE(MAX(id), 0) FROM llm_polls WHERE state = 'done'")
    return int(row[0]) if row is not None else 0


def availability_context(db: Database) -> tuple[dict[str, bool], bool]:
    """(property name → in the Papierkorb, an external source added objects)."""
    return properties_of(db), has_external_objects(db)
