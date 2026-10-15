"""The `settings` table: small JSON values the admin switches at runtime
(not to be confused with `virtubooth.settings`, the environment config).

- `upload_pause` = {enabled, since, period, by}: the new-guest lock. The period
  counter persists while it is off.
- `upload_stop` = {enabled, since, by}: nobody can upload.
- `join_stop` = {enabled, since, by}: nobody new can join.
- `event` = {name, by}: the event name set in the admin (absent: VB_PARTY_NAME).
- `admin.password` = {hash, changed_at, by}: the admin password set in the admin
  or by `virtubooth reset-admin-password` (absent: VB_ADMIN_PASSWORD).
- `public_address` = {address, by}: the public address set in Allgemeines
  (absent: VB_PUBLIC_BASE_URL, else the request's origin).
- `public_address_check` = {status, url, at, message}: the last reachability check.

Extensions keep their own keys as `x.<extension id>.<name>` (e.g.
`x.booth.filters`), defined in their package.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

from ..db.database import Database
from ..domain.constants import JOIN_STOP_KEY, UPLOAD_LOCK_KEY, UPLOAD_STOP_KEY
from ..domain.models import UploadLock, UploadStop

EVENT_KEY: Final = "event"
ADMIN_PASSWORD_KEY: Final = "admin.password"
PUBLIC_ADDRESS_KEY: Final = "public_address"
PUBLIC_ADDRESS_CHECK_KEY: Final = "public_address_check"


@dataclass(frozen=True)
class EventName:
    """The event name the host set (the row's `updated_at` as `at`)."""

    name: str
    by: str | None
    at: str | None


@dataclass(frozen=True)
class StoredAddress:
    """The public address the host set (the row's `updated_at` as `at`)."""

    address: str
    by: str | None
    at: str | None


@dataclass(frozen=True)
class StoredCheck:
    """The last check of the public address."""

    status: str
    url: str | None
    at: str | None
    message: str


@dataclass(frozen=True)
class StoredPassword:
    """The admin password hash (core/passwords.py encoding)."""

    hash: str
    changed_at: str | None
    by: str | None


class AppSettingsRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str) -> dict[str, Any]:
        row = self.db.one("SELECT value FROM settings WHERE key=?", (key,))
        if row is None:
            return {}
        value = json.loads(row["value"])
        return value if isinstance(value, dict) else {}

    def get_entry(self, key: str) -> tuple[dict[str, Any], str | None]:
        """The value and when it was written (`({}, None)` when absent)."""
        row = self.db.one("SELECT value, updated_at FROM settings WHERE key=?", (key,))
        if row is None:
            return {}, None
        value = json.loads(row["value"])
        return (value if isinstance(value, dict) else {}), row["updated_at"]

    def put(self, key: str, value: dict[str, Any], *, at: str) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) ON CONFLICT(key) "
                "DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value), at),
            )

    def delete(self, key: str) -> bool:
        """Remove a value (back to its default). False when there was none."""
        with self.db.tx() as c:
            return c.execute("DELETE FROM settings WHERE key=?", (key,)).rowcount > 0

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

    # --------------------------------------------------------- join switch

    def join_stop(self) -> UploadStop:
        """Nobody new can join (same shape as the upload stop)."""
        raw = self.get(JOIN_STOP_KEY)
        enabled = bool(raw.get("enabled"))
        return UploadStop(
            enabled=enabled, since=raw.get("since") if enabled else None, by=raw.get("by")
        )

    def put_join_stop(self, *, enabled: bool, since: str | None, by: str, at: str) -> None:
        self.put(JOIN_STOP_KEY, {"enabled": enabled, "since": since, "by": by}, at=at)

    # ------------------------------------------------------------ event name

    def event_name(self) -> EventName | None:
        """The name the host set in the admin; None: VB_PARTY_NAME applies."""
        raw, at = self.get_entry(EVENT_KEY)
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            return None
        by = raw.get("by")
        return EventName(name=name, by=by if isinstance(by, str) else None, at=at)

    def put_event_name(self, name: str, *, by: str, at: str) -> None:
        self.put(EVENT_KEY, {"name": name, "by": by}, at=at)

    # -------------------------------------------------------- admin password

    def admin_password(self) -> StoredPassword | None:
        """The stored admin password hash; None: VB_ADMIN_PASSWORD applies."""
        raw = self.get(ADMIN_PASSWORD_KEY)
        encoded = raw.get("hash")
        if not isinstance(encoded, str) or not encoded:
            return None
        changed_at, by = raw.get("changed_at"), raw.get("by")
        return StoredPassword(
            hash=encoded,
            changed_at=changed_at if isinstance(changed_at, str) else None,
            by=by if isinstance(by, str) else None,
        )

    def put_admin_password(self, encoded: str, *, by: str, at: str) -> None:
        self.put(ADMIN_PASSWORD_KEY, {"hash": encoded, "changed_at": at, "by": by}, at=at)

    # -------------------------------------------------------- public address

    def public_address(self) -> StoredAddress | None:
        """The address the host set in Allgemeines; None: env or automatic."""
        raw, at = self.get_entry(PUBLIC_ADDRESS_KEY)
        address = raw.get("address")
        if not isinstance(address, str) or not address:
            return None
        by = raw.get("by")
        return StoredAddress(address=address, by=by if isinstance(by, str) else None, at=at)

    def put_public_address(self, address: str, *, by: str, at: str) -> None:
        self.put(PUBLIC_ADDRESS_KEY, {"address": address, "by": by}, at=at)

    def public_address_check(self) -> StoredCheck | None:
        raw = self.get(PUBLIC_ADDRESS_CHECK_KEY)
        status = raw.get("status")
        if not isinstance(status, str):
            return None
        url, at, message = raw.get("url"), raw.get("at"), raw.get("message")
        return StoredCheck(
            status=status,
            url=url if isinstance(url, str) else None,
            at=at if isinstance(at, str) else None,
            message=message if isinstance(message, str) else "",
        )

    def put_public_address_check(self, check: StoredCheck) -> None:
        at = check.at or ""
        self.put(
            PUBLIC_ADDRESS_CHECK_KEY,
            {"status": check.status, "url": check.url, "at": check.at, "message": check.message},
            at=at,
        )
