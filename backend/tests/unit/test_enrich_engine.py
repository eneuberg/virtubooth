"""The category engine (categories v2; the specs here are mostly v1, which every
write still takes and converts): every operator, the value keys (facts, objects,
counts per label, property aggregations, photo values), top/bottom, then_by, one
per guest, ties, captions, visibility and opt-outs, validation (German field
names, v1 and v2), threshold, focus objects, the explanation, availability, the
snapshot cache."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from virtubooth.db.database import Database
from virtubooth.domain.models import new_public_id
from virtubooth.extensions.wall.enrich import engine, objects, presets
from virtubooth.extensions.wall.enrich.engine import InvalidCategory, PhotoFilter
from virtubooth.extensions.wall.enrich.objects import DetectedObject
from virtubooth.repositories.container import Repositories
from virtubooth.services.identity import create_user

T0 = "2026-10-13T18:00:00.000+00:00"
ALL = PhotoFilter(sources=None, not_after="2026-10-13T23:59:00.000+00:00")


def at(minute: int) -> str:
    return f"2026-10-13T18:{minute:02d}:00.000+00:00"


class Party:
    def __init__(self, data: Path) -> None:
        self.db = Database(data / "virtubooth.db")
        self.repos = Repositories.create(self.db, data)
        self.core = SimpleNamespace(db=self.db)
        self.users: list[int] = []
        self._minute = 0
        self._props: dict[str, int] = {}

    def user(self) -> int:
        uid = create_user(self.db, self.repos, consent_version="1", instagram=None,
                          fp_hash=None, fp_components={}, ip="10.0.0.1",
                          user_agent="pytest").id  # fmt: skip
        self.users.append(uid)
        return uid

    def photo(self, *, user: int | None = None, created_at: str | None = None,
              ext: str = "booth", objs: list[tuple[str, float]] | None = None,
              props: dict[str, list[float | None]] | None = None, **facts: float) -> int:  # fmt: skip
        if user is None:
            user = self.user()
        if created_at is None:
            self._minute += 1
            created_at = at(self._minute)
        public_id = new_public_id()
        self.repos.photos.insert(
            public_id=public_id, extension=ext, user_id=user, filename="x.jpg",
            thumb_filename="t.jpg", width=10, height=10, size=1, meta={}, created_at=created_at,
        )  # fmt: skip
        pid = self.repos.photos.internal_id(public_id)
        assert pid is not None
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO wall_analysis (photo_id, state, data, rev) VALUES (?, 'done', '{}', "
                "(SELECT COALESCE(MAX(rev), 0) + 1 FROM wall_analysis))",
                (pid,),
            )
            c.executemany(
                "INSERT INTO wall_facts (photo_id, key, value) VALUES (?,?,?)",
                [(pid, k, float(v)) for k, v in facts.items()],
            )
        if objs is not None:
            objects.append(self.db, pid, "local", "m@1",
                           [DetectedObject(lab, lab.title(), sc, None) for lab, sc in objs])  # fmt: skip
        for name, scores in (props or {}).items():
            self.scores(pid, name, scores)
        return pid

    def prop(self, name: str) -> int:
        if name not in self._props:
            with self.db.tx() as c:
                c.execute(
                    "INSERT INTO llm_properties (name, prompt, created_at) VALUES (?, 'p', ?)",
                    (name, T0),
                )
            self._props[name] = int(
                self.db.one("SELECT id FROM llm_properties WHERE name=?", (name,))[0]
            )
        return self._props[name]

    def scores(self, pid: int, name: str, scores: list[float | None]) -> None:
        prop_id = self.prop(name)
        with self.db.tx() as c:
            c.execute("INSERT OR IGNORE INTO llm_polls (id, started_at, state) VALUES (1, ?, 'done')",
                      (T0,))  # fmt: skip
            c.execute(
                "INSERT INTO property_scores (property_id, photo_id, scores, poll_id, updated_at) "
                "VALUES (?, ?, ?, 1, ?) ON CONFLICT(property_id, photo_id) DO UPDATE SET "
                "scores=excluded.scores, updated_at=excluded.updated_at",
                (prop_id, pid, json.dumps(scores), f"{T0}-{pid}-{len(scores)}-{scores}"),
            )

    def pick(self, where: list[dict[str, Any]] | None = None, by: str = "people", **sel: Any):
        label = sel.pop("label", {})
        spec = engine.validate({
            "emoji": "🎉", "title": "T", "where": where or [],
            "select": {"by": by, **sel}, "label": label,
        })  # fmt: skip
        return engine.evaluate(self.core, spec, sel.pop("flt", ALL))

    def ids(self, where: list[dict[str, Any]] | None = None, by: str = "people", **sel: Any):
        return [w.photo_id for w in self.pick(where, by, **sel)]


@pytest.fixture
def party(tmp_path: Path) -> Iterator[Party]:
    p = Party(tmp_path / "data")
    yield p
    p.db.close()


def w(value: str, op: str, operand: Any = None) -> dict[str, Any]:
    return {"value": value, "op": op, "operand": operand}


# ------------------------------------------------------------- operators


@pytest.mark.parametrize(
    ("op", "operand", "expected"),
    [
        ("gt", 3, [5, 4]),
        ("gte", 3, [5, 4, 3]),
        ("lt", 3, [2, 1]),
        ("lte", 3, [3, 2, 1]),
        ("eq", 3, [3]),
        ("ne", 3, [5, 4, 2, 1]),
        ("between", [2, 4], [4, 3, 2]),
        ("exists", None, [5, 4, 3, 2, 1]),
    ],
)
def test_number_operators(party, op, operand, expected):
    by_value = {party.photo(people=n): n for n in (1, 2, 3, 4, 5)}
    party.photo(faces=1)  # no `people` value: fails every condition but `not_exists`
    got = party.ids([w("people", op, operand)], count=10)
    assert [by_value[i] for i in got] == expected


def test_not_exists(party):
    party.photo(people=2)
    none = party.photo(faces=1)
    assert party.ids([w("people", "not_exists")], by="faces") == [none]


def test_label_operators_and_counts(party):
    hat = party.photo(objs=[("hat", 0.9), ("cup", 0.5)])
    hats = party.photo(objs=[("hat", 0.8), ("hat", 0.6), ("bottle", 0.7)])
    cup = party.photo(objs=[("cup", 0.9)])
    empty = party.photo(objs=[])
    party.photo(people=1)  # never detected: no object values at all

    def got(*where: dict[str, Any], by: str = "objects.count") -> set[int]:
        return set(party.ids(list(where), by=by, count=10, one_per_guest=False))

    assert got(w("objects", "contains", "hat")) == {hat, hats}
    assert got(w("objects", "not_contains", "hat")) == {cup, empty}
    assert got(w("objects", "contains_any", ["cup", "bottle"])) == {hat, hats, cup}
    assert got(w("objects.count:hat", "gte", 2)) == {hats}
    assert got(w("objects.count", "eq", 0)) == {empty}
    # „Anzahl von Hut“ as the ranking value: the most hats first
    assert party.ids([w("objects", "contains", "hat")], by="objects.count:hat") == [hats, hat]
    # case and spaces in labels are normalised
    assert got(w("objects", "contains", "  HAT ")) == {hat, hats}


def test_property_aggregations_and_at_label(party):
    party.prop("coolness")
    a = party.photo(objs=[("hat", 0.9), ("cup", 0.5)], props={"coolness": [0.2, 0.9]})
    b = party.photo(objs=[("hat", 0.8), ("hat", 0.6)], props={"coolness": [0.7, None]})
    c = party.photo(objs=[("cup", 0.9)], props={"coolness": [0.4]})
    party.photo(objs=[("cup", 0.9)])  # not scored yet

    def values(key: str) -> dict[int, float | None]:
        return {x.photo_id: x.value for x in party.pick([w(key, "exists")], by=key, count=10)}

    assert values("prop.coolness.max") == {a: 0.9, b: 0.7, c: 0.4}
    assert values("prop.coolness.min") == {b: 0.7, c: 0.4, a: 0.2}
    assert values("prop.coolness.sum") == pytest.approx({a: 1.1, b: 0.7, c: 0.4})
    assert values("prop.coolness.mean") == pytest.approx({b: 0.7, a: 0.55, c: 0.4})
    assert values("prop.coolness.count") == {a: 2.0, b: 1.0, c: 1.0}
    assert values("prop.coolness.at:hat") == {b: 0.7, a: 0.2}
    # the coolest object: its idx and German label (style `object`)
    (best,) = party.pick([w("prop.coolness.max", "exists")], by="prop.coolness.max", count=1,
                         label={"style": "object"})  # fmt: skip
    assert (best.photo_id, best.object_idx, best.label) == (a, 1, "Cup")
    lowest = party.pick([], by="prop.coolness.min", order="bottom", count=1)[0]
    assert (lowest.photo_id, lowest.object_idx) == (a, 0)


# -------------------------------------------------------------- selection


def test_top_bottom_ties_and_one_per_guest(party):
    g = party.user()
    old = party.photo(user=g, people=4)
    new = party.photo(user=g, people=4)  # a tie within the guest: the newer one
    top = party.photo(people=9)
    low = party.photo(people=1)
    assert party.ids(count=3) == [top, new, low]
    assert party.ids(count=3, one_per_guest=False) == [top, new, old]
    assert party.ids(order="bottom", count=2) == [low, new]
    # ties across guests: newer first
    other = party.photo(people=4)
    assert party.ids(count=3, one_per_guest=False) == [top, other, new]


def test_then_by_and_missing_values_rank_last(party):
    a = party.photo(people=3, smiles=1)
    b = party.photo(people=3, smiles=2)
    c = party.photo(people=3)  # no smiles: last among the tied
    d = party.photo(people=5)
    assert party.ids(count=4, then_by=["smiles"]) == [d, b, a, c]
    assert party.ids(count=4, then_by=[{"by": "smiles", "order": "bottom"}]) == [d, a, b, c]
    # a label value is required; `by` may be missing (ranks last)
    e = party.photo(smiles=3)
    got = party.ids([w("smiles", "exists")], by="happy_max", count=4,
                    label={"value": "smiles"})  # fmt: skip
    assert got == [e, b, a]


def test_photo_values(party):
    g = party.user()
    first = party.photo(user=g, created_at="2026-10-13T17:42:00.000+00:00")
    for _ in range(4):
        newest = party.photo(user=g)
    party.photo()
    (opening,) = party.pick([], by="photo.created_at", order="bottom", count=1,
                            label={"style": "time"})  # fmt: skip
    assert opening.photo_id == first and opening.label == "um 19:42"
    (busy,) = party.pick([w("photo.guest_photos", "gte", 5)], by="photo.guest_photos",
                         label={"one": "Foto", "many": "Fotos"})  # fmt: skip
    assert (busy.photo_id, busy.value, busy.label) == (newest, 5.0, "5 Fotos")


def test_captions():
    vt = engine.value_text
    assert vt("count", 1, "Person", "Personen") == "1 Person"
    assert vt("count", 7, "Person", "Personen") == "7 Personen"
    assert vt("percent", 0.823, "Drama", "") == "82 % Drama"
    assert vt("number", 73.4, "Farbwert", "") == "Farbwert 73"
    assert vt("decimal", 0.934, "Coolness", "") == "0,93 Coolness"
    assert vt("text", 3, "volle Bewegung", "") == "volle Bewegung"
    assert vt("none", 3, "x", "") == ""
    obj = engine.FocusObject(2, "sunglasses", "Sonnenbrille", 0.93, None)

    def cap(fmt: str, show: bool, one: str = "") -> dict[str, Any]:
        return {"format": fmt, "one": one, "many": "", "show_object": show}

    assert engine.caption(cap("decimal", True, "Coolness"), 0.93, obj) == (
        "Sonnenbrille", "0,93 Coolness", "Sonnenbrille · 0,93 Coolness",
    )  # fmt: skip
    assert engine.caption(cap("none", True), 0.93, obj) == ("Sonnenbrille", None, "Sonnenbrille")
    assert engine.caption(cap("none", True), 0.93, None) == ("Objekt", None, "Objekt")
    assert engine.caption(cap("count", False, "Ding"), 1, obj) == ("1 Ding", None, "1 Ding")


def test_only_visible_photos_and_never_opted_out_guests(party):
    shown = party.photo(people=3, colorfulness=50)
    hidden = party.photo(people=8)
    deleted = party.photo(people=9)
    beer = party.photo(people=7, ext="beer")
    late = party.photo(people=6, created_at="2026-10-13T20:00:00.000+00:00")
    pub = {pid: party.db.one("SELECT public_id FROM photos WHERE id=?", (pid,))[0]
           for pid in (hidden, deleted)}  # fmt: skip
    party.repos.photos.hide(pub[hidden], at=T0, reason="admin")
    party.repos.photos.mark_deleted(pub[deleted], at=T0)
    flt = PhotoFilter(sources=("booth",), not_after="2026-10-13T19:00:00.000+00:00")
    assert party.ids(flt=flt) == [shown]
    assert party.ids(count=5) == [beer, late, shown]
    opted = party.db.one("SELECT user_id FROM photos WHERE id=?", (beer,))[0]
    with party.db.tx() as c:
        c.execute("UPDATE users SET analysis_opt_out=1 WHERE id=?", (opted,))
    # live flag: all their photos are out, image values (basic) too
    assert party.ids(count=5) == [late, shown]
    assert beer not in party.ids(by="colorfulness", count=5)
    # the external-AI opt-out alone changes nothing here
    with party.db.tx() as c:
        c.execute("UPDATE users SET analysis_opt_out=0, ai_opt_out=1 WHERE id=?", (opted,))
    assert party.ids(count=5) == [beer, late, shown]


def test_matched_counts_condition_hits(party):
    for n in (1, 3, 4, 5):
        party.photo(people=n)
    spec = engine.validate({"emoji": "👥", "title": "T", "where": [w("people", "gte", 3)],
                            "select": {"by": "people", "count": 1}})  # fmt: skip
    result = engine.run(party.core, spec, ALL)
    assert result.matched == 3 and len(result.winners) == 1


# ------------------------------------------------------------- validation


def base(**changes: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {"emoji": "👥", "title": "Volles Haus", "line": "x",
                            "where": [], "select": {"by": "people"}}  # fmt: skip
    spec.update(changes)
    return spec


@pytest.mark.parametrize(
    ("spec", "field"),
    [
        (base(emoji="ab"), "Emoji"),
        (base(emoji="👥👥"), "Emoji"),
        (base(emoji=""), "Emoji"),
        (base(title=""), "Titel"),
        (base(title="x" * 41), "Titel"),
        (base(line="x" * 81), "Untertitel"),
        (base(where=[w("people", "gte", 1)] * 9), "Bedingungen"),
        (base(where=[w("nope", "gte", 1)]), "Bedingung 1: Wert"),
        (base(where=[w("people", "like", 1)]), "Bedingung 1: Operator"),
        (base(where=[w("people", "gte", "3")]), "Bedingung 1: Vergleichswert"),
        (base(where=[w("people", "gte", True)]), "Bedingung 1: Vergleichswert"),
        (base(where=[w("people", "between", [5, 1])]), "Bedingung 1: Vergleichswert"),
        (base(where=[w("people", "exists", 3)]), "Bedingung 1: Vergleichswert"),
        (base(where=[w("people", "contains", "hat")]), "Bedingung 1: Wert"),
        (base(where=[w("objects", "gt", 1)]), "Bedingung 1: Wert"),
        (base(where=[w("objects", "contains_any", [])]), "Bedingung 1: Vergleichswert"),
        (base(where=[w("prop.Bad.max", "exists")]), "Bedingung 1: Wert"),
        (base(where=[w("prop.cool.median", "exists")]), "Bedingung 1: Wert"),
        (base(select={"by": "objects"}), "Auswahl: Wert"),
        (base(select={"by": "people", "order": "up"}), "Auswahl: Top / Bottom"),
        (base(select={"by": "people", "count": 11}), "Anzahl"),
        (base(select={"by": "people", "count": 0}), "Anzahl"),
        (base(select={"by": "people", "then_by": ["a", "b", "c"]}), "Auswahl: danach"),
        (base(select={"by": "people", "then_by": ["nope"]}), "Auswahl: danach 1"),
        (base(select={"by": "people", "one_per_guest": "yes"}), "Ein Foto pro Gast"),
        (base(label={"style": "fancy"}), "Beschriftung: Stil"),
        (base(verdict={"prompt": ""}), "Urteil der KI (Prompt)"),
        (base(verdict={"prompt": "x" * 1001}), "Urteil der KI (Prompt)"),
        ([], "Kategorie"),
    ],
)
def test_invalid_specs_name_the_field(spec, field):
    with pytest.raises(InvalidCategory) as exc:
        engine.validate(spec)
    assert exc.value.field == field


@pytest.mark.parametrize("emoji", ["👥", "✌️", "👩‍👩‍👧", "🇩🇪", "👍🏽", "1️⃣", "🏳️‍🌈"])
def test_emoji_graphemes(emoji):
    assert engine.validate(base(emoji=emoji))["emoji"] == emoji


def test_validation_normalises():
    spec = engine.validate(base(title="  Volles   Haus ", select={"by": "people",
                                                                  "then_by": ["smiles"]}))  # fmt: skip
    assert spec["title"] == "Volles Haus" and spec["version"] == 2
    assert spec["rank"] == {"by": {"kind": "value", "key": "people"}, "order": "desc",
                            "threshold": None,
                            "then_by": [{"by": {"kind": "value", "key": "smiles"},
                                      "order": "desc"}]}  # fmt: skip
    assert spec["select"] == {"count": 3, "one_per_guest": True}
    assert spec["caption"] == {"value": None, "format": "count", "one": "", "many": "",
                               "show_object": False}  # fmt: skip
    assert spec["verdict"] is None and spec["pool"] == []
    assert engine.validate(spec) == spec


def v2(**changes: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {"version": 2, "emoji": "🏆", "title": "T",
                            "rank": {"by": {"kind": "value", "key": "people"}}}  # fmt: skip
    spec.update(changes)
    return spec


OBJ = {"kind": "objects", "field": "prop:coolness", "agg": "max"}


@pytest.mark.parametrize(
    ("spec", "field"),
    [
        (v2(version=3), "Version"),
        (v2(version=True), "Version"),
        (v2(extra=1), "Kategorie"),
        (v2(rank={"by": {"kind": "value", "key": "nope"}}), "Rang: Messgröße"),
        (v2(rank={"by": {"kind": "value", "key": "people"}, "order": "top"}), "Rang: Richtung"),
        (v2(rank={"by": {"kind": "value", "key": "people"}, "threshold": "3"}),
         "Rang: Schwelle"),
        (v2(rank={"by": {"kind": "value", "key": "people"},
                  "then_by": [{"by": OBJ}] * 3}), "Rang: danach"),
        (v2(rank={"by": {"kind": "objects", "agg": "max"}}), "Rang: Messgröße"),  # no field
        (v2(rank={"by": {**OBJ, "agg": "top_k_mean"}}), "Rang: Messgröße"),  # no k
        (v2(rank={"by": {**OBJ, "agg": "top_k_mean", "k": 6}}), "Rang: Messgröße"),
        (v2(rank={"by": {**OBJ, "k": 2}}), "Rang: Messgröße"),  # k only for top_k_mean
        (v2(rank={"by": {**OBJ, "agg": "count_ge", "t": 1.5}}), "Rang: Messgröße"),
        (v2(rank={"by": {**OBJ, "field": "prop:Bad"}}), "Rang: Messgröße"),
        (v2(rank={"by": {**OBJ, "where": {"labels": [""]}}}), "Rang: Messgröße"),
        (v2(rank={"by": {**OBJ, "where": {"min_confidence": 2}}}), "Rang: Messgröße"),
        (v2(pool=[{"measure": OBJ, "op": "contains", "operand": 1}]), "Bedingung 1: Operator"),
        (v2(pool=[{"measure": OBJ, "op": "gte", "operand": None}]),
         "Bedingung 1: Vergleichswert"),
        (v2(pool=[{"measure": {"kind": "value"}, "op": "exists"}]), "Bedingung 1: Messgröße"),
        (v2(select={"count": 11}), "Anzahl"),
        (v2(caption={"format": "fancy"}), "Beschriftung: Format"),
        (v2(caption={"show_object": True}), "Beschriftung: Objekt zeigen"),  # a fact: no object
        (v2(verdict={"count": 6}), "KI-Urteil: Anzahl"),
        (v2(verdict={"model": "claude-opus-5-5"}), "KI-Urteil: Modell"),  # Opus class: no
        (v2(verdict={"effort": "max"}), "KI-Urteil: Denkaufwand"),
        (v2(verdict={"prompt": "x" * 1001}), "KI-Urteil: Prompt"),
    ],
)  # fmt: skip
def test_invalid_v2_specs_name_the_field(spec, field):
    with pytest.raises(InvalidCategory) as exc:
        engine.validate(spec)
    assert exc.value.field == field and exc.value.version == 2


def test_v2_normalises_measures_and_labels():
    spec = engine.validate(v2(
        rank={"by": {"kind": "objects", "where": {"labels": [" Smartphone ", "phone"],
                                                  "exclude": ["person"]},
                     "agg": "count"}, "threshold": 2},
        caption={"show_object": True, "format": "count", "one": "Handy", "many": "Handys"},
        verdict={"prompt": "  ", "model": "claude-sonnet-5-5"}))  # fmt: skip
    by = spec["rank"]["by"]
    # synonyms become the canonical label, once
    assert by == {"kind": "objects", "where": {"labels": ["cell phone"], "exclude": ["person"],
                                               "min_confidence": None},
                  "field": None, "agg": "count", "k": None, "t": None}  # fmt: skip
    assert spec["rank"]["threshold"] == 2.0
    assert spec["verdict"] == {"prompt": None, "count": 3, "model": "claude-sonnet-5-5",
                               "effort": "low"}  # fmt: skip
    assert engine.validate(spec) == spec


def test_threshold_focus_object_and_box(party):
    party.prop("coolness")
    with_box = party.photo()
    objects.append(party.db, with_box, "local", "m@1", [
        DetectedObject("hat", "Hat", 0.9, None),
        DetectedObject("sunglasses", "Sunglasses", 0.5, (0.1, 0.2, 0.3, 0.4)),
    ])  # fmt: skip
    party.scores(with_box, "coolness", [0.2, 0.93])
    low = party.photo(objs=[("cup", 0.9)], props={"coolness": [0.4]})
    party.photo(objs=[("cup", 0.9)], props={"coolness": [0.1]})
    spec = engine.validate(v2(
        rank={"by": OBJ, "threshold": 0.3},
        caption={"format": "decimal", "one": "Coolness", "show_object": True}))  # fmt: skip
    result = engine.run(party.core, spec, ALL)
    assert result.matched == 2  # 0.1 is below the threshold
    first, second = result.winners
    assert (first.photo_id, first.headline, first.detail, first.label) == (
        with_box, "Sunglasses", "0,93 Coolness", "Sunglasses · 0,93 Coolness",
    )  # fmt: skip
    assert first.object == engine.FocusObject(1, "sunglasses", "Sunglasses", 0.93,
                                              (0.1, 0.2, 0.3, 0.4))  # fmt: skip
    assert second.photo_id == low and second.object is not None and second.object.box is None
    # asc: at most the threshold
    spec = engine.validate(v2(rank={"by": OBJ, "order": "asc", "threshold": 0.3}))
    assert [w.value for w in engine.evaluate(party.core, spec, ALL)] == [0.1]


def test_explain():
    def ex(**rank: Any) -> str:
        return engine.explain(engine.validate(v2(rank=rank)))

    assert ex(by={"kind": "value", "key": "people"}, threshold=3) == (
        "Höchster Wert bei „Personen“, mindestens 3"
    )
    assert ex(by={"kind": "value", "key": "sharpness"}, order="asc", threshold=80) == (
        "Niedrigster Wert bei „Schärfe“, höchstens 80"
    )
    assert ex(by={**OBJ, "where": {"exclude": ["person"]}}) == (
        "Höchster coolness-Wert unter allen Objekten (ohne person)"
    )
    assert (
        ex(by={"kind": "objects", "agg": "count"}, threshold=3)
        == "Die meisten Objekte, mindestens 3"
    )
    assert ex(by={**OBJ, "agg": "top_k_mean", "k": 2}) == (
        "Höchster Schnitt der besten 2 coolness-Werte"
    )
    assert ex(by={"kind": "value", "key": "photo.created_at"}, order="asc") == "Das früheste Foto"
    assert ex(by={**OBJ, "agg": "count_ge", "t": 0.7}) == "Die meisten Objekte mit coolness ab 0,70"


# ------------------------------------------------- availability and cache


def test_availability():
    everything = {"basic", "faces", "emotion", "gestures", "objects", "tags", "age"}
    specs = {pid: engine.validate(spec) for pid, spec, _ in presets.PRESETS}

    def reason(pid: str, active: set[str], props: dict[str, bool] | None = None) -> str | None:
        return engine.spec_availability(specs[pid], active, props or {}, False)

    assert all(reason(p, everything) is None for p in presets.CLASSIC)
    assert reason("haende_hoch", everything - {"gestures"}) == (
        "Braucht die Analyse „Hände und Gesten“."
    )
    # people: the detector or the faces
    assert reason("volles_haus", {"basic", "faces"}) is None
    assert reason("volles_haus", {"basic"}) == "Braucht die Analyse „Objekte“."
    # FairFace (`age`) only ranks; the age groups are what is shown
    assert reason("generationen", {"basic", "faces", "tags"}) is None
    assert reason("eroeffnung", set()) is None and reason("farbexplosion", {"basic"}) is None
    assert reason("coolstes_objekt", everything) == "Braucht die Eigenschaft „coolness“."
    assert reason("coolstes_objekt", everything, {"coolness": True}) is None  # trashed: readable
    assert reason("coolstes_objekt", everything - {"objects"}, {"coolness": False}) == (
        "Braucht die Analyse „Objekte“."
    )


def test_the_snapshot_is_cached_until_something_changes(party):
    a = party.photo(people=3)
    spec = engine.validate(base())
    engine.evaluate(party.core, spec, ALL)
    loads = engine._loads[0]
    engine.evaluate(party.core, spec, ALL)
    assert engine._loads[0] == loads
    b = party.photo(people=5)  # a new analysis bumps the rev
    assert [x.photo_id for x in engine.evaluate(party.core, spec, ALL)] == [b, a]
    assert engine._loads[0] == loads + 1
    party.scores(a, "coolness", [0.5])  # a poll's new scores
    engine.evaluate(party.core, spec, ALL)
    assert engine._loads[0] == loads + 2
