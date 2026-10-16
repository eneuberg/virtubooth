"""Category specs version 1 (PLAN-NIGHT N13) and the converter to version 2.

v1 named its values with string keys (`people`, `objects.count:hat`,
`prop.coolness.max`, `prop.coolness.at:hat`, …), filtered with `where` and
ranked with `select.by`. v2 (engine.py) has one building block for all of that,
the measure (measures.py). This module keeps the v1 validator exactly as it was
(a stored v1 spec, an old editor's or an import's v1 spec still validates the
same) and converts with `upgrade()`, a pure function:

| v1                                   | v2                                              |
|--------------------------------------|-------------------------------------------------|
| `where[i] {value, op, operand}`      | `pool[i] {measure, op, operand}`                |
| `objects contains L`                 | `objects({labels:[L]}).count ≥ 1`               |
| `objects not_contains L`             | `objects({labels:[L]}).count = 0`               |
| `objects contains_any [..]`          | `objects({labels:[..]}).count ≥ 1`              |
| `objects.count[:L]`                  | `objects([{labels:[L]}]).count`                 |
| `prop.N.max/min/sum/mean/count`      | `objects.agg(prop:N)`                           |
| `prop.N.at:L`                        | `objects({labels:[L]}).max(prop:N)`             |
| `select.by/order top/bottom`         | `rank.by`, `order desc/asc`                     |
| a `gte` (top) / `lte` (bottom) condition on `select.by` | `rank.threshold`             |
| `exists` on `select.by` (shown = by) | dropped: a winner needs the shown value anyway  |
| `select.then_by`                     | `rank.then_by`                                  |
| `label {value, style, one, many}`    | `caption {value, format, one, many, show_object}` |
| `verdict {prompt}`                   | `verdict {prompt, count: 1, model: null, effort: low}` |

`downgrade()` goes the other way where v1 can say it (the v1 category editor,
until the v2 editor replaces it); None otherwise.
"""

from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from .measures import InvalidCategory

NUMERIC_OPS = ("gt", "lt", "gte", "lte", "eq", "ne")
OPS = (*NUMERIC_OPS, "between", "exists", "not_exists", "contains", "not_contains",
       "contains_any")  # fmt: skip
LABEL_OPS = ("contains", "not_contains", "contains_any")
STYLES = ("count", "percent", "number", "time", "fixed", "object")
AGGREGATES = ("max", "min", "sum", "mean", "count")
MAX_WHERE = 8
MAX_THEN_BY = 2
MAX_COUNT = 10
MAX_ANY = 20
LABEL_MAX = 60
PROPERTY_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_PROP_REF = re.compile(r"prop\.([a-z][a-z0-9_]{1,30})\.")

RefKind = Literal[
    "fact", "labels", "count", "count_label", "prop", "prop_at", "created", "guest_photos"
]


def _all_facts() -> frozenset[str]:
    from .analyzers import INFOS

    return frozenset(f for i in INFOS for f in i.facts)


# ------------------------------------------------------------- value keys


@dataclass(frozen=True)
class ValueRef:
    key: str
    kind: RefKind
    fact: str | None = None
    prop: str | None = None
    agg: str | None = None
    label: str | None = None

    @property
    def is_labels(self) -> bool:
        return self.kind == "labels"


def _label(raw: str) -> str | None:
    label = raw.strip().lower()
    if not label or len(label) > LABEL_MAX or any(ord(ch) < 32 for ch in label):
        return None
    return label


def parse_key(key: object) -> ValueRef | None:
    """The value a v1 key names, or None when it is not a valid key."""
    if not isinstance(key, str) or not key or len(key) > 120:
        return None
    if key in _all_facts():
        return ValueRef(key, "fact", fact=key)
    if key == "objects":
        return ValueRef(key, "labels")
    if key == "objects.count":
        return ValueRef(key, "count")
    if key.startswith("objects.count:"):
        label = _label(key[len("objects.count:") :])
        return ValueRef(f"objects.count:{label}", "count_label", label=label) if label else None
    if key == "photo.created_at":
        return ValueRef(key, "created")
    if key == "photo.guest_photos":
        return ValueRef(key, "guest_photos")
    if key.startswith("prop."):
        name, _, tail = key[len("prop.") :].partition(".")
        if not PROPERTY_RE.match(name):
            return None
        if tail in AGGREGATES:
            return ValueRef(key, "prop", prop=name, agg=tail)
        if tail.startswith("at:"):
            label = _label(tail[3:])
            if label:
                return ValueRef(f"prop.{name}.at:{label}", "prop_at", prop=name, label=label)
    return None


