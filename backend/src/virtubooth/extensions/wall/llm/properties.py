"""Properties („Eigenschaften“, PLAN-NIGHT N7): a name and a prompt the poll
rates every object with. Name and prompt never change (DB trigger), a
property is never deleted, only archived (no more polling; its last scores
stay readable) and can be unarchived."""

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
    archived_at: str | None
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
        archived_at=r["archived_at"],
        scored_photos=r["n"],
        last_scored_at=r["last"],
    )


def list_all(db: Database) -> list[Property]:
    """Active ones first, each group oldest first."""
    return [_row(r) for r in db.all(f"{_SELECT} ORDER BY lp.archived_at IS NOT NULL, lp.id")]


def active(db: Database) -> list[Property]:
    return [_row(r) for r in db.all(f"{_SELECT} WHERE lp.archived_at IS NULL ORDER BY lp.id")]


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
        if c.execute("SELECT 1 FROM llm_properties WHERE name=?", (name,)).fetchone():
            raise errors.ApiError(
                409, "property_exists", "Diese Eigenschaft gibt es schon (auch archiviert)."
            )
        c.execute(
            "INSERT INTO llm_properties (name, prompt, created_at, created_by) VALUES (?,?,?,?)",
            (name, prompt, at, actor),
        )
        audit.log(actor, "llm.property.create", f"property:{name}", {"name": name}, at=at)
    found = get(db, name)
    assert found is not None
    return found


def set_archived(
    db: Database, audit: AuditRepo, name: str, archived: bool, *, actor: str
) -> Property | None:
    """None: no such property. Archiving an archived one changes nothing."""
    at = now_iso()
    with db.tx() as c:
        row = c.execute("SELECT archived_at FROM llm_properties WHERE name=?", (name,)).fetchone()
        if row is None:
            return None
        if (row["archived_at"] is not None) != archived:
            c.execute(
                "UPDATE llm_properties SET archived_at=? WHERE name=?",
                (at if archived else None, name),
            )
            action = "llm.property.archive" if archived else "llm.property.unarchive"
            audit.log(actor, action, f"property:{name}", {"name": name}, at=at)
    return get(db, name)
