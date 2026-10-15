"""The values a wall category can test and rank by (PLAN-NIGHT §4.2, N13).

Keys:
- `<fact>`                     every fact of every analyzer (`wall_facts`)
- `objects`                    the photo's object labels (for contains/…)
- `objects.count`              how many objects
- `objects.count:<label>`      how many objects with this label („Anzahl von …“)
- `prop.<name>.max|min|sum|mean|count`  an LLM property's scores, aggregated
- `prop.<name>.at:<label>`     the best score of the objects with this label
- `photo.created_at`           unix seconds
- `photo.guest_photos`         the guest's visible photos

`catalogue()` lists them for the editor (facts from the analyzer registry,
properties including archived ones) with the object labels seen so far.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from ....db.database import Database
from .analyzers import BY_NAME, INFOS

ValueKind = Literal["number", "count", "labels", "time"]
RefKind = Literal[
    "fact", "labels", "count", "count_label", "prop", "prop_at", "created", "guest_photos"
]
AGGREGATES = ("max", "min", "sum", "mean", "count")
PROPERTY_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
LABEL_MAX = 60

# fact → (German title, kind, unit)
FACTS: dict[str, tuple[str, ValueKind, str]] = {
    "brightness": ("Helligkeit", "number", "0–1"),
    "colorfulness": ("Farbigkeit", "number", ""),
    "sharpness": ("Schärfe", "number", ""),
    "faces": ("Gesichter", "count", ""),
    "smiles": ("Lächeln", "count", ""),
    "eyes_closed": ("Geschlossene Augen", "count", ""),
    "mouth_open": ("Offene Münder", "count", ""),
    "face_area_max": ("Größtes Gesicht (Bildanteil)", "number", "0–1"),
    "happy_max": ("Fröhlichkeit (höchste)", "number", "0–1"),
    "sad_max": ("Traurigkeit (höchste)", "number", "0–1"),
    "surprise_max": ("Überraschung (höchste)", "number", "0–1"),
    "hands": ("Hände", "count", ""),
    "peace": ("Peace-Zeichen", "count", ""),
    "thumbs_up": ("Daumen hoch", "count", ""),
    "rock": ("Pommesgabeln", "count", ""),
    "people": ("Personen", "count", ""),
    "drinks": ("Gläser und Flaschen", "count", ""),
    "phones": ("Handys", "count", ""),
    "glasses": ("Brillen", "count", ""),
    "hats": ("Hüte", "count", ""),
    "age_groups": ("Altersgruppen", "count", ""),
    "age_spread": ("Altersspanne", "number", "Jahre"),
}
AGG_TITLES = {
    "max": "höchster Wert", "min": "niedrigster Wert", "sum": "Summe", "mean": "Durchschnitt",
    "count": "Anzahl bewerteter Objekte",
}  # fmt: skip


def producers(fact: str) -> tuple[str, ...]:
    """The analyzers that write `fact` (`people`: the detector, else faces)."""
    if fact == "people":
        return ("objects", "faces")
    return tuple(i.name for i in INFOS if fact in i.facts)


ALL_FACTS = frozenset(f for i in INFOS for f in i.facts)


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


def parse(key: object) -> ValueRef | None:
    """The value a key names, or None when it is not a valid key."""
    if not isinstance(key, str) or not key or len(key) > 120:
        return None
    if key in ALL_FACTS:
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
        rest = key[len("prop.") :]
        name, _, tail = rest.partition(".")
        if not PROPERTY_RE.match(name):
            return None
        if tail in AGGREGATES:
            return ValueRef(key, "prop", prop=name, agg=tail)
        if tail.startswith("at:"):
            label = _label(tail[3:])
            return (
                ValueRef(f"prop.{name}.at:{label}", "prop_at", prop=name, label=label)
                if label
                else None
            )
    return None


def availability(
    ref: ValueRef, active: Collection[str], properties: Mapping[str, bool], external_objects: bool
) -> str | None:
    """None when the value can have data, else a German reason. `properties`:
    name → archived; `external_objects`: an external source added objects."""
    if ref.kind == "fact":
        assert ref.fact is not None
        found = producers(ref.fact)
        if any(n in active for n in found):
            return None
        title = BY_NAME[found[0]].title if found and found[0] in BY_NAME else ref.fact
        return f"Braucht die Analyse „{title}“."
    if ref.kind in ("labels", "count", "count_label"):
        if "objects" in active or external_objects:
            return None
        return f"Braucht die Analyse „{BY_NAME['objects'].title}“."
    if ref.kind in ("prop", "prop_at"):
        if ref.prop in properties:
            return None
        return f"Braucht die Eigenschaft „{ref.prop}“."
    return None


def properties_of(db: Database) -> dict[str, bool]:
    """LLM property name → archived."""
    return {
        r["name"]: r["archived_at"] is not None
        for r in db.all("SELECT name, archived_at FROM llm_properties ORDER BY name")
    }


def has_external_objects(db: Database) -> bool:
    return db.one("SELECT 1 FROM photo_objects WHERE source != 'local' LIMIT 1") is not None


# ------------------------------------------------------------- catalogue


class ValueInfo(BaseModel):
    key: str
    title: str = Field(description="German.")
    group: str = Field(description="German group heading (the analyzer, „Objekte“, …).")
    kind: ValueKind
    unit: str
    needs: list[str] = Field(
        description="Analyzer names (any of them) or `prop:<name>`; empty = always there."
    )
    available: bool
    reason: str | None
    archived: bool = Field(description="A value of an archived property (scores stay readable).")


class LabelInfo(BaseModel):
    label: str
    label_de: str
    count: int = Field(description="Photos (not deleted) with at least one such object.")


class ValuesOut(BaseModel):
    values: list[ValueInfo]
    labels: list[LabelInfo] = Field(
        description="Object labels seen so far, most frequent first: compose "
        "`objects.count:<label>` and `prop.<name>.at:<label>` with them."
    )


def labels_seen(db: Database) -> list[LabelInfo]:
    rows = db.all(
        "SELECT o.label, MIN(o.label_de) AS label_de, COUNT(DISTINCT o.photo_id) AS n "
        "FROM photo_objects o JOIN photos p ON p.id = o.photo_id WHERE p.deleted_at IS NULL "
        "GROUP BY o.label ORDER BY n DESC, o.label"
    )
    return [LabelInfo(label=r["label"], label_de=r["label_de"], count=int(r["n"])) for r in rows]


def catalogue(db: Database, active: Collection[str]) -> ValuesOut:
    props = properties_of(db)
    external = has_external_objects(db)
    out: list[ValueInfo] = []

    def add(key: str, title: str, group: str, kind: ValueKind, unit: str, needs: list[str],
            archived: bool = False) -> None:  # fmt: skip
        ref = parse(key)
        assert ref is not None, key
        reason = availability(ref, active, props, external)
        out.append(ValueInfo(key=key, title=title, group=group, kind=kind, unit=unit,
                             needs=needs, available=reason is None, reason=reason,
                             archived=archived))  # fmt: skip

    seen: set[str] = set()
    for info in INFOS:
        for fact in info.facts:
            if fact in seen:
                continue
            seen.add(fact)
            title, kind, unit = FACTS.get(fact, (fact, "number", ""))
            add(fact, title, info.title, kind, unit, list(producers(fact)))
    group = BY_NAME["objects"].title
    add("objects", "Erkannte Objekte", group, "labels", "", ["objects"])
    add("objects.count", "Anzahl Objekte", group, "count", "", ["objects"])
    add("photo.created_at", "Aufnahmezeit", "Foto", "time", "", [])
    add("photo.guest_photos", "Fotos dieses Gasts", "Foto", "count", "", [])
    for name, archived in props.items():
        for agg in AGGREGATES:
            add(f"prop.{name}.{agg}", f"{name}: {AGG_TITLES[agg]}", f"Eigenschaft „{name}“",
                "count" if agg == "count" else "number", "" if agg == "count" else "0–1",
                [f"prop:{name}"], archived)  # fmt: skip
    return ValuesOut(values=out, labels=labels_seen(db))
