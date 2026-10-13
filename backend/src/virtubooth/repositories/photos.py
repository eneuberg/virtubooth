"""Photos: rows plus where their files live. Rows are never removed: a deleted
photo stays as a tombstone (`deleted_at`) so sequence numbers are never reused."""

from __future__ import annotations

import builtins
import json
from pathlib import Path
from typing import Any

from ..db.database import Database
from ..domain.constants import HIDDEN_BY_BAN
from ..domain.models import Photo, PhotoQuery
from ._rows import PHOTO_COLS, as_int, photo_from_row

MAX_PAGE = 1000
# tombstones count: a number is never handed out twice
_NEXT_SEQ = "SELECT COALESCE(MAX(seq), 0) + 1 FROM photos WHERE extension=?"


class PhotosRepo:
    def __init__(self, db: Database, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir

    def path(self, extension: str, filename: str) -> Path:
        return self.data_dir / extension / filename

    def insert(
        self,
        *,
        public_id: str,
        extension: str,
        user_id: int,
        filename: str,
        thumb_filename: str,
        width: int,
        height: int,
        size: int,
        meta: dict[str, Any],
        created_at: str,
    ) -> None:
        with self.db.tx() as c:
            seq = c.execute(_NEXT_SEQ, (extension,)).fetchone()[0]
            c.execute(
                "INSERT INTO photos (public_id, extension, user_id, seq, filename, "
                "thumb_filename, created_at, width, height, bytes, meta) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    public_id, extension, user_id, seq, filename, thumb_filename,
                    created_at, width, height, size, json.dumps(meta),
                ),
            )  # fmt: skip

    def next_seq(self, extension: str) -> int:
        """The number the extension's next photo gets (unless another upload is faster)."""
        row = self.db.one(_NEXT_SEQ, (extension,))
        return as_int(row[0]) if row else 1

    def get(self, public_id: str, *, include_deleted: bool = False) -> Photo | None:
        sql = (
            f"SELECT {PHOTO_COLS} FROM photos p JOIN users u ON u.id=p.user_id WHERE p.public_id=?"
        )
        if not include_deleted:
            sql += " AND p.deleted_at IS NULL"
        row = self.db.one(sql, (public_id,))
        return photo_from_row(row) if row else None

    def list(self, q: PhotoQuery) -> list[Photo]:
        where: list[str] = []
        params: list[Any] = []
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
        sql = f"SELECT {PHOTO_COLS} FROM photos p JOIN users u ON u.id=p.user_id"
        if where:
            sql += " WHERE " + " AND ".join(where)
        order = "ASC" if q.order == "asc" else "DESC"
        # ids grow in upload order, so they double as the time order
        sql += f" ORDER BY p.id {order} LIMIT ?"
        # one more than the cap is allowed: callers ask for limit+1 to see if more follow
        params.append(max(1, min(q.limit, MAX_PAGE + 1)))
        return [photo_from_row(r) for r in self.db.all(sql, params)]

    def internal_id(self, public_id: str) -> int | None:
        row = self.db.one("SELECT id FROM photos WHERE public_id=?", (public_id,))
        return int(row["id"]) if row else None

    def count(
        self,
        extension: str | None = None,
        *,
        user_id: int | None = None,
        hidden: bool | None = None,
    ) -> int:
        """Non-deleted photos; same filters as `list` (without the cursor)."""
        where = ["deleted_at IS NULL"]
        params: list[Any] = []
        if extension:
            where.append("extension=?")
            params.append(extension)
        if user_id is not None:
            where.append("user_id=?")
            params.append(user_id)
        if hidden is True:
            where.append("hidden_at IS NOT NULL")
        elif hidden is False:
            where.append("hidden_at IS NULL")
        row = self.db.one(f"SELECT COUNT(*) FROM photos WHERE {' AND '.join(where)}", params)
        return as_int(row[0]) if row else 0

    def counts_by_extension(self) -> dict[str, int]:
        """Non-deleted photos per extension."""
        rows = self.db.all(
            "SELECT extension, COUNT(*) AS n FROM photos WHERE deleted_at IS NULL "
            "GROUP BY extension ORDER BY extension"
        )
        return {r["extension"]: int(r["n"]) for r in rows}

    # ---------------------------------------------------------- moderation

    def hide(self, public_id: str, *, at: str, reason: str) -> bool:
        with self.db.tx() as c:
            cur = c.execute(
                "UPDATE photos SET hidden_at=?, hidden_reason=? "
                "WHERE public_id=? AND hidden_at IS NULL AND deleted_at IS NULL",
                (at, reason, public_id),
            )
        return cur.rowcount > 0

    def unhide(self, public_id: str) -> bool:
        with self.db.tx() as c:
            cur = c.execute(
                "UPDATE photos SET hidden_at=NULL, hidden_reason=NULL "
                "WHERE public_id=? AND hidden_at IS NOT NULL AND deleted_at IS NULL",
                (public_id,),
            )
        return cur.rowcount > 0

    def mark_deleted(self, public_id: str, *, at: str) -> builtins.list[Path] | None:
        """Tombstone the row; returns the files to remove (None: nothing to delete).
        The caller removes them once the transaction committed."""
        with self.db.tx() as c:
            row = c.execute(
                "SELECT extension, filename, thumb_filename FROM photos "
                "WHERE public_id=? AND deleted_at IS NULL",
                (public_id,),
            ).fetchone()
            if row is None:
                return None
            c.execute("UPDATE photos SET deleted_at=? WHERE public_id=?", (at, public_id))
        return [self.path(row["extension"], name) for name in (row[1], row[2])]

    def hide_for_ban(self, user_id: int, *, at: str) -> None:
        with self.db.tx() as c:
            c.execute(
                "UPDATE photos SET hidden_at=?, hidden_reason=? "
                "WHERE user_id=? AND hidden_at IS NULL AND deleted_at IS NULL",
                (at, HIDDEN_BY_BAN, user_id),
            )

    def restore_after_ban(self, user_id: int) -> None:
        # only photos the ban hid come back; ones an admin hid stay hidden
        with self.db.tx() as c:
            c.execute(
                "UPDATE photos SET hidden_at=NULL, hidden_reason=NULL "
                "WHERE user_id=? AND hidden_reason=?",
                (user_id, HIDDEN_BY_BAN),
            )
