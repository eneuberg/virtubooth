"""Properties („Eigenschaften“, PLAN-NIGHT N7): a name and a prompt the poll
rates every object with. Name and prompt never change (DB trigger).

There is no switch (categories v2, migration 18): a property is polled while it
is not in the Papierkorb, the external AI is ready and an enabled category reads
it (`polled`, enrich/lifecycle.py); its status is derived from that.
`deleted_at` (the „Papierkorb“): not polled, hidden from the list and from the
category editor, scores kept; trashing it switches the enabled categories that
read it off (`property_trashed`); „Wiederherstellen“ brings it back (those
categories stay off until the host switches them on). Only a property in the
trash can be deleted for good (`purge`): the row and its scores go, but never
while a category still reads it.

A name stays taken (also in the trash) until the property is deleted for good."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ....core import errors
from ....core.clock import now_iso
from ....db.database import Database
from ....repositories.audit import AuditRepo

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
PROMPT_MAX = 2000


@dataclass(frozen=True)
class Property:
    id: int
    name: str
    prompt: str
    created_at: str
    deleted_at: str | None
    scored_photos: int
    last_scored_at: str | None


_SELECT = (
    "SELECT lp.*, (SELECT COUNT(*) FROM property_scores s WHERE s.property_id = lp.id) AS n, "
    "(SELECT MAX(updated_at) FROM property_scores s WHERE s.property_id = lp.id) AS last "
    "FROM llm_properties lp"
)


def _row(r: Any) -> Property:
    return Property(
        id=r["id"],
        name=r["name"],
        prompt=r["prompt"],
        created_at=r["created_at"],
        deleted_at=r["deleted_at"],
        scored_photos=r["n"],
        last_scored_at=r["last"],
    )


def list_all(db: Database) -> list[Property]:
    """Everything, the trash included: the others first, then the trash; each
    group oldest first."""
    return [_row(r) for r in db.all(f"{_SELECT} ORDER BY lp.deleted_at IS NOT NULL, lp.id")]


def polled(db: Database, ai_ready: bool = True) -> list[Property]:
    """The ones the poll asks about: not in the trash, the AI ready (the poller
    checks that itself), read by an enabled category; oldest first."""
    from ..enrich import lifecycle

    names = set(lifecycle.polled_names(db, ai_ready))
    return [p for p in list_all(db) if p.name in names]


def get(db: Database, name: str) -> Property | None:
    r = db.one(f"{_SELECT} WHERE lp.name = ?", (name,))
    return _row(r) if r else None


def invalid(message: str) -> errors.ApiError:
    return errors.bad_request(message, "invalid_property")


def create(db: Database, audit: AuditRepo, name: str, prompt: str, *, actor: str) -> Property:
    name = name.strip()
    prompt = prompt.strip()
    if not NAME_RE.match(name):
        raise invalid(
            "Der Name braucht 2 bis 31 Zeichen: Kleinbuchstaben, Ziffern und _, "
            "am Anfang ein Buchstabe (z. B. coolness)."
        )
    if not prompt or len(prompt) > PROMPT_MAX:
        raise invalid(f"Der Prompt braucht 1 bis {PROMPT_MAX} Zeichen.")
    at = now_iso()
    with db.tx() as c:
        row = c.execute("SELECT deleted_at FROM llm_properties WHERE name=?", (name,)).fetchone()
        if row is not None:
            raise errors.ApiError(
                409,
                "property_exists",
                "Diese Eigenschaft liegt im Papierkorb: dort wiederherstellen oder endgültig "
                "löschen, dann ist der Name wieder frei."
                if row["deleted_at"] is not None
                else "Diese Eigenschaft gibt es schon.",
            )
        c.execute(
            "INSERT INTO llm_properties (name, prompt, created_at, created_by) VALUES (?,?,?,?)",
            (name, prompt, at, actor),
        )
        audit.log(actor, "llm.property.create", f"property:{name}", {"name": name}, at=at)
    found = get(db, name)
    assert found is not None
    return found


def _toggle(
    db: Database, audit: AuditRepo, name: str, column: str, on: bool, actions: tuple[str, str],
    *, actor: str,
) -> Property | None:  # fmt: skip
    """Set `column` to now (on) or NULL (off). None: no such property. Setting
    the state it already has changes nothing (no audit entry)."""
    at = now_iso()
    with db.tx() as c:
        row = c.execute(f"SELECT {column} FROM llm_properties WHERE name=?", (name,)).fetchone()
        if row is None:
            return None
        if (row[column] is not None) != on:
            c.execute(
                f"UPDATE llm_properties SET {column}=? WHERE name=?", (at if on else None, name)
            )
            audit.log(actor, actions[0 if on else 1], f"property:{name}", {"name": name}, at=at)
    return get(db, name)


def set_trashed(
    db: Database, audit: AuditRepo, name: str, trashed: bool, *, actor: str
) -> Property | None:
    """„Löschen“ (into the Papierkorb) and „Wiederherstellen“ (back as it was).
    Trashing switches the enabled categories that read it off
    (`property_trashed`, same transaction). None: no such property."""
    from ..enrich import lifecycle

    with db.tx():
        found = _toggle(db, audit, name, "deleted_at", trashed,
                        ("llm.property.trash", "llm.property.restore"), actor=actor)  # fmt: skip
        if found is not None and trashed:
            lifecycle.reconcile(db, ai_ready=True)
    return found


def using_categories(db: Database, name: str) -> list[tuple[str, str]]:
    """(id, title) of the categories whose spec reads the property anywhere
    (pool, ranking, caption), enabled or not."""
    from ..enrich import lifecycle

    out: list[tuple[str, str]] = []
    for cat in lifecycle.users_of(db, name):
        title = cat.spec.get("title")
        out.append((cat.id, title if isinstance(title, str) and title else cat.id))
    return out


def purge(db: Database, audit: AuditRepo, name: str, *, actor: str) -> bool:
    """„Endgültig löschen“: the property and its scores go for good, and the
    name is free again. False: no such property. 409 `property_not_in_trash`
    (only from the Papierkorb), 409 `property_in_use` (a category still uses
    it: the message names them; change their conditions first)."""
    at = now_iso()
    with db.tx() as c:
        row = c.execute(
            "SELECT id, deleted_at FROM llm_properties WHERE name=?", (name,)
        ).fetchone()
        if row is None:
            return False
        if row["deleted_at"] is None:
            raise errors.ApiError(
                409,
                "property_not_in_trash",
                "Nur Eigenschaften im Papierkorb lassen sich endgültig löschen.",
            )
        users = using_categories(db, name)
        if users:
            titles = ", ".join(f"„{title}“" for _, title in users)
            raise errors.ApiError(
                409,
                "property_in_use",
                f"Die Eigenschaft „{name}“ wird noch in {'der Kategorie' if len(users) == 1 else 'den Kategorien'} "
                f"{titles} verwendet: dort zuerst die Bedingungen ändern oder die Kategorie löschen.",
            )
        scores = c.execute("DELETE FROM property_scores WHERE property_id=?", (row["id"],)).rowcount
        c.execute("DELETE FROM llm_properties WHERE id=?", (row["id"],))
        audit.log(actor, "llm.property.delete", f"property:{name}",
                  {"name": name, "scores": scores}, at=at)  # fmt: skip
    return True
