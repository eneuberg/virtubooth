"""Export jobs (`export_jobs`): one row per job the admin started. The export
service changes the status; the worker claims queued jobs one at a time."""

from __future__ import annotations

import builtins
import json
import sqlite3
from typing import Any, cast

from ..db.database import Database
from ..domain.exports import ExportJob, ExportKind, ExportStatus

COLS = (
    "id, kind, status, options, progress, created_at, created_by, started_at, finished_at, "
    "error, file_name, bytes"
)
# newest first; rowid breaks ties between jobs created in the same millisecond
NEWEST_FIRST = "ORDER BY created_at DESC, rowid DESC"


def _job(row: sqlite3.Row) -> ExportJob:
    options = json.loads(row["options"] or "{}")
    return ExportJob(
        id=row["id"],
        kind=cast(ExportKind, row["kind"]),
        status=cast(ExportStatus, row["status"]),
        options=options if isinstance(options, dict) else {},
        progress=row["progress"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
        file_name=row["file_name"],
        bytes=row["bytes"],
    )


class ExportJobsRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def insert(
        self, job_id: str, *, kind: ExportKind, options: dict[str, Any], created_at: str, by: str
    ) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO export_jobs (id, kind, status, options, created_at, created_by) "
                "VALUES (?,?,'queued',?,?,?)",
                (job_id, kind, json.dumps(options, sort_keys=True), created_at, by),
            )

    def get(self, job_id: str) -> ExportJob | None:
        row = self.db.one(f"SELECT {COLS} FROM export_jobs WHERE id=?", (job_id,))
        return _job(row) if row else None

    def list(self) -> builtins.list[ExportJob]:
        """Every job, newest first (pruning keeps the table small)."""
        return [_job(r) for r in self.db.all(f"SELECT {COLS} FROM export_jobs {NEWEST_FIRST}")]

    def active(self, kind: ExportKind) -> ExportJob | None:
        """The queued or running job of this kind (there is at most one)."""
        row = self.db.one(
            f"SELECT {COLS} FROM export_jobs WHERE kind=? AND status IN ('queued','running') "
            f"{NEWEST_FIRST} LIMIT 1",
            (kind,),
        )
        return _job(row) if row else None

    def claim_next(self, *, at: str) -> ExportJob | None:
        """The oldest queued job, now marked running (atomic against `delete`)."""
        with self.db.tx() as c:
            row = c.execute(
                "SELECT id FROM export_jobs WHERE status='queued' "
                "ORDER BY created_at, rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            c.execute(
                "UPDATE export_jobs SET status='running', started_at=?, progress=0 WHERE id=?",
                (at, row["id"]),
            )
        return self.get(row["id"])

    def set_progress(self, job_id: str, progress: float) -> None:
        with self.db.tx() as c:
            c.execute(
                "UPDATE export_jobs SET progress=? WHERE id=? AND status='running'",
                (progress, job_id),
            )

    def finish(self, job_id: str, *, at: str, file_name: str, size: int) -> None:
        with self.db.tx() as c:
            c.execute(
                "UPDATE export_jobs SET status='done', progress=1, finished_at=?, file_name=?, "
                "bytes=?, error=NULL WHERE id=? AND status='running'",
                (at, file_name, size, job_id),
            )

    def fail(self, job_id: str, *, at: str, error: str) -> None:
        with self.db.tx() as c:
            c.execute(
                "UPDATE export_jobs SET status='failed', finished_at=?, error=? "
                "WHERE id=? AND status IN ('queued','running')",
                (at, error, job_id),
            )

    def fail_unfinished(self, *, at: str, error: str) -> builtins.list[str]:
        """Mark every queued or running job failed; returns their ids."""
        with self.db.tx() as c:
            ids = [
                r["id"]
                for r in c.execute(
                    "SELECT id FROM export_jobs WHERE status IN ('queued','running')"
                ).fetchall()
            ]
            c.execute(
                "UPDATE export_jobs SET status='failed', finished_at=?, error=? "
                "WHERE status IN ('queued','running')",
                (at, error),
            )
        return ids

    def delete(self, job_id: str) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM export_jobs WHERE id=?", (job_id,))

    def beyond(self, status: ExportStatus, keep: int) -> builtins.list[ExportJob]:
        """Jobs with this status older than the newest `keep` (to prune)."""
        rows = self.db.all(
            f"SELECT {COLS} FROM export_jobs WHERE status=? {NEWEST_FIRST} LIMIT -1 OFFSET ?",
            (status, keep),
        )
        return [_job(r) for r in rows]
