"""Export jobs: what the admin's export section starts (archive, timelapse),
run one at a time by the export worker (services/exports.py). The QR sheet
(kind `qr`) is gone: the QR-Codes tab makes each code's PNG/PDF/poster, and old
`qr` records stay in the table but are hidden (`EXPORT_KINDS`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

ExportKind = Literal["archive", "timelapse"]
ExportStatus = Literal["queued", "running", "done", "failed"]

EXPORT_KINDS: Final[tuple[ExportKind, ...]] = ("archive", "timelapse")
# a job in one of these has no file yet and blocks another job of its kind
ACTIVE_STATUSES: Final[tuple[ExportStatus, ...]] = ("queued", "running")

# what a job left queued or running by a stopped server becomes on the next start
RESTART_ERROR: Final = "Server wurde neu gestartet."

# finished files kept in <data>/exports/; older done jobs are deleted with their file
KEEP_DONE: Final = 10
# failed jobs kept (no file, only the record with the error)
KEEP_FAILED: Final = 10

MEDIA_TYPES: Final[dict[ExportKind, str]] = {
    "archive": "application/zip",
    "timelapse": "video/mp4",
}


@dataclass(frozen=True)
class ExportJob:
    id: str
    kind: ExportKind
    status: ExportStatus
    options: dict[str, Any]
    progress: float | None
    created_at: str
    created_by: str
    started_at: str | None
    finished_at: str | None
    error: str | None
    file_name: str | None
    bytes: int | None

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATUSES
