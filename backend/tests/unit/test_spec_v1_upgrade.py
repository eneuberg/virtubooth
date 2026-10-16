"""spec_v1.upgrade (categories v2): every row of the mapping table, the
threshold taken out of the conditions, `exists` on the ranking value dropped,
idempotence, invalid v1 specs; and the downgrade the v1 editor reads."""

from __future__ import annotations

from typing import Any

import pytest

from virtubooth.extensions.wall.enrich import engine, presets, presets_v1, spec_v1
from virtubooth.extensions.wall.enrich.measures import InvalidCategory

NONE = {"labels": [], "exclude": [], "min_confidence": None}


def objs(agg: str, *, labels: list[str] | None = None, field: str | None = None) -> dict[str, Any]:
    return {"kind": "objects", "where": {**NONE, "labels": labels or []}, "field": field,
            "agg": agg, "k": None, "t": None}  # fmt: skip


def val(key: str) -> dict[str, Any]:
    return {"kind": "value", "key": key}


def v1(where: list[dict[str, Any]] | None = None, by: str = "people", **sel: Any) -> dict[str, Any]:
    label = sel.pop("label", {})
    verdict = sel.pop("verdict", None)
    return spec_v1.validate({"emoji": "🎉", "title": "T", "where": where or [],
                             "select": {"by": by, **sel}, "label": label,
                             "verdict": verdict})  # fmt: skip


def w(value: str, op: str, operand: Any = None) -> dict[str, Any]:
    return {"value": value, "op": op, "operand": operand}


@pytest.mark.parametrize(
    ("key", "measure"),
    [
        ("people", val("people")),
        ("photo.created_at", val("photo.created_at")),
        ("photo.guest_photos", val("photo.guest_photos")),
        ("objects.count", objs("count")),
        ("objects.count:hat", objs("count", labels=["hat"])),
        ("prop.coolness.max", objs("max", field="prop:coolness")),
        ("prop.coolness.min", objs("min", field="prop:coolness")),
        ("prop.coolness.sum", objs("sum", field="prop:coolness")),
        ("prop.coolness.mean", objs("mean", field="prop:coolness")),
        ("prop.coolness.count", objs("count", field="prop:coolness")),
        ("prop.coolness.at:hat", objs("max", labels=["hat"], field="prop:coolness")),
    ],
)
def test_value_keys(key, measure):
    assert spec_v1.measure_of(key) == measure
    assert spec_v1.key_of(measure) == key  # and back


@pytest.mark.parametrize(
    ("cond", "pool"),
    [
        (w("faces", "eq", 1), {"measure": val("faces"), "op": "eq", "operand": 1.0}),
        (w("faces", "between", [1, 3]),
         {"measure": val("faces"), "op": "between", "operand": [1.0, 3.0]}),
        (w("faces", "not_exists"), {"measure": val("faces"), "op": "not_exists", "operand": None}),
        (w("objects", "contains", "hat"),
         {"measure": objs("count", labels=["hat"]), "op": "gte", "operand": 1.0}),
        (w("objects", "not_contains", "hat"),
         {"measure": objs("count", labels=["hat"]), "op": "eq", "operand": 0.0}),
        (w("objects", "contains_any", ["cup", "hat"]),
         {"measure": objs("count", labels=["cup", "hat"]), "op": "gte", "operand": 1.0}),
    ],
)  # fmt: skip
def test_conditions(cond, pool):
    spec = spec_v1.upgrade(v1([cond], by="smiles"))
    assert spec["pool"] == [pool]
    assert engine.validate(spec)["pool"] == [pool]


