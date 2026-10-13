"""The `settings` table: small JSON values the admin switches at runtime
(not to be confused with `virtubooth.settings`, the environment config).

- `upload_pause` = {enabled, since, period, by}: the new-guest lock. The period
  counter persists while it is off.
- `upload_stop` = {enabled, since, by}: nobody can upload.
"""

from __future__ import annotations

import json
from typing import Any

from ..db.database import Database
from ..domain.constants import UPLOAD_LOCK_KEY, UPLOAD_STOP_KEY
from ..domain.models import UploadLock, UploadStop


class AppSettingsRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str) -> dict[str, Any]:
        row = self.db.one("SELECT value FROM settings WHERE key=?", (key,))
        if row is None:
            return {}
        value = json.loads(row["value"])
        return value if isinstance(value, dict) else {}

    def put(self, key: str, value: dict[str, Any], *, at: str) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) ON CONFLICT(key) "
                "DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value), at),
            )

    # ------------------------------------------------------ upload switches

    def upload_lock(self) -> UploadLock:
        """The new-guest lock: every guest who joins while it is on starts with
        uploads paused, tagged `period`."""
        raw = self.get(UPLOAD_LOCK_KEY)
        enabled = bool(raw.get("enabled"))
        return UploadLock(
            enabled=enabled,
            since=raw.get("since") if enabled else None,
            period=raw.get("period") if enabled else None,
            by=raw.get("by"),
        )

    def lock_period_counter(self) -> int:
        """The last lock period number (kept while the lock is off)."""
        return int(self.get(UPLOAD_LOCK_KEY).get("period") or 0)

    def put_upload_lock(
        self, *, enabled: bool, since: str | None, period: int, by: str, at: str
    ) -> None:
        self.put(
            UPLOAD_LOCK_KEY,
            {"enabled": enabled, "since": since, "period": period, "by": by},
            at=at,
        )

    def upload_stop(self) -> UploadStop:
        """Stop all uploads. Per-guest pauses and the new-guest lock are separate."""
        raw = self.get(UPLOAD_STOP_KEY)
        enabled = bool(raw.get("enabled"))
        return UploadStop(
            enabled=enabled, since=raw.get("since") if enabled else None, by=raw.get("by")
        )

    def put_upload_stop(self, *, enabled: bool, since: str | None, by: str, at: str) -> None:
        self.put(UPLOAD_STOP_KEY, {"enabled": enabled, "since": since, "by": by}, at=at)
