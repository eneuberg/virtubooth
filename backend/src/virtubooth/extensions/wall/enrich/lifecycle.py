"""Which categories may be on, and which properties are polled (categories v2).

    KI bereit  = master switch on ∧ „Eigenschaften abfragen“ on ∧ a usable key
    lock(K)    = the first of: a property K reads is missing, is in the
                 Papierkorb, the AI is not ready — only for categories with a
                 `prop:` measure
    polled(P)  ⇔ P not in the Papierkorb ∧ KI bereit ∧ an enabled category reads P

Every event (property trashed, AI switched off, key deleted, migration) runs
`reconcile()`: each enabled category with a lock is switched off with the lock
as its reason (`off_reason`, `off_detail`: the property). Nothing switches back
on by itself: once the lock is gone the host switches it on again (the editor
shows the reason and a banner). A category that only has an AI verdict stays on
while the AI is off; its comments are hidden meanwhile.

Reasons: `ai_off`, `property_trashed`, `property_missing`, `migrated_inactive`
(migration 18: it used a property that was switched off then).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ....db.database import Database
from . import engine

OffReason = Literal["ai_off", "property_trashed", "property_missing", "migrated_inactive"]
LockReason = Literal["ai_off", "property_trashed", "property_missing"]

REASON_TEXT: dict[str, str] = {
    "ai_off": "Externe KI ist aus (Hauptschalter, „Eigenschaften abfragen“ oder Schlüssel).",
    "property_trashed": "Die Eigenschaft „{detail}“ liegt im Papierkorb.",
    "property_missing": "Die Eigenschaft „{detail}“ gibt es nicht.",
    "migrated_inactive": "Die Eigenschaft „{detail}“ war bei der Umstellung inaktiv.",
}


def reason_text(reason: str, detail: str | None) -> str:
    return REASON_TEXT.get(reason, reason).format(detail=detail or "?")


@dataclass(frozen=True)
class Lock:
    reason: LockReason
    detail: str | None  # the property's name

    @property
    def text(self) -> str:
        return reason_text(self.reason, self.detail)


def references(spec: Mapping[str, Any]) -> list[str]:
    """The properties a (validated) spec reads."""
    return engine.references(spec)


def property_states(db: Database) -> dict[str, bool]:
    """Property name → in the Papierkorb."""
    return {
        r["name"]: r["deleted_at"] is not None
        for r in db.all("SELECT name, deleted_at FROM llm_properties")
    }


def lock_of(spec: Mapping[str, Any], props: Mapping[str, bool], ai_ready: bool) -> Lock | None:
    """Why the category cannot be switched on, or None. A missing property the
    presets know (presets.PRESET_PROPERTIES) is no lock: switching on creates it."""
    from .presets import PRESET_PROPERTIES

    names = references(spec)
    if not names:
        return None
    for name in names:
        if name not in props and name not in PRESET_PROPERTIES:
            return Lock("property_missing", name)
    for name in names:
        if props.get(name):
            return Lock("property_trashed", name)
    if not ai_ready:
        return Lock("ai_off", None)
    return None


def locks(db: Database, ai_ready: bool) -> dict[str, Lock]:
    """Category id → its lock (every category, on or off)."""
    props = property_states(db)
    out: dict[str, Lock] = {}
    for cat in engine.stored(db):
        lock = lock_of(cat.spec, props, ai_ready)
        if lock is not None:
            out[cat.id] = lock
    return out


def reconcile(db: Database, ai_ready: bool) -> list[tuple[str, str, str | None]]:
    """Switch off every enabled category that has a lock (idempotent; in one
    transaction). Returns (id, reason, detail) of those switched off now."""
    switched: list[tuple[str, str, str | None]] = []
    with db.tx():
        props = property_states(db)
        for cat in engine.stored(db):
            if not cat.enabled:
                continue
            lock = lock_of(cat.spec, props, ai_ready)
            if lock is None:
                continue
            engine.switch_off(db, cat.id, lock.reason, lock.detail)
            switched.append((cat.id, lock.reason, lock.detail))
    return switched


def users_of(db: Database, name: str) -> list[engine.StoredCategory]:
    """The categories that read the property (on or off), in position order. A
    v1 row that does not validate any more counts when its JSON names it."""
    from . import spec_v1

    out = [c for c in engine.stored(db) if name in references(c.spec)]
    known = {c.id for c in out} | {c.id for c in engine.stored(db)}
    for r in db.all("SELECT id, position, enabled, preset, spec, updated_at FROM wall_categories "
                    "ORDER BY position, id"):  # fmt: skip
        if r["id"] in known:
            continue
        if name in spec_v1.referenced_properties(r["spec"]):
            out.append(engine.StoredCategory(r["id"], int(r["position"]), bool(r["enabled"]),
                                             r["preset"], {"title": r["id"]}, r["updated_at"]))  # fmt: skip
    return out


def polled_names(db: Database, ai_ready: bool = True) -> list[str]:
    """The properties the poll asks about: not in the Papierkorb, the AI ready,
    read by an enabled category."""
    if not ai_ready:
        return []
    props = property_states(db)
    wanted: list[str] = []
    for cat in engine.stored(db):
        if cat.enabled:
            wanted += [n for n in references(cat.spec) if n not in wanted]
    return [n for n in wanted if n in props and not props[n]]


def used_by(db: Database) -> dict[str, list[tuple[str, str, bool]]]:
    """Property name → (category id, title, enabled) of the categories reading it."""
    out: dict[str, list[tuple[str, str, bool]]] = {}
    for cat in engine.stored(db):
        for name in references(cat.spec):
            out.setdefault(name, []).append((cat.id, str(cat.spec["title"]), cat.enabled))
    return out
