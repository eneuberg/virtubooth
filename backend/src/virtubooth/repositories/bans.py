"""Fingerprint (device) bans: new identities showing a banned fingerprint start banned."""

from __future__ import annotations

from ..db.database import Database
from ..domain.models import FingerprintBan


class FingerprintBansRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, fp_hash: str, *, at: str, reason: str, source_user_id: int | None = None) -> bool:
        with self.db.tx() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO fingerprint_bans VALUES (?,?,?,?)",
                (fp_hash, at, reason, source_user_id),
            )
        return cur.rowcount > 0

    def remove(self, fp_hash: str) -> bool:
        with self.db.tx() as c:
            cur = c.execute("DELETE FROM fingerprint_bans WHERE fp_hash=?", (fp_hash,))
        return cur.rowcount > 0

    def is_banned(self, fp_hash: str) -> bool:
        return self.db.one("SELECT 1 FROM fingerprint_bans WHERE fp_hash=?", (fp_hash,)) is not None

    def list(self) -> list[FingerprintBan]:
        rows = self.db.all("SELECT * FROM fingerprint_bans ORDER BY created_at")
        return [
            FingerprintBan(
                fp_hash=r["fp_hash"],
                created_at=r["created_at"],
                reason=r["reason"],
                source_user_id=r["source_user_id"],
            )
            for r in rows
        ]
