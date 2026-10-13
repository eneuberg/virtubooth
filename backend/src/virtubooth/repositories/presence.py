"""Last-seen times for the dashboard: the `visitors` table (one row per browser
that opened a valid QR link) and `users.last_seen_at`.

Only random ids and timestamps are written here. The callers throttle
(services/presence.py); these are single small statements.
"""

from __future__ import annotations

from ..db.database import Database


class PresenceRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def visit(self, visitor_id: str, *, at: str, user_id: int | None = None) -> None:
        """Record a visitor (first time: insert), and link it to the guest it
        became. A link is never removed by a later anonymous visit."""
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO visitors (id, first_seen_at, last_seen_at, user_id) VALUES (?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET last_seen_at=excluded.last_seen_at, "
                "user_id=COALESCE(excluded.user_id, visitors.user_id)",
                (visitor_id, at, at, user_id),
            )

    def touch_visitor(self, visitor_id: str, *, at: str) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE visitors SET last_seen_at=? WHERE id=?", (at, visitor_id))

    def touch_user(self, public_id: str, *, at: str) -> None:
        with self.db.tx() as c:
            c.execute(
                "UPDATE users SET last_seen_at=? WHERE public_id=? AND last_seen_at<?",
                (at, public_id, at),
            )

    def visitor_user(self, visitor_id: str) -> int | None:
        """The guest a visitor became (tests, diagnostics)."""
        row = self.db.one("SELECT user_id FROM visitors WHERE id=?", (visitor_id,))
        return int(row[0]) if row and row[0] is not None else None