def test_selection_threshold_and_caption():
    spec = spec_v1.upgrade(v1([w("people", "gte", 3), w("smiles", "gte", 1),
                               w("people", "gte", 5)], count=4,
                              then_by=["smiles", {"by": "hands", "order": "bottom"}],
                              one_per_guest=False, label={"one": "P", "many": "Ps"}))  # fmt: skip
    # the first `gte` on the ranking value is the threshold; the rest stay conditions
    assert spec["rank"] == {"by": val("people"), "order": "desc", "threshold": 3.0,
                            "then": [{"by": val("smiles"), "order": "desc"},
                                     {"by": val("hands"), "order": "asc"}]}  # fmt: skip
    assert [c["measure"] for c in spec["pool"]] == [val("smiles"), val("people")]
    assert spec["select"] == {"count": 4, "one_per_guest": False}
    assert spec["caption"] == {"value": None, "format": "count", "one": "P", "many": "Ps",
                               "show_object": False}  # fmt: skip
    # bottom: `lte` is the threshold, `gte` stays
    spec = spec_v1.upgrade(v1([w("sharpness", "gte", 5), w("sharpness", "lte", 80)],
                              by="sharpness", order="bottom"))  # fmt: skip
    assert spec["rank"]["threshold"] == 80.0 and spec["rank"]["order"] == "asc"
    assert spec["pool"] == [{"measure": val("sharpness"), "op": "gte", "operand": 5.0}]


@pytest.mark.parametrize(
    ("style", "fmt", "show"),
    [("count", "count", False), ("percent", "percent", False), ("number", "number", False),
     ("time", "time", False), ("fixed", "text", False)],
)  # fmt: skip
def test_styles(style, fmt, show):
    cap = spec_v1.upgrade(v1(label={"style": style, "one": "x", "value": "faces"}))["caption"]
    assert (cap["format"], cap["show_object"], cap["value"]) == (fmt, show, val("faces"))


def test_object_style_exists_and_verdict():
    spec = spec_v1.upgrade(v1([w("prop.coolness.max", "exists")], by="prop.coolness.max",
                              label={"style": "object"}, verdict={"prompt": "Wer?"}))  # fmt: skip
    # `exists` on the shown ranking value is redundant: dropped
    assert spec["pool"] == []
    assert spec["caption"]["format"] == "none" and spec["caption"]["show_object"] is True
    assert spec["verdict"] == {"prompt": "Wer?", "count": 1, "model": None, "effort": "low"}
    # with another displayed value it is kept
    spec = spec_v1.upgrade(v1([w("prop.coolness.max", "exists")], by="prop.coolness.max",
                              label={"value": "people"}))  # fmt: skip
    assert len(spec["pool"]) == 1
    # an object style without an object to point at becomes a text
    spec = spec_v1.upgrade(v1(by="people", label={"style": "object"}))
    assert spec["caption"] == {"value": None, "format": "text", "one": "Objekt", "many": "",
                               "show_object": False}  # fmt: skip


def test_idempotent_and_invalid():
    old = presets_v1.BY_ID["action_shot"]
    once = engine.validate(old)
    assert engine.validate(once) == once  # a v2 spec stays as it is
    assert once == presets.BY_ID["action_shot"][0]
    for bad in ({"emoji": "🎉", "title": "T"}, {"emoji": "🎉", "title": "T", "select": {"by": "x"}},
                {"emoji": "🎉", "title": "T", "select": {"by": "people"},
                 "where": [w("people", "contains", "hat")]}):  # fmt: skip
        with pytest.raises(InvalidCategory) as exc:
            engine.validate(bad)
        assert exc.value.version == 1


def test_downgrade_round_trips_what_v1_can_say():
    for pid, spec, _ in presets.PRESETS:
        old = spec_v1.downgrade(engine.validate(spec))
        if pid in ("am_unerwartetsten", "meiste_objekte", "albernstes_objekt"):
            assert old is None, pid  # top_k_mean, confidence, decimal: not in v1
            continue
        if pid == "coolstes_objekt":
            assert old is None  # decimal caption
            continue
        assert old is not None, pid
        assert engine.validate(old) == engine.validate(spec) | {
            "verdict": engine.validate(old)["verdict"]
        }, pid
    # v2 only: an exclude filter, a min confidence
    spec = engine.validate({"version": 2, "emoji": "🎉", "title": "T", "rank": {"by": {
        "kind": "objects", "agg": "count", "where": {"exclude": ["person"]}}}})  # fmt: skip
    assert spec_v1.downgrade(spec) is None
