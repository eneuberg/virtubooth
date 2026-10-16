"""The one building block of a category (categories v2): the measure.

    Measure := value(key)                       a photo value (an analyzer's fact,
                                                `photo.created_at`, `photo.guest_photos`)
             | objects(filter).count            how many objects pass the filter
             | objects(filter).agg(field)       field ∈ {confidence, prop:<name>}
    filter  := {labels ⊆ L, exclude ⊆ L, min_confidence}
    agg     := count | max | min | mean | sum | top_k_mean(k) | count_ge(t)

A measure is used everywhere: in the pool, the ranking, the tie-breakers and the
caption. The aggregates are pure functions over `[(idx, x)] → (value, focus idx)`
in a registry (`AGGREGATES`), like pandas' NamedAgg.

The focus object (what the wall frames): argmax for max, mean, sum, top_k_mean,
count_ge and a count of rated objects, argmin for min (ties: the lower idx), the
surest object for a count of objects with a label filter, none for a plain count.

Missing data is „no value“ (None): a photo no detection ran on has no object
measures; a property without scores for the photo has no `prop:` values; an idx
beyond a (shorter, older) score array, and a null score, count as „no value“.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from .merge import canonical

EPS = 1e-9
LABEL_MAX = 60
MAX_LABELS = 20
PROPERTY_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
FIELD_RE = re.compile(r"^(confidence|prop:[a-z][a-z0-9_]{1,30})$")
PHOTO_KEYS = ("photo.created_at", "photo.guest_photos")
AGGS = ("count", "max", "min", "mean", "sum", "top_k_mean", "count_ge")
# aggregates that need a field (count works with and without one)
FIELD_AGGS = frozenset({"max", "min", "mean", "sum", "top_k_mean", "count_ge"})
K_RANGE = (2, 5)

Kind = Literal["value", "objects"]


class InvalidCategory(ValueError):
    """A spec field is invalid; `field` is its German name for the 400, `version`
    the spec version whose field it is (a v1 spec is validated as v1)."""

    def __init__(self, field: str, version: int = 2) -> None:
        super().__init__(field)
        self.field = field
        self.version = version


# ------------------------------------------------------------------ labels


def canonical_label(raw: Any) -> str | None:
    """Lower case, single spaces, the canonical English (COCO) name for a synonym
    („smartphone“ → „cell phone“), as the merged object list stores labels."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or len(text) > LABEL_MAX or any(ord(ch) < 32 for ch in text):
        return None
    label = canonical(text.lower())[0]
    return label if label and len(label) <= LABEL_MAX else None


# ------------------------------------------------------------------ shapes


@dataclass(frozen=True)
class ObjectFilter:
    labels: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    min_confidence: float | None = None

    def passes(self, label: str, confidence: float) -> bool:
        if self.labels and label not in self.labels:
            return False
        if label in self.exclude:
            return False
        return self.min_confidence is None or confidence >= self.min_confidence - EPS

    def to_json(self) -> dict[str, Any]:
        return {"labels": list(self.labels), "exclude": list(self.exclude),
                "min_confidence": self.min_confidence}  # fmt: skip

    @property
    def empty(self) -> bool:
        return not self.labels and not self.exclude and self.min_confidence is None


@dataclass(frozen=True)
class Measure:
    kind: Kind
    key: str | None = None  # value
    where: ObjectFilter = field(default_factory=ObjectFilter)
    field: str | None = None  # objects: confidence | prop:<name> | None
    agg: str | None = None
    k: int | None = None
    t: float | None = None

    @property
    def prop(self) -> str | None:
        """The property it reads (`field: prop:<name>`), else None."""
        if self.field and self.field.startswith("prop:"):
            return self.field[5:]
        return None

    @property
    def has_focus(self) -> bool:
        """Whether a winner gets a focus object from this measure."""
        if self.kind != "objects":
            return False
        if self.agg == "count" and self.field is None:
            return bool(self.where.labels)
        return True

    def to_json(self) -> dict[str, Any]:
        if self.kind == "value":
            return {"kind": "value", "key": self.key}
        return {"kind": "objects", "where": self.where.to_json(), "field": self.field,
                "agg": self.agg, "k": self.k, "t": self.t}  # fmt: skip


# --------------------------------------------------------------- parsing


