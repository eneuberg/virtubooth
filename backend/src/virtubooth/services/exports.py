"""Export jobs: the admin starts an archive or a timelapse; one
worker thread runs them one at a time and writes the files to <data>/exports/.

- State lives in the `export_jobs` table (migration v3): a job survives a
  restart as a record. Jobs a stopped server left queued or running are marked
  failed on the next start ("Server wurde neu gestartet.").
- At most one queued or running job per kind: starting another returns that one.
- Every change is an `export.updated` event (progress at most every 5 % or
  second); a deleted or pruned job is `export.deleted`.
- The newest KEEP_DONE finished files are kept; older ones go with their record.
- Creation and deletion are audit-logged in the same transaction.

The worker runs while the app does: `attach()` from the app's lifespan start,
`detach()` from its end (counted: several test clients may share one app).
Shutting down cancels the running job (it fails with the restart message).
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..api.schemas.exports import ExportJob as ExportJobOut
from ..api.schemas.exports import ExportOptions
from ..core import errors
from ..core.clock import local_now, now_iso
from ..db.database import Database
from ..domain.exports import (
    EXPORT_KINDS,
    KEEP_DONE,
    KEEP_FAILED,
    RESTART_ERROR,
    ExportJob,
    ExportKind,
)
from ..domain.models import new_public_id
from ..repositories.container import Repositories
from ..tools._common import EXPORTS_DIR, ToolError
from .events import AdminEvents
from .export_runners import (
    RUNNERS,
    JobCancelled,
    JobContext,
    JobFailed,
    Runner,
    user_message,
)

if TYPE_CHECKING:
    from ..runtime import Core

log = logging.getLogger("virtubooth.exports")

GENERIC_ERROR = "Der Export ist fehlgeschlagen. Details stehen im Server-Log."
# progress events: at least this much further, or this long since the last one
PROGRESS_STEP = 0.05
PROGRESS_INTERVAL = 1.0
# how long the app's shutdown waits for the cancelled job to stop
STOP_TIMEOUT = 10.0


def _not_found() -> errors.ApiError:
    return errors.not_found("Export nicht gefunden.")


def _unlink(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.warning("could not remove %s", path)


@dataclass(frozen=True)
class Download:
    job: ExportJob
    path: Path
    file_name: str


class ExportService:
    def __init__(self, core: Core, db: Database, repos: Repositories, events: AdminEvents) -> None:
        self.core = core
        self.db = db
        self.repos = repos
        self.events = events
        # tests swap single runners (e.g. one that blocks until released)
        self.runners: dict[ExportKind, Runner] = dict(RUNNERS)
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self._attached = 0
        self._stopping = False
        self._pending = False  # jobs were queued since the worker last looked
        self._idle = True  # the worker waits for work (or there is none)
        self._cancel = threading.Event()

    @property
    def exports_dir(self) -> Path:
        return self.core.settings.data_dir / EXPORTS_DIR

    # ------------------------------------------------------------ queries

    def jobs(self) -> list[ExportJob]:
        """Every job, newest first. Records of a removed kind (the old `qr`
        sheet) are hidden."""
        return [j for j in self.repos.exports.list() if j.kind in EXPORT_KINDS]

    def get(self, job_id: str) -> ExportJob | None:
        job = self.repos.exports.get(job_id)
        return job if job is not None and job.kind in EXPORT_KINDS else None

    @staticmethod
    def ffmpeg_available() -> bool:
        return shutil.which("ffmpeg") is not None

    # ---------------------------------------------------------- mutations

    def create(
        self, kind: ExportKind, options: ExportOptions, *, actor: str
    ) -> tuple[ExportJob, bool]:
        """Queue a job; (job, True). When one of this kind is already queued or
        running: (that job, False), nothing new."""
        values = options.model_dump(mode="json")
        with self.db.tx():
            existing = self.repos.exports.active(kind)
            if existing is not None:
                return existing, False
            job_id, at = new_public_id(), now_iso()
            self.repos.exports.insert(job_id, kind=kind, options=values, created_at=at, by=actor)
            self.repos.audit.log(
                actor, "export.create", f"export:{job_id}", {"kind": kind, "options": values}, at=at
            )
            job = self.repos.exports.get(job_id)
            assert job is not None
            self.events.export_updated(ExportJobOut.of(job))
            self.db.on_commit(self._wake)
        return job, True

    def delete(self, job_id: str, *, actor: str) -> None:
        """Remove a job and its file. A queued job is cancelled this way; a
        running one can't be deleted (409 export_running)."""
        with self.db.tx():
            job = self.get(job_id)
            if job is None:
                raise _not_found()
            if job.status == "running":
                raise errors.ApiError(
                    409,
                    "export_running",
                    "Dieser Export läuft gerade. Du kannst ihn löschen, sobald er fertig ist.",
                )
            at = now_iso()
            self.repos.exports.delete(job_id)
            self.repos.audit.log(
                actor,
                "export.delete",
                f"export:{job_id}",
                {"kind": job.kind, "status": job.status, "file_name": job.file_name},
                at=at,
            )
            files = self._files_of(job)
            self.db.on_commit(lambda: _unlink(files))
            self.events.export_deleted(job_id)

    def download(self, job_id: str) -> Download:
        """The finished file, only from inside <data>/exports/."""
        job = self.get(job_id)
        if job is None:
            raise _not_found()
        if job.status != "done":
            message = (
                "Dieser Export ist fehlgeschlagen, es gibt keine Datei."
                if job.status == "failed"
                else "Der Export ist noch nicht fertig."
            )
            raise errors.ApiError(409, "export_not_ready", message)
        path = self._file_path(job.file_name)
        if path is None or job.file_name is None or not path.is_file():
            raise errors.not_found("Die Datei dieses Exports gibt es nicht mehr.")
        return Download(job, path, job.file_name)

    def recover(self) -> None:
        """On start: what a stopped server left queued or running has failed."""
        for job_id in self.repos.exports.fail_unfinished(at=now_iso(), error=RESTART_ERROR):
            _unlink([self._part_path(job_id)])
            for leftover in self._scratch_dirs(job_id):
                shutil.rmtree(leftover, ignore_errors=True)

    # -------------------------------------------------------------- paths

    def _file_path(self, name: str | None) -> Path | None:
        """<data>/exports/<name>, or None when `name` would point elsewhere."""
        if not name or name.startswith(".") or "/" in name or "\\" in name:
            return None
        root = self.exports_dir.resolve()
        path = (root / name).resolve()
        return path if path.parent == root else None

    def _part_path(self, job_id: str) -> Path:
        return self.exports_dir / f".{job_id}.part"

    def _scratch_dirs(self, job_id: str) -> list[Path]:
        if not self.exports_dir.is_dir():
            return []
        return [p for p in self.exports_dir.glob(f".vb-job-{job_id}-*") if p.is_dir()]

    def _files_of(self, job: ExportJob) -> list[Path]:
        path = self._file_path(job.file_name)
        return [p for p in (path, self._part_path(job.id)) if p is not None]

    def _file_name(self, job: ExportJob) -> str:
        stamp = local_now(self.core.settings.timezone).strftime("%Y%m%d-%H%M")
        suffix = f"{stamp}-{job.id[:8]}"
        if job.kind == "archive":
            return f"archiv-{suffix}.zip"
        extension = str(job.options.get("extension") or "fotos")
        return f"zeitraffer-{extension}-{suffix}.mp4"

    # ------------------------------------------------------------- worker

    def attach(self) -> None:
        """The app started (lifespan): run the worker."""
        with self._cond:
            self._attached += 1
            self._stopping = False
            self._cancel.clear()
            # jobs queued before the worker ran
            self._pending, self._idle = True, False
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._loop, name="vb-export-worker", daemon=True
                )
                self._thread.start()
            self._cond.notify_all()

    def detach(self, timeout: float = STOP_TIMEOUT) -> None:
        """The app stops (lifespan end): cancel the running job, stop the worker."""
        with self._cond:
            self._attached = max(0, self._attached - 1)
            thread = self._thread
            if self._attached or thread is None:
                return
            self._stopping = True
            self._cancel.set()
            self._cond.notify_all()
        thread.join(timeout)
        if thread.is_alive():
            log.warning("export worker did not stop within %.0f s", timeout)

    def wait_idle(self, timeout: float = 60.0) -> bool:
        """Block until no job is queued or running (tests); False on timeout."""
        with self._cond:
            return self._cond.wait_for(lambda: self._idle and not self._pending, timeout)

    def _wake(self) -> None:
        with self._cond:
            self._pending, self._idle = True, False
            self._cond.notify_all()

    def _loop(self) -> None:
        while True:
            with self._cond:
                while not self._pending and not self._stopping:
                    self._idle = True
                    self._cond.notify_all()
                    self._cond.wait()
                if self._stopping:
                    self._idle = True
                    self._cond.notify_all()
                    return
                self._pending = False
            try:
                while not self._cancel.is_set():
                    job = self.repos.exports.claim_next(at=now_iso())
                    if job is None:
                        break
                    self._run(job)
            except Exception:
                log.exception("export worker error")

    def _run(self, job: ExportJob) -> None:
        self._publish(job.id)  # running
        part = self._part_path(job.id)
        try:
            file_name = self._file_name(job)
            runner = self.runners[job.kind]
            self.exports_dir.mkdir(parents=True, exist_ok=True)
            runner(
                JobContext(
                    job=job,
                    settings=self.core.settings,
                    repos=self.repos,
                    extensions=list(self.core.extensions.values()),
                    exports_dir=self.exports_dir,
                    file_name=file_name,
                    part=part,
                    progress=_Progress(self, job.id),
                )
            )
            if self._cancel.is_set():
                raise JobCancelled
            target = self.exports_dir / file_name
            os.replace(part, target)
            size = target.stat().st_size
        except JobCancelled:
            self._fail(job.id, RESTART_ERROR)
        except JobFailed as exc:
            log.info("export %s (%s) failed: %s", job.id, job.kind, exc.message)
            self._fail(job.id, exc.message)
        except ToolError as exc:
            log.warning("export %s (%s) failed: %s", job.id, job.kind, exc)
            self._fail(job.id, user_message(exc))
        except Exception:
            log.exception("export %s (%s) failed", job.id, job.kind)
            self._fail(job.id, GENERIC_ERROR)
        else:
            with self.db.tx():
                self.repos.exports.finish(job.id, at=now_iso(), file_name=file_name, size=size)
                self._publish(job.id)
        finally:
            _unlink([part])
        self._prune()

    def _fail(self, job_id: str, error: str) -> None:
        with self.db.tx():
            self.repos.exports.fail(job_id, at=now_iso(), error=error)
            self._publish(job_id)

    def _publish(self, job_id: str) -> None:
        job = self.get(job_id)
        if job is not None:
            self.events.export_updated(ExportJobOut.of(job))

    def report(self, job_id: str, progress: float) -> None:
        with self.db.tx():
            self.repos.exports.set_progress(job_id, round(progress, 4))
            self._publish(job_id)

    def _prune(self) -> None:
        """Keep the newest KEEP_DONE files (and KEEP_FAILED failed records)."""
        with self.db.tx():
            old = self.repos.exports.beyond("done", KEEP_DONE)
            old += self.repos.exports.beyond("failed", KEEP_FAILED)
            files: list[Path] = []
            for job in old:
                self.repos.exports.delete(job.id)
                files += self._files_of(job)
                self.events.export_deleted(job.id)
            if files:
                self.db.on_commit(lambda: _unlink(files))
        if old:
            log.info("pruned %d old export job(s)", len(old))


class _Progress:
    """`ctx.progress`: monotonic, throttled, and the cancellation point."""

    def __init__(self, service: ExportService, job_id: str) -> None:
        self.service = service
        self.job_id = job_id
        self.value = 0.0
        self.sent = 0.0
        self.sent_at = time.monotonic()
        self.cancelled: Callable[[], bool] = service._cancel.is_set

    def __call__(self, fraction: float) -> None:
        if self.cancelled():
            raise JobCancelled
        self.value = max(self.value, min(1.0, fraction))
        now = time.monotonic()
        if self.value - self.sent >= PROGRESS_STEP or (
            self.value > self.sent and now - self.sent_at >= PROGRESS_INTERVAL
        ):
            self.sent, self.sent_at = self.value, now
            self.service.report(self.job_id, self.value)
