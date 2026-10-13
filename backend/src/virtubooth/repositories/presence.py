"""Last-seen times for the dashboard: the `visitors` table (one row per browser
that opened a valid QR link) and `users.last_seen_at`; the online time of
joined guests (`users.online_*`, see `beat()`).

Only random ids and timestamps are written here. The callers throttle
(services/presence.py); these are single small statements.
"""

from __future__ import annotations

from datetime import datetime

from ..core.clock import iso
from ..db.database import Database
from ..domain import overview


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

    def beat(self, public_id: str, *, visible: bool, now: datetime) -> bool:
        """One heartbeat of a joined guest's page: the online-time accounting
        of `domain.overview.beat()` and the last-seen time, read and written in
        one transaction (one small UPDATE). False: no such guest."""
        at = iso(now)
        with self.db.tx() as c:
            row = c.execute("SELECT id, online_at FROM users WHERE public_id=?", (public_id,))
            found = row.fetchone()
            if found is None:
                return False
            step = overview.beat(found["online_at"], now, visible=visible)
            c.execute(
                "UPDATE users SET online_seconds=online_seconds+?, "
                "online_sessions=online_sessions+?, online_at=?, "
                "last_seen_at=MAX(last_seen_at, ?) WHERE id=?",
                (step.add_seconds, int(step.new_visit), at if visible else None, at, found["id"]),
            )
        return True