def _number(value: Any, name: str, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise InvalidCategory(name)
    x = float(value)
    if (lo is not None and x < lo) or (hi is not None and x > hi):
        raise InvalidCategory(name)
    return x


def _labels(raw: Any, name: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_LABELS:
        raise InvalidCategory(name)
    out: list[str] = []
    for item in raw:
        label = canonical_label(item)
        if label is None:
            raise InvalidCategory(name)
        out.append(label)
    return tuple(dict.fromkeys(out))


def parse_filter(raw: Any, name: str) -> ObjectFilter:
    if raw is None:
        return ObjectFilter()
    if not isinstance(raw, dict) or set(raw) - {"labels", "exclude", "min_confidence"}:
        raise InvalidCategory(name)
    conf = raw.get("min_confidence")
    return ObjectFilter(
        labels=_labels(raw.get("labels"), name),
        exclude=_labels(raw.get("exclude"), name),
        min_confidence=None if conf is None else _number(conf, name, 0.0, 1.0),
    )


def parse(raw: Any, name: str, facts: frozenset[str]) -> Measure:
    """A measure from JSON (normalised), or InvalidCategory(`name`). `facts`:
    the photo values the analyzers write."""
    if not isinstance(raw, dict):
        raise InvalidCategory(name)
    kind = raw.get("kind")
    if kind == "value":
        if set(raw) - {"kind", "key"}:
            raise InvalidCategory(name)
        key = raw.get("key")
        if not isinstance(key, str) or (key not in facts and key not in PHOTO_KEYS):
            raise InvalidCategory(name)
        return Measure("value", key=key)
    if kind != "objects" or set(raw) - {"kind", "where", "field", "agg", "k", "t"}:
        raise InvalidCategory(name)
    agg = raw.get("agg")
    if agg not in AGGS:
        raise InvalidCategory(name)
    fld = raw.get("field")
    if fld is not None and (not isinstance(fld, str) or not FIELD_RE.match(fld)):
        raise InvalidCategory(name)
    if agg in FIELD_AGGS and fld is None:
        raise InvalidCategory(name)
    k = raw.get("k")
    t = raw.get("t")
    if agg == "top_k_mean":
        if isinstance(k, bool) or not isinstance(k, int) or not K_RANGE[0] <= k <= K_RANGE[1]:
            raise InvalidCategory(name)
    elif k is not None:
        raise InvalidCategory(name)
    t_val: float | None = None
    if agg == "count_ge":
        t_val = _number(t, name, 0.0, 1.0)
    elif t is not None:
        raise InvalidCategory(name)
    return Measure("objects", where=parse_filter(raw.get("where"), name), field=fld, agg=agg,
                   k=k if agg == "top_k_mean" else None, t=t_val)  # fmt: skip


# ------------------------------------------------------------ aggregates

Items = Sequence[tuple[int, float]]
AggFn = Callable[[Items, Measure], tuple[float | None, int | None]]


def _argmax(items: Items) -> int | None:
    """The idx with the highest x (ties: the lower idx)."""
    if not items:
        return None
    return max(items, key=lambda it: (it[1], -it[0]))[0]


def _argmin(items: Items) -> int | None:
    if not items:
        return None
    return min(items, key=lambda it: (it[1], it[0]))[0]


def _max(items: Items, m: Measure) -> tuple[float | None, int | None]:
    return (max(x for _, x in items), _argmax(items)) if items else (None, None)


def _min(items: Items, m: Measure) -> tuple[float | None, int | None]:
    return (min(x for _, x in items), _argmin(items)) if items else (None, None)


def _mean(items: Items, m: Measure) -> tuple[float | None, int | None]:
    return (sum(x for _, x in items) / len(items), _argmax(items)) if items else (None, None)


def _sum(items: Items, m: Measure) -> tuple[float | None, int | None]:
    return (float(sum(x for _, x in items)), _argmax(items)) if items else (None, None)


def _top_k_mean(items: Items, m: Measure) -> tuple[float | None, int | None]:
    if not items:
        return None, None
    best = sorted(items, key=lambda it: (-it[1], it[0]))[: m.k or K_RANGE[0]]
    return sum(x for _, x in best) / len(best), best[0][0]


def _count(items: Items, m: Measure) -> tuple[float | None, int | None]:
    return float(len(items)), None


def _count_ge(items: Items, m: Measure) -> tuple[float | None, int | None]:
    t = m.t if m.t is not None else 0.0
    hits = [it for it in items if it[1] >= t - EPS]
    return float(len(hits)), _argmax(hits)


AGGREGATES: dict[str, AggFn] = {
    "count": _count, "max": _max, "min": _min, "mean": _mean, "sum": _sum,
    "top_k_mean": _top_k_mean, "count_ge": _count_ge,
}  # fmt: skip


# ------------------------------------------------------------ evaluation


@dataclass(frozen=True)
class Obj:
    idx: int
    label: str
    label_de: str
    confidence: float
    box: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class PhotoInput:
    """What a measure reads of one photo: its values (facts plus the photo
    values), its merged object list (idx order), whether a detection ran (an
    empty list is data then) and the property scores (index = idx)."""

    values: Mapping[str, float]
    objects: Sequence[Obj] = ()
    detected: bool = False
    props: Mapping[str, Sequence[float | None]] = field(default_factory=dict)


@dataclass(frozen=True)
class Result:
    value: float | None
    focus: int | None = None  # the focus object's idx
    focus_value: float | None = None  # its x (the field's value, else its confidence)


NONE = Result(None)


def evaluate(m: Measure, p: PhotoInput) -> Result:
    if m.kind == "value":
        assert m.key is not None
        return Result(p.values.get(m.key))
    if not p.detected and not p.objects:
        return NONE
    objs = [o for o in p.objects if m.where.passes(o.label, o.confidence)]
    if m.field is None:
        n = float(len(objs))
        if not m.where.labels or not objs:
            return Result(n)
        surest = max(objs, key=lambda o: (o.confidence, -o.idx))
        return Result(n, surest.idx, surest.confidence)
    if m.field == "confidence":
        items = [(o.idx, o.confidence) for o in objs]
    else:
        scores = p.props.get(m.field[5:])
        if scores is None:
            return NONE
        items = []
        for o in objs:
            x = scores[o.idx] if 0 <= o.idx < len(scores) else None
            if x is not None:
                items.append((o.idx, float(x)))
    value, focus = AGGREGATES[m.agg or "count"](items, m)
    if m.agg == "count":
        focus = _argmax(items)  # the best-rated of the counted ones
    focus_value = next((x for i, x in items if i == focus), None) if focus is not None else None
    return Result(value, focus, focus_value)