def referenced_properties(spec: Any) -> list[str]:
    """Property names a v1 spec uses (`prop.<name>.…` anywhere), in order."""
    return list(dict.fromkeys(_PROP_REF.findall(json.dumps(spec, ensure_ascii=False))))


# --------------------------------------------------------------- validate


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


def _value(key: Any, field: str, *, numeric: bool) -> ValueRef:
    ref = parse_key(key)
    if ref is None or (numeric and ref.is_labels):
        raise InvalidCategory(field)
    return ref


def _label_operand(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidCategory(field)
    label = _label(value)
    if label is None:
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
    """The normalised v1 spec, or InvalidCategory naming the field (German).
    Unchanged from v1 (emoji: engine.one_grapheme)."""
    from .engine import one_grapheme

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


# ---------------------------------------------------------------- upgrade

_NO_FILTER: dict[str, Any] = {"labels": [], "exclude": [], "min_confidence": None}


def _objects(agg: str, *, labels: list[str] | None = None, field: str | None = None
             ) -> dict[str, Any]:  # fmt: skip
    return {"kind": "objects", "where": {**_NO_FILTER, "labels": labels or []}, "field": field,
            "agg": agg, "k": None, "t": None}  # fmt: skip


def measure_of(key: str) -> dict[str, Any]:
    """The v2 measure for a (numeric) v1 key."""
    ref = parse_key(key)
    if ref is None or ref.kind == "labels":
        raise InvalidCategory("Wert")
    if ref.kind in ("fact", "created", "guest_photos"):
        return {"kind": "value", "key": ref.key}
    if ref.kind == "count":
        return _objects("count")
    if ref.kind == "count_label":
        assert ref.label is not None
        return _objects("count", labels=[ref.label])
    if ref.kind == "prop":
        return _objects(ref.agg or "max", field=f"prop:{ref.prop}")
    assert ref.label is not None
    return _objects("max", labels=[ref.label], field=f"prop:{ref.prop}")


def _condition(w: dict[str, Any]) -> dict[str, Any]:
    op, operand = w["op"], w["operand"]
    if op in LABEL_OPS:
        labels = operand if isinstance(operand, list) else [operand]
        measure = _objects("count", labels=list(labels))
        if op == "not_contains":
            return {"measure": measure, "op": "eq", "operand": 0.0}
        return {"measure": measure, "op": "gte", "operand": 1.0}
    return {"measure": measure_of(w["value"]), "op": op, "operand": operand}


_FORMATS = {"count": "count", "percent": "percent", "number": "number", "time": "time",
            "fixed": "text", "object": "none"}  # fmt: skip


def upgrade(v1: dict[str, Any]) -> dict[str, Any]:
    """A validated v1 spec as a v2 spec (not yet validated: engine.validate)."""
    sel, lab = v1["select"], v1["label"]
    by = sel["by"]
    top = sel["order"] == "top"
    shown = lab["value"] or by
    where = list(v1["where"])
    threshold: float | None = None
    for i, w in enumerate(where):
        if w["value"] == by and w["op"] == ("gte" if top else "lte"):
            threshold = float(w["operand"])
            del where[i]
            break
    # `exists` on the ranking value is what the displayed value requires anyway
    where = [w for w in where if not (w["op"] == "exists" and w["value"] == by == shown)]
    style = lab["style"]
    caption = {
        "value": measure_of(lab["value"]) if lab["value"] else None,
        "format": _FORMATS[style], "one": lab["one"], "many": lab["many"],
        "show_object": style == "object",
    }  # fmt: skip
    if style == "object" and not _has_focus(measure_of(shown)):
        # v1 named the detector's surest object here; v2 frames only a focus object
        caption.update(format="text", one=lab["one"] or "Objekt", show_object=False)
    verdict = v1.get("verdict")
    return {
        "version": 2, "emoji": v1["emoji"], "title": v1["title"], "line": v1["line"],
        "pool": [_condition(w) for w in where],
        "rank": {"by": measure_of(by), "order": "desc" if top else "asc",
                 "threshold": threshold,
                 "then_by": [{"by": measure_of(t["by"]),
                           "order": "desc" if t["order"] == "top" else "asc"}
                          for t in sel["then_by"]]},
        "select": {"count": sel["count"], "one_per_guest": sel["one_per_guest"]},
        "caption": caption,
        "verdict": {"prompt": verdict["prompt"], "count": 1, "model": None, "effort": "low"}
        if verdict else None,
    }  # fmt: skip


def _has_focus(m: dict[str, Any]) -> bool:
    if m["kind"] != "objects":
        return False
    if m["agg"] == "count" and m["field"] is None:
        return bool(m["where"]["labels"])
    return True


# --------------------------------------------------------------- downgrade


def key_of(m: dict[str, Any]) -> str | None:
    """The v1 key of a (normalised) v2 measure, None when v1 cannot say it."""
    if m["kind"] == "value":
        return str(m["key"])
    where = m["where"]
    if where["exclude"] or where["min_confidence"] is not None or len(where["labels"]) > 1:
        return None
    label = where["labels"][0] if where["labels"] else None
    agg, fld = m["agg"], m["field"]
    if fld is None:
        if agg != "count":
            return None
        return f"objects.count:{label}" if label else "objects.count"
    if not fld.startswith("prop:"):
        return None
    name = fld[5:]
    if label is not None:
        return f"prop.{name}.at:{label}" if agg == "max" else None
    return f"prop.{name}.{agg}" if agg in AGGREGATES else None


def _cond_v1(c: dict[str, Any]) -> dict[str, Any] | None:
    m, op, operand = c["measure"], c["op"], c["operand"]
    where = m.get("where") or {}
    plain_count = (
        m["kind"] == "objects" and m["agg"] == "count" and m["field"] is None
        and where["labels"] and not where["exclude"] and where["min_confidence"] is None
    )  # fmt: skip
    if plain_count and op == "gte" and operand == 1:
        labels = list(where["labels"])
        if len(labels) == 1:
            return {"value": "objects", "op": "contains", "operand": labels[0]}
        return {"value": "objects", "op": "contains_any", "operand": labels}
    if plain_count and op == "eq" and operand == 0 and len(where["labels"]) == 1:
        return {"value": "objects", "op": "not_contains", "operand": where["labels"][0]}
    key = key_of(m)
    return None if key is None else {"value": key, "op": op, "operand": operand}


_STYLES = {"count": "count", "percent": "percent", "number": "number", "time": "time",
           "text": "fixed"}  # fmt: skip


def downgrade(spec: dict[str, Any]) -> dict[str, Any] | None:
    """A validated v2 spec in v1 shape (the v1 editor), None when v1 cannot say it.
    `upgrade(downgrade(s))` is `s` up to the verdict's model/effort/count."""
    spec = copy.deepcopy(spec)
    rank, cap = spec["rank"], spec["caption"]
    by = key_of(rank["by"])
    if by is None:
        return None
    where: list[dict[str, Any]] = []
    for c in spec["pool"]:
        w = _cond_v1(c)
        if w is None:
            return None
        where.append(w)
    top = rank["order"] == "desc"
    if rank["threshold"] is not None:
        where.insert(0, {"value": by, "op": "gte" if top else "lte",
                         "operand": rank["threshold"]})  # fmt: skip
    then_by = []
    for t in rank["then_by"]:
        key = key_of(t["by"])
        if key is None:
            return None
        then_by.append({"by": key, "order": "top" if t["order"] == "desc" else "bottom"})
    value = key_of(cap["value"]) if cap["value"] else None
    if cap["value"] and value is None:
        return None
    if cap["show_object"]:
        if cap["format"] != "none":
            return None
        style = "object"
    elif cap["format"] in _STYLES:
        style = _STYLES[cap["format"]]
    else:
        return None
    verdict = spec.get("verdict")
    if verdict and not verdict.get("prompt"):
        return None
    return {
        "emoji": spec["emoji"], "title": spec["title"], "line": spec["line"], "where": where,
        "select": {"by": by, "order": "top" if top else "bottom", "count": spec["select"]["count"],
                   "then_by": then_by, "one_per_guest": spec["select"]["one_per_guest"]},
        "label": {"value": value, "style": style, "one": cap["one"], "many": cap["many"]},
        "verdict": {"prompt": verdict["prompt"]} if verdict else None,
    }  # fmt: skip
