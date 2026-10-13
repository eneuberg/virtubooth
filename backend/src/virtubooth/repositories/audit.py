"""The audit log. Services write the entry in the same transaction as the
change it records.

Vocabulary: actor `anonymous` or `admin:<first 8 hex of the session hash>`;
target `user:<id>`, `photo:<public id>`, `fp:<first 16 hex>`, `ip:<ip>` or "".
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..db.database import Database
from ..domain.models import AuditEntry

MAX_PAGE = 500


def _entry(row: sqlite3.Row) -> AuditEntry:
    return AuditEntry(
        id=row["id"],
        at=row["at"],
        actor=row["actor"],
        action=row["action"],
        target=row["target"],
        details=json.loads(row["details"] or "{}"),
    )


class AuditRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def log(
        self,
        actor: str,
        action: str,
        target: str = "",
        details: dict[str, Any] | None = None,
        *,
        at: str,
    ) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO audit_log (at, actor, action, target, details) VALUES (?,?,?,?,?)",
                (at, actor, action, target, json.dumps(details or {})),
            )

    def list(self, limit: int = 100) -> list[AuditEntry]:
        rows = self.db.all("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(limit, 1000),))
        return [_entry(r) for r in rows]

    def page(self, *, before: int | None = None, limit: int = 100) -> list[AuditEntry]:
        """Newest first; `before` is the id of the last entry already shown."""
        sql = "SELECT * FROM audit_log"
        params: list[Any] = []
        if before is not None:
            sql += " WHERE id<?"
            params.append(before)
        sql += " ORDER BY id DESC LIMIT ?"
        # one more than the cap is allowed: callers ask for limit+1 to see if more follow
        params.append(max(1, min(limit, MAX_PAGE + 1)))
        return [_entry(r) for r in self.db.all(sql, params)]
