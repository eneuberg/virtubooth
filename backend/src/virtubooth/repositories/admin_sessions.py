"""Admin sessions: only the SHA-256 of the cookie token is stored."""

from __future__ import annotations

from ..db.database import Database
from ..domain.models import AdminSession


class AdminSessionsRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        token_hash: str,
        *,
        now: str,
        expires_at: str,
        pw_tag: str,
        ip: str,
        user_agent: str,
    ) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM admin_sessions WHERE expires_at<?", (now,))
            c.execute(
                "INSERT INTO admin_sessions VALUES (?,?,?,?,?,?)",
                (token_hash, now, expires_at, pw_tag, ip, user_agent[:300]),
            )

    def get(self, token_hash: str, *, now: str) -> AdminSession | None:
        row = self.db.one(
            "SELECT * FROM admin_sessions WHERE token_hash=? AND expires_at>?", (token_hash, now)
        )
        return AdminSession(**dict(row)) if row else None

    def delete(self, token_hash: str) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM admin_sessions WHERE token_hash=?", (token_hash,))
