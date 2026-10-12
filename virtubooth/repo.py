"""Data access for users, photos, bans, admin sessions and the audit log.

Everything that touches the database or the photo files goes through here, so
extensions and the admin API never write SQL themselves.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .db import Database
from .names import pseudonym


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_public_id() -> str:
    return secrets.token_urlsafe(12)


@dataclass(frozen=True)
class User:
    id: int
    public_id: str
    name: str
    created_at: str
    last_seen_at: str
    consent_at: str
    consent_version: str
    instagram: str | None
    fp_hash: str | None
    fp_components: dict[str, Any]
    first_ip: str
    last_ip: str
    user_agent: str
    banned_at: str | None
    ban_reason: str | None
    photo_count: int = 0

    @property
    def banned(self) -> bool:
        return self.banned_at is not None

    def guest_view(self) -> dict[str, Any]:
        """What the guest's own browser may see about itself."""
        return {"name": self.name, "instagram": self.instagram, "banned": self.banned}

    def admin_view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "instagram": self.instagram,
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
            "consent_at": self.consent_at,
            "consent_version": self.consent_version,
            "fp_hash": self.fp_hash,
            "fp_components": self.fp_components,
            "first_ip": self.first_ip,
            "last_ip": self.last_ip,
            "user_agent": self.user_agent,
            "banned": self.banned,
            "banned_at": self.banned_at,
            "ban_reason": self.ban_reason,
            "photo_count": self.photo_count,
        }


@dataclass(frozen=True)
class Photo:
    id: int
    public_id: str
    extension: str
    user_id: int
    seq: int
    filename: str
    thumb_filename: str
    created_at: str
    width: int
    height: int
    bytes: int
    meta: dict[str, Any]
    hidden_at: str | None
    hidden_reason: str | None
    deleted_at: str | None
    user_name: str = ""
    user_instagram: str | None = None
    user_banned: bool = False

    @property
    def hidden(self) -> bool:
        return self.hidden_at is not None

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None

    def url(self, thumb: bool = False) -> str:
        return f"/media/{self.public_id}" + ("?thumb=1" if thumb else "")

    def admin_view(self) -> dict[str, Any]:
        return {
            "id": self.public_id,
            "extension": self.extension,
            "seq": self.seq,
            "created_at": self.created_at,
            "width": self.width,
            "height": self.height,
            "bytes": self.bytes,
            "meta": self.meta,
            "hidden": self.hidden,
            "hidden_at": self.hidden_at,
            "hidden_reason": self.hidden_reason,
            "deleted": self.deleted,
            "url": self.url(),
            "thumb_url": self.url(thumb=True),
            "user": {
                "id": self.user_id,
                "name": self.user_name,
                "instagram": self.user_instagram,
                "banned": self.user_banned,
            },
        }


@dataclass
class PhotoQuery:
    extension: str | None = None
    user_id: int | None = None
    # None = both, True = only hidden, False = only visible
    hidden: bool | None = None
    include_deleted: bool = False
    # pagination by internal id: newest first, pass the last id you saw
    before_id: int | None = None
    # for live views: everything newer than this id (returned newest first too)
    after_id: int | None = None
    limit: int = 50
    order: str = "desc"  # "desc" (newest first) or "asc" (upload order)


_USER_COLS = (
    "u.id, u.public_id, u.name, u.created_at, u.last_seen_at, u.consent_at, "
    "u.consent_version, u.instagram, u.fp_hash, u.fp_components, u.first_ip, "
    "u.last_ip, u.user_agent, u.banned_at, u.ban_reason"
)
_PHOTO_COLS = (
    "p.id, p.public_id, p.extension, p.user_id, p.seq, p.filename, p.thumb_filename, "
    "p.created_at, p.width, p.height, p.bytes, p.meta, p.hidden_at, p.hidden_reason, "
    "p.deleted_at, u.name AS user_name, u.instagram AS user_instagram, "
    "u.banned_at IS NOT NULL AS user_banned"
)


def _user(row: sqlite3.Row, photo_count: int = 0) -> User:
    d = dict(row)
    d.pop("photo_count", None)
    d["fp_components"] = json.loads(d["fp_components"] or "{}")
    return User(**d, photo_count=photo_count)


def _photo(row: sqlite3.Row) -> Photo:
    d = dict(row)
    d["meta"] = json.loads(d["meta"] or "{}")
    d["user_banned"] = bool(d["user_banned"])
    return Photo(**d)


