"""QR codes (`party_codes`), every token they ever had (`party_code_tokens`, by
SHA-256) and which browser opened which code (`code_visitors`).

Rows are never deleted: „Löschen“ sets `revoked_at`. A code's current token is
its `party_code_tokens` row with `retired_at IS NULL`; changing the token
retires that row and bumps `token_gen` (which the access cookie carries).
"""

from __future__ import annotations

import builtins
import sqlite3
from datetime import UTC, datetime, timedelta

from ..core.clock import iso
from ..db.database import Database
from ..domain.codes import CodeStats, PartyCode, token_hash
from ..domain.overview import ACTIVE_MINUTES
from ._rows import as_int

_COLS = (
    "c.id, c.animal, c.token, c.token_gen, c.target, c.note, c.created_at, c.created_by, "
    "c.updated_at, c.revoked_at, c.revoked_by"
)


def _code(row: sqlite3.Row) -> PartyCode:
    return PartyCode(
        id=row["id"],
        animal=row["animal"],
        token=row["token"],
        token_gen=row["token_gen"],
        target=row["target"],
        note=row["note"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        updated_at=row["updated_at"],
        revoked_at=row["revoked_at"],
        revoked_by=row["revoked_by"],
    )


class PartyCodesRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------ reading

    def any(self) -> bool:
        """Whether a code was ever created (revoked ones count)."""
        return self.db.one("SELECT 1 FROM party_codes LIMIT 1") is not None

    def get(self, code_id: int) -> PartyCode | None:
        row = self.db.one(f"SELECT {_COLS} FROM party_codes c WHERE c.id=?", (code_id,))
        return _code(row) if row else None

    def list(self) -> builtins.list[PartyCode]:
        """Every code, revoked ones included, by number."""
        return [_code(r) for r in self.db.all(f"SELECT {_COLS} FROM party_codes c ORDER BY c.id")]

    def lowest_active(self) -> PartyCode | None:
        row = self.db.one(
            f"SELECT {_COLS} FROM party_codes c WHERE c.revoked_at IS NULL ORDER BY c.id LIMIT 1"
        )
        return _code(row) if row else None

    def by_token(self, token: str) -> PartyCode | None:
        """The active code whose current token this is. Looked up by hash, so
        the time it takes says nothing about the stored tokens."""
        row = self.db.one(
            f"SELECT {_COLS} FROM party_code_tokens t JOIN party_codes c ON c.id=t.code_id "
            "WHERE t.token_hash=? AND t.retired_at IS NULL AND c.revoked_at IS NULL",
            (token_hash(token),),
        )
        return _code(row) if row else None

    def token_taken(self, token: str) -> bool:
        """Some code has or had this token."""
        row = self.db.one(
            "SELECT 1 FROM party_code_tokens WHERE token_hash=?", (token_hash(token),)
        )
        return row is not None

    def animal_counts(self) -> dict[str, int]:
        rows = self.db.all("SELECT animal, COUNT(*) AS n FROM party_codes GROUP BY animal")
        return {r["animal"]: r["n"] for r in rows}

    def counts(self) -> tuple[int, int]:
        """(active, revoked)."""
        row = self.db.one(
            "SELECT SUM(revoked_at IS NULL) AS active, SUM(revoked_at IS NOT NULL) AS revoked "
            "FROM party_codes"
        )
        assert row is not None
        return as_int(row["active"]), as_int(row["revoked"])

    def stats(self, now: datetime | None = None) -> dict[int, CodeStats]:
        """Statistics of every code (codes are few: one query for all)."""
        now = now or datetime.now(UTC)
        active_since = iso(now - timedelta(minutes=ACTIVE_MINUTES))
        rows = self.db.all(
            "WITH v AS (SELECT code_id, SUM(scans) AS scans, COUNT(*) AS people, "
            "  MIN(first_seen_at) AS first_scan_at, MAX(last_seen_at) AS last_scan_at "
            "  FROM code_visitors GROUP BY code_id), "
            "nj AS (SELECT cv.code_id, COUNT(*) AS n FROM code_visitors cv "
            "  JOIN visitors vi ON vi.id=cv.visitor_id WHERE vi.user_id IS NULL "
            "  GROUP BY cv.code_id), "
            "g AS (SELECT code_id, COUNT(*) AS guests, "
            "  SUM(banned_at IS NULL AND last_seen_at>=?) AS active_now "
            "  FROM users WHERE code_id IS NOT NULL GROUP BY code_id), "
            "p AS (SELECT u.code_id, COUNT(*) AS photos FROM photos ph "
            "  JOIN users u ON u.id=ph.user_id "
            "  WHERE u.code_id IS NOT NULL AND ph.deleted_at IS NULL GROUP BY u.code_id) "
            "SELECT c.id, v.scans, v.people, v.first_scan_at, v.last_scan_at, nj.n AS not_joined, "
            "  g.guests, g.active_now, p.photos "
            "FROM party_codes c LEFT JOIN v ON v.code_id=c.id LEFT JOIN nj ON nj.code_id=c.id "
            "LEFT JOIN g ON g.code_id=c.id LEFT JOIN p ON p.code_id=c.id",
            (active_since,),
        )
        return {
            r["id"]: CodeStats(
                scans=as_int(r["scans"]),
                people=as_int(r["people"]),
                guests=as_int(r["guests"]),
                not_joined=as_int(r["not_joined"]),
                photos=as_int(r["photos"]),
                active_now=as_int(r["active_now"]),
                first_scan_at=r["first_scan_at"],
                last_scan_at=r["last_scan_at"],
            )
            for r in rows
        }

    # ------------------------------------------------------------ writing

    def create(self, *, animal: str, token: str, target: str, note: str, at: str, by: str) -> int:
        """A new code and its token row; its number."""
        with self.db.tx() as c:
            cur = c.execute(
                "INSERT INTO party_codes (animal, token, target, note, created_at, created_by, "
                "updated_at) VALUES (?,?,?,?,?,?,?)",
                (animal, token, target, note, at, by, at),
            )
            code_id = cur.lastrowid
            assert code_id is not None
            c.execute(
                "INSERT INTO party_code_tokens (token_hash, code_id, set_at) VALUES (?,?,?)",
                (token_hash(token), code_id, at),
            )
        return code_id

    def edit(self, code_id: int, *, target: str, note: str, at: str) -> None:
        with self.db.tx() as c:
            c.execute(
                "UPDATE party_codes SET target=?, note=?, updated_at=? WHERE id=?",
                (target, note, at, code_id),
            )

    def set_token(self, code_id: int, token: str, *, at: str) -> None:
        """Retire the code's token and give it `token` (the next generation)."""
        with self.db.tx() as c:
            c.execute(
                "UPDATE party_code_tokens SET retired_at=? WHERE code_id=? AND retired_at IS NULL",
                (at, code_id),
            )
            c.execute(
                "INSERT INTO party_code_tokens (token_hash, code_id, set_at) VALUES (?,?,?)",
                (token_hash(token), code_id, at),
            )
            c.execute(
                "UPDATE party_codes SET token=?, token_gen=token_gen+1, updated_at=? WHERE id=?",
                (token, at, code_id),
            )

    def revoke(self, code_id: int, *, at: str, by: str) -> None:
        """The token stops working (the lookup only joins active codes); the
        row and its statistics stay."""
        with self.db.tx() as c:
            c.execute(
                "UPDATE party_codes SET revoked_at=?, revoked_by=?, updated_at=? "
                "WHERE id=? AND revoked_at IS NULL",
                (at, by, at, code_id),
            )

    def record_visit(self, code_id: int, visitor_id: str, *, at: str) -> None:
        """A valid scan of `code_id` by the browser `visitor_id`."""
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO code_visitors (code_id, visitor_id, first_seen_at, last_seen_at) "
                "VALUES (?,?,?,?) ON CONFLICT(code_id, visitor_id) DO UPDATE SET "
                "scans=scans+1, last_seen_at=excluded.last_seen_at",
                (code_id, visitor_id, at, at),
            )

    def adopt_existing(self, code_id: int) -> None:
        """Seeding: every guest and every visitor from before the codes came
        through `code_id` (they all used the one party token)."""
        with self.db.tx() as c:
            c.execute("UPDATE users SET code_id=? WHERE code_id IS NULL", (code_id,))
            c.execute(
                "INSERT OR IGNORE INTO code_visitors "
                "(code_id, visitor_id, first_seen_at, last_seen_at, scans) "
                "SELECT ?, id, first_seen_at, last_seen_at, 1 FROM visitors",
                (code_id,),
            )
