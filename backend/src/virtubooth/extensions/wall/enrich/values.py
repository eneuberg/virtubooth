"""The building blocks of a category (categories v2) for the editor: the photo
values, the object fields, the aggregates (German titles) and the object labels
seen so far, each with its availability (`GET /admin/values`).

Photo values are the analyzers' facts (`wall_facts`) plus `photo.created_at`
(unix seconds) and `photo.guest_photos` (the guest's visible photos). Object
fields are `confidence` and `prop:<name>` (every property not in the
Papierkorb). The aggregates are measures.AGGREGATES.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Literal

from pydantic import BaseModel, Field

from ....db.database import Database
from .analyzers import BY_NAME, INFOS
from .measures import Measure

ValueKind = Literal["number", "count", "labels", "time"]

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
PHOTO_VALUES: dict[str, tuple[str, ValueKind]] = {
    "photo.created_at": ("Aufnahmezeit", "time"),
    "photo.guest_photos": ("Fotos dieses Gasts", "count"),
}
FACT_TITLES: dict[str, str] = {k: v[0] for k, v in FACTS.items()} | {
    k: v[0] for k, v in PHOTO_VALUES.items()
}
# aggregate → (German title, needs a field, its parameter, focus object)
AGG_INFO: dict[str, tuple[str, bool, str | None, str | None]] = {
    "count": ("Anzahl", False, None, "surest"),  # with a field: the best-rated (max)
    "max": ("höchster Wert", True, None, "max"),
    "min": ("niedrigster Wert", True, None, "min"),
    "mean": ("Durchschnitt", True, None, "max"),
    "sum": ("Summe", True, None, "max"),
    "top_k_mean": ("Mittel der besten k", True, "k", "max"),
    "count_ge": ("Anzahl mit Wert ≥ t", True, "t", "max"),
}


def producers(fact: str) -> tuple[str, ...]:
    """The analyzers that write `fact` (`people`: the detector, else faces)."""
    if fact == "people":
        return ("objects", "faces")
    return tuple(i.name for i in INFOS if fact in i.facts)


ALL_FACTS = frozenset(f for i in INFOS for f in i.facts)


def _fact_reason(fact: str, active: Collection[str]) -> str | None:
    found = producers(fact)
    if any(n in active for n in found):
        return None
    title = BY_NAME[found[0]].title if found and found[0] in BY_NAME else fact
    return f"Braucht die Analyse „{title}“."


def objects_reason(active: Collection[str], external_objects: bool) -> str | None:
    if "objects" in active or external_objects:
        return None
    return f"Braucht die Analyse „{BY_NAME['objects'].title}“."


def availability(
    m: Measure, active: Collection[str], properties: Mapping[str, bool], external_objects: bool
) -> str | None:
    """None when the measure can have data, else a German reason. `properties`:
    name → in the Papierkorb (any property with a row counts: its scores stay
    readable); `external_objects`: an external source added objects."""
    if m.kind == "value":
        assert m.key is not None
        return None if m.key in PHOTO_VALUES else _fact_reason(m.key, active)
    reason = objects_reason(active, external_objects)
    if reason:
        return reason
    if m.prop is not None and m.prop not in properties:
        return f"Braucht die Eigenschaft „{m.prop}“."
    return None


def properties_of(db: Database) -> dict[str, bool]:
    """LLM property name → in the Papierkorb. Every property with a row counts:
    its scores stay readable."""
    return {
        r["name"]: r["deleted_at"] is not None
        for r in db.all("SELECT name, deleted_at FROM llm_properties ORDER BY name")
    }


def has_external_objects(db: Database) -> bool:
    return db.one("SELECT 1 FROM photo_source_objects WHERE source != 'local' LIMIT 1") is not None


# ------------------------------------------------------------- catalogue


class PhotoValueInfo(BaseModel):
    key: str = Field(description="`{kind: value, key}`: an analyzer's fact or `photo.*`.")
    title: str = Field(description="German.")
    group: str = Field(description="German group heading (the analyzer, „Foto“).")
    kind: Literal["number", "count", "time"]
    unit: str
    needs: list[str] = Field(description="Analyzer names (any of them); empty = always there.")
    available: bool
    reason: str | None


class ObjectFieldInfo(BaseModel):
    field: str = Field(description="`confidence` or `prop:<name>`.")
    title: str = Field(description="German.")
    property: str | None = Field(description="The property's name for `prop:<name>`.")
    unit: str = Field(description="„0–1“: both are scores.")


class AggregateInfo(BaseModel):
    agg: Literal["count", "max", "min", "mean", "sum", "top_k_mean", "count_ge"]
    title: str = Field(description="German.")
    needs_field: bool = Field(description="False: `count` also works without a field.")
    param: Literal["k", "t"] | None = Field(
        description="`k` (top_k_mean, 2–5) or `t` (count_ge, 0–1)."
    )
    focus: Literal["max", "min", "surest"] | None = Field(
        description="Which object a winner points at: the highest / lowest value, the "
        "surest one (count with a label filter)."
    )


class LabelInfo(BaseModel):
    label: str
    label_de: str
    count: int = Field(description="Photos (not deleted) with at least one such object.")


class ValuesOut(BaseModel):
    photo_values: list[PhotoValueInfo]
    object_fields: list[ObjectFieldInfo] = Field(
        description="What `objects.agg(field)` can read: `confidence` and every property "
        "not in the Papierkorb."
    )
    aggregates: list[AggregateInfo]
    objects_available: bool = Field(description="Object measures can have data.")
    objects_reason: str | None
    labels: list[LabelInfo] = Field(
        description="Object labels seen so far, most frequent first (for object filters)."
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
    names = [n for n, trashed in props.items() if not trashed]
    obj_reason = objects_reason(active, has_external_objects(db))
    photo_values: list[PhotoValueInfo] = []
    seen: set[str] = set()
    for info in INFOS:
        for fact in info.facts:
            if fact in seen:
                continue
            seen.add(fact)
            title, kind, unit = FACTS.get(fact, (fact, "number", ""))
            reason = _fact_reason(fact, active)
            photo_values.append(PhotoValueInfo(
                key=fact, title=title, group=info.title, kind="number" if kind == "labels"
                else kind, unit=unit, needs=list(producers(fact)), available=reason is None,
                reason=reason))  # fmt: skip
    for key, (title, kind) in PHOTO_VALUES.items():
        photo_values.append(PhotoValueInfo(key=key, title=title, group="Foto", kind=kind,  # type: ignore[arg-type]
                                           unit="", needs=[], available=True, reason=None))  # fmt: skip
    fields = [ObjectFieldInfo(field="confidence", title="Erkennungssicherheit", property=None,
                              unit="0–1")]  # fmt: skip
    fields += [ObjectFieldInfo(field=f"prop:{n}", title=n, property=n, unit="0–1") for n in names]
    aggregates = [
        AggregateInfo(agg=a, title=t, needs_field=nf, param=p, focus=f)  # type: ignore[arg-type]
        for a, (t, nf, p, f) in AGG_INFO.items()
    ]
    return ValuesOut(
        photo_values=photo_values, object_fields=fields, aggregates=aggregates,
        objects_available=obj_reason is None, objects_reason=obj_reason,
        labels=labels_seen(db),
    )  # fmt: skip