class Repo:
    def __init__(self, db: Database, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir

    # ---------------------------------------------------------------- users

    def create_user(
        self,
        *,
        consent_version: str,
        instagram: str | None,
        fp_hash: str | None,
        fp_components: dict[str, Any],
        ip: str,
        user_agent: str,
        banned_reason: str | None = None,
    ) -> User:
        ts = now_iso()
        public_id = new_public_id()
        with self.db.tx() as c:
            cur = c.execute(
                "INSERT INTO users (public_id, created_at, last_seen_at, consent_at, "
                "consent_version, instagram, fp_hash, fp_components, first_ip, last_ip, "
                "user_agent, banned_at, ban_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    public_id, ts, ts, ts, consent_version, instagram, fp_hash,
                    json.dumps(fp_components), ip, ip, user_agent,
                    ts if banned_reason else None, banned_reason,
                ),
            )  # fmt: skip
            uid = cur.lastrowid
            assert uid is not None
            c.execute("UPDATE users SET name=? WHERE id=?", (pseudonym(uid), uid))
            if fp_hash:
                c.execute(
                    "INSERT OR IGNORE INTO user_fingerprints VALUES (?,?,?,?)",
                    (uid, fp_hash, ts, ts),
                )
        user = self.get_user(uid)
        assert user is not None
        return user

    def get_user(self, user_id: int) -> User | None:
        row = self.db.one(
            f"SELECT {_USER_COLS}, (SELECT COUNT(*) FROM photos p WHERE p.user_id=u.id "
            "AND p.deleted_at IS NULL) AS photo_count FROM users u WHERE u.id=?",
            (user_id,),
        )
        return _user(row, row["photo_count"]) if row else None

    def get_user_by_public_id(self, public_id: str) -> User | None:
        row = self.db.one(f"SELECT {_USER_COLS} FROM users u WHERE u.public_id=?", (public_id,))
        return _user(row) if row else None

    def touch_user(
        self,
        user_id: int,
        *,
        ip: str,
        user_agent: str,
        fp_hash: str | None = None,
        fp_components: dict[str, Any] | None = None,
    ) -> None:
        ts = now_iso()
        with self.db.tx() as c:
            c.execute(
                "UPDATE users SET last_seen_at=?, last_ip=?, user_agent=? WHERE id=?",
                (ts, ip, user_agent, user_id),
            )
            if fp_hash:
                c.execute(
                    "UPDATE users SET fp_hash=?, fp_components=? WHERE id=?",
                    (fp_hash, json.dumps(fp_components or {}), user_id),
                )
                c.execute(
                    "INSERT INTO user_fingerprints VALUES (?,?,?,?) "
                    "ON CONFLICT(user_id, fp_hash) DO UPDATE SET last_seen=excluded.last_seen",
                    (user_id, fp_hash, ts, ts),
                )

    def set_instagram(self, user_id: int, handle: str | None) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE users SET instagram=? WHERE id=?", (handle, user_id))

    def list_users(
        self,
        *,
        banned: bool | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[User]:
        where, params = [], []
        if banned is not None:
            where.append("u.banned_at IS NOT NULL" if banned else "u.banned_at IS NULL")
        if search:
            where.append("(u.name LIKE ? OR u.instagram LIKE ? OR CAST(u.id AS TEXT) = ?)")
            like = f"%{search}%"
            params += [like, like, search.lstrip("#")]
        sql = (
            f"SELECT {_USER_COLS}, (SELECT COUNT(*) FROM photos p WHERE p.user_id=u.id "
            "AND p.deleted_at IS NULL) AS photo_count FROM users u"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY u.id DESC LIMIT ? OFFSET ?"
        rows = self.db.all(sql, [*params, min(limit, 500), offset])
        return [_user(r, r["photo_count"]) for r in rows]

    def user_fingerprints(self, user_id: int) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT f.fp_hash, f.first_seen, f.last_seen, "
            "(SELECT COUNT(DISTINCT o.user_id) FROM user_fingerprints o "
            " WHERE o.fp_hash=f.fp_hash AND o.user_id<>f.user_id) AS shared_with, "
            "EXISTS(SELECT 1 FROM fingerprint_bans b WHERE b.fp_hash=f.fp_hash) AS banned "
            "FROM user_fingerprints f WHERE f.user_id=? ORDER BY f.last_seen DESC",
            (user_id,),
        )
        return [dict(r) | {"banned": bool(r["banned"])} for r in rows]

    def users_sharing_fingerprint(self, user_id: int) -> list[User]:
        """Other users that showed any fingerprint this user showed.

        A shared fingerprint is a hint, not proof: identical phone models with
        the same OS version often produce the same fingerprint.
        """
        rows = self.db.all(
            f"SELECT DISTINCT {_USER_COLS} FROM users u JOIN user_fingerprints o "
            "ON o.user_id=u.id WHERE o.fp_hash IN "
            "(SELECT fp_hash FROM user_fingerprints WHERE user_id=?) AND u.id<>? "
            "ORDER BY u.id",
            (user_id, user_id),
        )
        return [_user(r) for r in rows]

    def ban_user(self, user_id: int, reason: str, actor: str) -> bool:
        ts = now_iso()
        with self.db.tx() as c:
            cur = c.execute(
                "UPDATE users SET banned_at=?, ban_reason=? WHERE id=? AND banned_at IS NULL",
                (ts, reason, user_id),
            )
            if cur.rowcount == 0:
                return False
            c.execute(
                "UPDATE photos SET hidden_at=?, hidden_reason='ban' "
                "WHERE user_id=? AND hidden_at IS NULL AND deleted_at IS NULL",
                (ts, user_id),
            )
        self.audit(actor, "user.ban", f"user:{user_id}", {"reason": reason})
        return True

    def unban_user(self, user_id: int, actor: str) -> bool:
        with self.db.tx() as c:
            cur = c.execute(
                "UPDATE users SET banned_at=NULL, ban_reason=NULL "
                "WHERE id=? AND banned_at IS NOT NULL",
                (user_id,),
            )
            if cur.rowcount == 0:
                return False
            # only photos the ban hid come back; ones an admin hid stay hidden
            c.execute(
                "UPDATE photos SET hidden_at=NULL, hidden_reason=NULL "
                "WHERE user_id=? AND hidden_reason='ban'",
                (user_id,),
            )
        self.audit(actor, "user.unban", f"user:{user_id}")
        return True

    def ban_fingerprint(
        self, fp_hash: str, reason: str, actor: str, source_user_id: int | None = None
    ) -> bool:
        with self.db.tx() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO fingerprint_bans VALUES (?,?,?,?)",
                (fp_hash, now_iso(), reason, source_user_id),
            )
        if cur.rowcount:
            self.audit(actor, "fingerprint.ban", f"fp:{fp_hash[:16]}", {"reason": reason})
        return bool(cur.rowcount)

    def unban_fingerprint(self, fp_hash: str, actor: str) -> bool:
        with self.db.tx() as c:
            cur = c.execute("DELETE FROM fingerprint_bans WHERE fp_hash=?", (fp_hash,))
        if cur.rowcount:
            self.audit(actor, "fingerprint.unban", f"fp:{fp_hash[:16]}")
        return bool(cur.rowcount)

    def is_fingerprint_banned(self, fp_hash: str) -> bool:
        return self.db.one("SELECT 1 FROM fingerprint_bans WHERE fp_hash=?", (fp_hash,)) is not None

    def list_fingerprint_bans(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.all("SELECT * FROM fingerprint_bans ORDER BY created_at")]

    # --------------------------------------------------------------- photos

    def insert_photo(
        self,
        *,
        extension: str,
        user_id: int,
        filename: str,
        thumb_filename: str,
        width: int,
        height: int,
        size: int,
        meta: dict[str, Any],
        created_at: str | None = None,
    ) -> Photo:
        public_id = new_public_id()
        with self.db.tx() as c:
            seq = c.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM photos WHERE extension=?", (extension,)
            ).fetchone()[0]
            c.execute(
                "INSERT INTO photos (public_id, extension, user_id, seq, filename, "
                "thumb_filename, created_at, width, height, bytes, meta) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    public_id, extension, user_id, seq, filename, thumb_filename,
                    created_at or now_iso(), width, height, size, json.dumps(meta),
                ),
            )  # fmt: skip
        photo = self.get_photo(public_id)
        assert photo is not None
        return photo

    def get_photo(self, public_id: str, *, include_deleted: bool = False) -> Photo | None:
        sql = (
            f"SELECT {_PHOTO_COLS} FROM photos p JOIN users u ON u.id=p.user_id "
            "WHERE p.public_id=?"
        )
        if not include_deleted:
            sql += " AND p.deleted_at IS NULL"
        row = self.db.one(sql, (public_id,))
        return _photo(row) if row else None

    def list_photos(self, q: PhotoQuery) -> list[Photo]:
        where, params = [], []
        if q.extension:
            where.append("p.extension=?")
            params.append(q.extension)
        if q.user_id is not None:
            where.append("p.user_id=?")
            params.append(q.user_id)
        if q.hidden is True:
            where.append("p.hidden_at IS NOT NULL")
        elif q.hidden is False:
            where.append("p.hidden_at IS NULL")
        if not q.include_deleted:
            where.append("p.deleted_at IS NULL")
        if q.before_id is not None:
            where.append("p.id<?")
            params.append(q.before_id)
        if q.after_id is not None:
            where.append("p.id>?")
            params.append(q.after_id)
        sql = f"SELECT {_PHOTO_COLS} FROM photos p JOIN users u ON u.id=p.user_id"
        if where:
            sql += " WHERE " + " AND ".join(where)
        order = "ASC" if q.order == "asc" else "DESC"
        # ids grow in upload order, so they double as the time order
        sql += f" ORDER BY p.id {order} LIMIT ?"
        params.append(max(1, min(q.limit, 1000)))
        return [_photo(r) for r in self.db.all(sql, params)]

    def photo_internal_id(self, public_id: str) -> int | None:
        row = self.db.one("SELECT id FROM photos WHERE public_id=?", (public_id,))
        return row["id"] if row else None

    def count_photos(self, extension: str | None = None, *, visible_only: bool = False) -> int:
        sql, params = "SELECT COUNT(*) FROM photos WHERE deleted_at IS NULL", []
        if extension:
            sql += " AND extension=?"
            params.append(extension)
        if visible_only:
            sql += " AND hidden_at IS NULL"
        row = self.db.one(sql, params)
        return int(row[0]) if row else 0

    def hide_photo(self, public_id: str, actor: str, reason: str = "admin") -> bool:
        with self.db.tx() as c:
            cur = c.execute(
                "UPDATE photos SET hidden_at=?, hidden_reason=? "
                "WHERE public_id=? AND hidden_at IS NULL AND deleted_at IS NULL",
                (now_iso(), reason, public_id),
            )
        if cur.rowcount:
            self.audit(actor, "photo.hide", f"photo:{public_id}")
        return bool(cur.rowcount)

    def unhide_photo(self, public_id: str, actor: str) -> bool:
        with self.db.tx() as c:
            cur = c.execute(
                "UPDATE photos SET hidden_at=NULL, hidden_reason=NULL "
                "WHERE public_id=? AND hidden_at IS NOT NULL AND deleted_at IS NULL",
                (public_id,),
            )
        if cur.rowcount:
            self.audit(actor, "photo.unhide", f"photo:{public_id}")
        return bool(cur.rowcount)

    def delete_photo(self, public_id: str, actor: str) -> bool:
        """Remove the files for good. The row stays as a tombstone so sequence
        numbers are never reused."""
        with self.db.tx() as c:
            row = c.execute(
                "SELECT extension, filename, thumb_filename FROM photos "
                "WHERE public_id=? AND deleted_at IS NULL",
                (public_id,),
            ).fetchone()
            if row is None:
                return False
            c.execute("UPDATE photos SET deleted_at=? WHERE public_id=?", (now_iso(), public_id))
            for name in (row["filename"], row["thumb_filename"]):
                self.photo_path(row["extension"], name).unlink(missing_ok=True)
        self.audit(actor, "photo.delete", f"photo:{public_id}")
        return True

    def photo_path(self, extension: str, filename: str) -> Path:
        return self.data_dir / extension / filename

    # ------------------------------------------------------- admin sessions

    def create_admin_session(
        self, token_hash: str, *, expires_at: str, pw_tag: str, ip: str, user_agent: str
    ) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM admin_sessions WHERE expires_at<?", (now_iso(),))
            c.execute(
                "INSERT INTO admin_sessions VALUES (?,?,?,?,?,?)",
                (token_hash, now_iso(), expires_at, pw_tag, ip, user_agent[:300]),
            )

    def get_admin_session(self, token_hash: str) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT * FROM admin_sessions WHERE token_hash=? AND expires_at>?",
            (token_hash, now_iso()),
        )
        return dict(row) if row else None

    def delete_admin_session(self, token_hash: str) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM admin_sessions WHERE token_hash=?", (token_hash,))

    # ----------------------------------------------------------------- audit

    def audit(self, actor: str, action: str, target: str = "", details: dict | None = None) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO audit_log (at, actor, action, target, details) VALUES (?,?,?,?,?)",
                (now_iso(), actor, action, target, json.dumps(details or {})),
            )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.all("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(limit, 1000),))
        return [dict(r) | {"details": json.loads(r["details"])} for r in rows]
