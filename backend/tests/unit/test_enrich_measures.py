"""Measures (categories v2): every aggregate, missing values, the focus object
(ties: the lower idx), object filters (labels, exclude, min_confidence, label
canonicalisation), and score arrays shorter than the object list."""

from __future__ import annotations

from typing import Any

import pytest

from virtubooth.extensions.wall.enrich import measures
from virtubooth.extensions.wall.enrich.measures import InvalidCategory, Obj, PhotoInput

FACTS = frozenset({"people", "faces"})
OBJS = (
    Obj(0, "person", "Person", 0.95),
    Obj(1, "hat", "Hut", 0.6),
    Obj(2, "hat", "Hut", 0.8),
    Obj(3, "cup", "Becher", 0.4),
)


def m(**raw: Any) -> measures.Measure:
    return measures.parse({"kind": "objects", **raw}, "x", FACTS)


def photo(scores: list[float | None] | None = (0.2, 0.9, 0.9, 0.1), **kw: Any) -> PhotoInput:  # type: ignore[assignment]
    props = {"coolness": list(scores)} if scores is not None else {}
    return PhotoInput({"people": 3.0}, kw.pop("objects", OBJS), kw.pop("detected", True), props)


def ev(measure: measures.Measure, p: PhotoInput | None = None) -> tuple[Any, Any, Any]:
    r = measures.evaluate(measure, p or photo())
    return r.value, r.focus, r.focus_value


C = "prop:coolness"


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ({"agg": "count"}, (4.0, None, None)),
        ({"agg": "count", "field": C}, (4.0, 1, 0.9)),  # the best-rated, lower idx on a tie
        ({"agg": "max", "field": C}, (0.9, 1, 0.9)),
        ({"agg": "min", "field": C}, (0.1, 3, 0.1)),
        ({"agg": "mean", "field": C}, (pytest.approx(0.525), 1, 0.9)),
        ({"agg": "sum", "field": C}, (pytest.approx(2.1), 1, 0.9)),
        ({"agg": "top_k_mean", "field": C, "k": 2}, (pytest.approx(0.9), 1, 0.9)),
        ({"agg": "top_k_mean", "field": C, "k": 3}, (pytest.approx(2 / 3), 1, 0.9)),
        ({"agg": "count_ge", "field": C, "t": 0.5}, (2.0, 1, 0.9)),
        ({"agg": "count_ge", "field": C, "t": 0.95}, (0.0, None, None)),
        ({"agg": "max", "field": "confidence"}, (0.95, 0, 0.95)),
        ({"agg": "min", "field": "confidence"}, (0.4, 3, 0.4)),
    ],
)
def test_aggregates(raw, want):
    assert ev(m(**raw)) == want


def test_value_measures():
    assert ev(measures.parse({"kind": "value", "key": "people"}, "x", FACTS)) == (3.0, None, None)
    assert ev(measures.parse({"kind": "value", "key": "faces"}, "x", FACTS)) == (None, None, None)
    photo_value = measures.parse({"kind": "value", "key": "photo.guest_photos"}, "x", FACTS)
    assert photo_value.key == "photo.guest_photos"
    with pytest.raises(InvalidCategory):
        measures.parse({"kind": "value", "key": "nope"}, "x", FACTS)


def test_missing_values():
    never = photo(objects=(), detected=False)
    empty = photo(objects=(), detected=True)
    unscored = photo(scores=None)
    nulls = photo(scores=[None, None, None, None])
    # no detection ran: no object measure at all; detected but empty: counts are 0
    assert ev(m(agg="count"), never) == (None, None, None)
    assert ev(m(agg="count"), empty) == (0.0, None, None)
    assert ev(m(agg="max", field=C), empty) == (None, None, None)
    # not scored: no prop: value, not even a count; confidence still works
    assert ev(m(agg="count", field=C), unscored) == (None, None, None)
    assert ev(m(agg="max", field="confidence"), unscored)[0] == 0.95
    # all null: count 0, the rest none
    assert ev(m(agg="count", field=C), nulls) == (0.0, None, None)
    assert ev(m(agg="count_ge", field=C, t=0.1), nulls) == (0.0, None, None)
    for agg in ("max", "min", "mean", "sum"):
        assert ev(m(agg=agg, field=C), nulls) == (None, None, None)
    assert ev(m(agg="top_k_mean", field=C, k=2), nulls) == (None, None, None)


def test_a_shorter_score_array_is_no_value_for_the_rest():
    short = photo(scores=[0.2, 0.9])  # an older photo whose list grew after the poll
    assert ev(m(agg="count", field=C), short) == (2.0, 1, 0.9)
    assert ev(m(agg="min", field=C, where={"labels": ["cup"]}), short) == (None, None, None)
    long = photo(scores=[0.2, 0.9, 0.9, 0.1, 1.0])  # an extra score has no object: ignored
    assert ev(m(agg="max", field=C), long) == (0.9, 1, 0.9)


def test_filters():
    assert ev(m(agg="count", where={"labels": ["hat"]})) == (2.0, 2, 0.8)  # the surest hat
    assert ev(m(agg="count", where={"exclude": ["person"]})) == (3.0, None, None)
    assert ev(m(agg="count", where={"min_confidence": 0.6})) == (3.0, None, None)
    assert ev(m(agg="max", field=C, where={"labels": ["cup", "person"]})) == (0.2, 0, 0.2)
    assert ev(m(agg="max", field=C, where={"exclude": ["hat"]})) == (0.2, 0, 0.2)
    # ties: the lower idx (both hats 0.9)
    assert ev(m(agg="max", field=C, where={"labels": ["hat"]}))[1] == 1
    # the surest hat on a tie in confidence: the lower idx
    tie = photo(objects=(Obj(0, "hat", "Hut", 0.7), Obj(1, "hat", "Hut", 0.7)))
    assert ev(m(agg="count", where={"labels": ["hat"]}), tie) == (2.0, 0, 0.7)


def test_labels_are_canonical():
    f = measures.parse_filter({"labels": [" Smartphone", "PHONE", "Party-Hut"],
                               "exclude": ["Woman"]}, "x")  # fmt: skip
    assert f.labels == ("cell phone", "party hut") and f.exclude == ("person",)
    for bad in ([""], ["x" * 61], [1], ["a\x00"], ["a"] * 21):
        with pytest.raises(InvalidCategory):
            measures.parse_filter({"labels": bad}, "x")
    with pytest.raises(InvalidCategory):
        measures.parse_filter({"labels": [], "other": 1}, "x")


def test_focus_rules():
    assert not m(agg="count").has_focus
    assert m(agg="count", where={"labels": ["hat"]}).has_focus
    assert m(agg="count", field=C).has_focus
    assert all(m(agg=a, field=C).has_focus for a in ("max", "min", "mean", "sum"))
    assert not measures.parse({"kind": "value", "key": "people"}, "x", FACTS).has_focus


def test_to_json_round_trip():
    raw = m(agg="top_k_mean", field=C, k=3, where={"labels": ["hat"]}).to_json()
    assert raw == {"kind": "objects", "where": {"labels": ["hat"], "exclude": [],
                                                "min_confidence": None},
                   "field": C, "agg": "top_k_mean", "k": 3, "t": None}  # fmt: skip
    assert measures.parse(raw, "x", FACTS).to_json() == raw
