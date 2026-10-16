"""The category engine (PLAN-NIGHT §4.2): every operator, the value keys
(facts, objects, counts per label, property aggregations, photo values),
top/bottom, then_by, one per guest, ties, labels, visibility and opt-outs,
validation (German field names), availability, the snapshot cache."""

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

    def prop(self, name: str, *, inactive: bool = False) -> int:
        if name not in self._props:
            with self.db.tx() as c:
                c.execute(
                    "INSERT INTO llm_properties (name, prompt, created_at, inactive_at) "
                    "VALUES (?, 'p', ?, ?)",
                    (name, T0, T0 if inactive else None),
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


def test_labels():
    assert engine.label_text("count", 1, "Person", "Personen") == "1 Person"
    assert engine.label_text("count", 7, "Person", "Personen") == "7 Personen"
    assert engine.label_text("percent", 0.823, "Drama", "") == "82 % Drama"
    assert engine.label_text("number", 73.4, "Farbwert", "") == "Farbwert 73"
    assert engine.label_text("fixed", 3, "volle Bewegung", "") == "volle Bewegung"
    assert engine.label_text("object", 0.9, "", "", "Sonnenbrille") == "Sonnenbrille"
    assert engine.label_text("object", 0.9, "", "", None) == "Objekt"


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
    assert spec["title"] == "Volles Haus"
    assert spec["select"] == {"by": "people", "order": "top", "count": 3,
                              "then_by": [{"by": "smiles", "order": "top"}],
                              "one_per_guest": True}  # fmt: skip
    assert spec["label"] == {"value": None, "style": "count", "one": "", "many": ""}
    assert spec["verdict"] is None
    assert engine.validate(spec) == spec


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
    assert reason("coolstes_objekt", everything, {"coolness": True}) is None  # inactive: readable


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
