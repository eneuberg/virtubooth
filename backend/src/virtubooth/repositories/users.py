"""Users (guest identities), the fingerprints they showed, and their upload pauses.

Repositories only read and write rows. Audit entries, events and the
transaction that makes several writes one change belong to the services.
"""

from __future__ import annotations

import json
from typing import Any

from ..db.database import Database
from ..domain.constants import PAUSE_ADMIN, PAUSE_NEW_GUEST_LOCK
from ..domain.models import User, UserFingerprint
from ..domain.names import pseudonym
from ._rows import USER_COLS, as_int, user_from_row

_PHOTO_COUNT = (
    "(SELECT COUNT(*) FROM photos p WHERE p.user_id=u.id AND p.deleted_at IS NULL) AS photo_count"
)
MAX_PAGE = 500


class UsersRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        *,
        public_id: str,
        at: str,
        consent_version: str,
        instagram: str | None,
        fp_hash: str | None,
        fp_components: dict[str, Any],
        ip: str,
        user_agent: str,
        banned_reason: str | None = None,
        lock_period: int | None = None,
    ) -> int:
        """Insert a guest (named by its id) and its first fingerprint. A
        `lock_period` starts it with uploads paused by that new-guest lock."""
        with self.db.tx() as c:
            cur = c.execute(
                "INSERT INTO users (public_id, created_at, last_seen_at, consent_at, "
                "consent_version, instagram, fp_hash, fp_components, first_ip, last_ip, "
                "user_agent, banned_at, ban_reason, uploads_paused_at, uploads_paused_source, "
                "uploads_lock_period) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    public_id, at, at, at, consent_version, instagram, fp_hash,
                    json.dumps(fp_components), ip, ip, user_agent,
                    at if banned_reason else None, banned_reason,
                    at if lock_period else None,
                    PAUSE_NEW_GUEST_LOCK if lock_period else None,
                    lock_period,
                ),
            )  # fmt: skip
            uid = cur.lastrowid
            assert uid is not None
            c.execute("UPDATE users SET name=? WHERE id=?", (pseudonym(uid), uid))
            if fp_hash:
                c.execute(
                    "INSERT OR IGNORE INTO user_fingerprints VALUES (?,?,?,?)",
                    (uid, fp_hash, at, at),
                )
        return uid

    def get(self, user_id: int) -> User | None:
        row = self.db.one(f"SELECT {USER_COLS}, {_PHOTO_COUNT} FROM users u WHERE u.id=?", (user_id,))
        return user_from_row(row, row["photo_count"]) if row else None

    def get_by_public_id(self, public_id: str) -> User | None:
        row = self.db.one(f"SELECT {USER_COLS} FROM users u WHERE u.public_id=?", (public_id,))
        return user_from_row(row) if row else None

    def touch(
        self,
        user_id: int,
        *,
        at: str,
        ip: str,
        user_agent: str,
        fp_hash: str | None = None,
        fp_components: dict[str, Any] | None = None,
    ) -> None:
        with self.db.tx() as c:
            c.execute(
                "UPDATE users SET last_seen_at=?, last_ip=?, user_agent=? WHERE id=?",
                (at, ip, user_agent, user_id),
            )
            if fp_hash:
                c.execute(
                    "UPDATE users SET fp_hash=?, fp_components=? WHERE id=?",
                    (fp_hash, json.dumps(fp_components or {}), user_id),
                )
                c.execute(
                    "INSERT INTO user_fingerprints VALUES (?,?,?,?) "
                    "ON CONFLICT(user_id, fp_hash) DO UPDATE SET last_seen=excluded.last_seen",
                    (user_id, fp_hash, at, at),
                )

    def set_instagram(self, user_id: int, handle: str | None) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE users SET instagram=? WHERE id=?", (handle, user_id))

    def list(
        self,
        *,
        banned: bool | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
        paused: bool | None = None,
    ) -> list[User]:
        where: list[str] = []
        params: list[Any] = []
        if banned is not None:
            where.append("u.banned_at IS NOT NULL" if banned else "u.banned_at IS NULL")
        if paused is not None:
            where.append(
                "u.uploads_paused_at IS NOT NULL" if paused else "u.uploads_paused_at IS NULL"
            )
        if search:
            where.append("(u.name LIKE ? OR u.instagram LIKE ? OR CAST(u.id AS TEXT) = ?)")
            like = f"%{search}%"
            params += [like, like, search.lstrip("#")]
        sql = f"SELECT {USER_COLS}, {_PHOTO_COUNT} FROM users u"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY u.id DESC LIMIT ? OFFSET ?"
        # one more than the cap is allowed: callers ask for limit+1 to see if more follow
        rows = self.db.all(sql, [*params, min(limit, MAX_PAGE + 1), offset])
        return [user_from_row(r, r["photo_count"]) for r in rows]

    def fingerprints(self, user_id: int) -> list[UserFingerprint]:
        rows = self.db.all(
            "SELECT f.fp_hash, f.first_seen, f.last_seen, "
            "(SELECT COUNT(DISTINCT o.user_id) FROM user_fingerprints o "
            " WHERE o.fp_hash=f.fp_hash AND o.user_id<>f.user_id) AS shared_with, "
            "EXISTS(SELECT 1 FROM fingerprint_bans b WHERE b.fp_hash=f.fp_hash) AS banned "
            "FROM user_fingerprints f WHERE f.user_id=? ORDER BY f.last_seen DESC",
            (user_id,),
        )
        return [
            UserFingerprint(
                fp_hash=r["fp_hash"],
                first_seen=r["first_seen"],
                last_seen=r["last_seen"],
                shared_with=as_int(r["shared_with"]),
                banned=bool(r["banned"]),
            )
            for r in rows
        ]

    def sharing_fingerprint(self, user_id: int) -> list[User]:
        """Other users that showed any fingerprint this user showed.

        A shared fingerprint is a hint, not proof: identical phone models with
        the same OS version often produce the same fingerprint.
        """
        rows = self.db.all(
            f"SELECT DISTINCT {USER_COLS} FROM users u JOIN user_fingerprints o "
            "ON o.user_id=u.id WHERE o.fp_hash IN "
            "(SELECT fp_hash FROM user_fingerprints WHERE user_id=?) AND u.id<>? "
            "ORDER BY u.id",
            (user_id, user_id),
        )
        return [user_from_row(r) for r in rows]

    # ----------------------------------------------------------------- bans

    def ban(self, user_id: int, *, at: str, reason: str) -> bool:
        with self.db.tx() as c:
            cur = c.execute(
                "UPDATE users SET banned_at=?, ban_reason=? WHERE id=? AND banned_at IS NULL",
                (at, reason, user_id),
            )
        return cur.rowcount > 0

    def unban(self, user_id: int) -> bool:
        with self.db.tx() as c:
            cur = c.execute(
                "UPDATE users SET banned_at=NULL, ban_reason=NULL "
                "WHERE id=? AND banned_at IS NOT NULL",
                (user_id,),
            )
        return cur.rowcount > 0

    # --------------------------------------------------------------- pauses

    def pause_source(self, user_id: int) -> tuple[bool, str | None] | None:
        """(paused, source) of a user, None if the user doesn't exist."""
        row = self.db.one(
            "SELECT uploads_paused_at IS NOT NULL AS paused, uploads_paused_source "
            "FROM users WHERE id=?",
            (user_id,),
        )
        return (bool(row["paused"]), row["uploads_paused_source"]) if row else None

    def pause(self, user_id: int, *, at: str) -> None:
        """Paused by an admin: source 'admin', no lock period."""
        with self.db.tx() as c:
            c.execute(
                "UPDATE users SET uploads_paused_at=?, uploads_paused_source=?, "
                "uploads_lock_period=NULL WHERE id=?",
                (at, PAUSE_ADMIN, user_id),
            )

    def unpause(self, user_id: int) -> None:
        with self.db.tx() as c:
            c.execute(
                "UPDATE users SET uploads_paused_at=NULL, uploads_paused_source=NULL, "
                "uploads_lock_period=NULL WHERE id=?",
                (user_id,),
            )

    def count_paused(self, *, lock_period: int | None = None) -> int:
        """Guests with paused uploads; with lock_period: only those that lock
        period paused (and nobody changed since)."""
        sql = "SELECT COUNT(*) FROM users WHERE uploads_paused_at IS NOT NULL"
        params: list[Any] = []
        if lock_period is not None:
            sql += " AND uploads_paused_source=? AND uploads_lock_period=?"
            params += [PAUSE_NEW_GUEST_LOCK, lock_period]
        row = self.db.one(sql, params)
        return as_int(row[0]) if row else 0

    def paused_by_lock(self, period: int) -> list[int]:
        rows = self.db.all(
            "SELECT id FROM users WHERE uploads_paused_at IS NOT NULL "
            "AND uploads_paused_source=? AND uploads_lock_period=? ORDER BY id",
            (PAUSE_NEW_GUEST_LOCK, period),
        )
        return [int(r[0]) for r in rows]

    def unpause_lock_period(self, period: int) -> None:
        with self.db.tx() as c:
            c.execute(
                "UPDATE users SET uploads_paused_at=NULL, uploads_paused_source=NULL, "
                "uploads_lock_period=NULL WHERE uploads_paused_at IS NOT NULL "
                "AND uploads_paused_source=? AND uploads_lock_period=?",
                (PAUSE_NEW_GUEST_LOCK, period),
            )
