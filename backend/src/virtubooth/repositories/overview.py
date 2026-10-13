"""The dashboard's live overview (read only): a handful of aggregate queries
over users, visitors and photos. Definitions: domain/overview.py.

Party scale (hundreds of guests, a few thousand photos) keeps these cheap; the
admin polls them about every 10 s per open dashboard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..core.clock import iso
from ..db.database import Database
from ..domain.overview import (
    ACTIVE_MINUTES,
    RECENT_LONG_MINUTES,
    RECENT_SHORT_MINUTES,
    ActivityCounts,
    GuestCounts,
    Overview,
    PhotoCounts,
    ScanCounts,
)
from ._rows import as_int


class OverviewReadModel:
    def __init__(self, db: Database) -> None:
        self.db = db

    def overview(self, now: datetime | None = None) -> Overview:
        now = now or datetime.now(UTC)

        def ago(minutes: int) -> str:
            return iso(now - timedelta(minutes=minutes))

        active, short, long = (
            ago(ACTIVE_MINUTES),
            ago(RECENT_SHORT_MINUTES),
            ago(RECENT_LONG_MINUTES),
        )
        users = self.db.one(
            "SELECT COUNT(*) AS total, "
            "SUM(banned_at IS NULL AND last_seen_at>=?) AS active, "
            "SUM(instagram IS NOT NULL) AS instagram, "
            "SUM(banned_at IS NOT NULL) AS banned, "
            "SUM(uploads_paused_at IS NOT NULL) AS paused FROM users",
            (active,),
        )
        uploading = self.db.one(
            "SELECT COUNT(DISTINCT user_id) FROM photos WHERE created_at>=?", (active,)
        )
        visitors = self.db.one(
            "SELECT COUNT(*) AS scanned, SUM(user_id IS NOT NULL) AS joined, "
            "SUM(user_id IS NULL AND last_seen_at>=?) AS waiting, "
            "MIN(first_seen_at) AS since FROM visitors",
            (active,),
        )
        photos = self.db.one(
            "SELECT SUM(deleted_at IS NULL) AS total, "
            "SUM(deleted_at IS NULL AND hidden_at IS NOT NULL) AS hidden, "
            "SUM(created_at>=?) AS short, SUM(created_at>=?) AS long, "
            "MAX(created_at) AS last_upload_at FROM photos",
            (short, long),
        )
        per_ext = self.db.all(
            "SELECT extension, SUM(deleted_at IS NULL) AS photos, "
            "SUM(deleted_at IS NULL AND hidden_at IS NULL) AS visible, "
            "SUM(created_at>=?) AS long FROM photos GROUP BY extension ORDER BY extension",
            (long,),
        )
        assert users is not None and visitors is not None and photos is not None
        scanned, joined = as_int(visitors["scanned"]), as_int(visitors["joined"])
        total, hidden = as_int(photos["total"]), as_int(photos["hidden"])
        return Overview(
            at=iso(now),
            guests=GuestCounts(
                total=as_int(users["total"]),
                active_now=as_int(users["active"]),
                uploading_now=as_int(uploading[0]) if uploading else 0,
                instagram=as_int(users["instagram"]),
                banned=as_int(users["banned"]),
                paused=as_int(users["paused"]),
            ),
            scans=ScanCounts(
                scanned=scanned,
                joined=joined,
                not_joined=scanned - joined,
                waiting_now=as_int(visitors["waiting"]),
                since=visitors["since"],
            ),
            photos=PhotoCounts(
                total=total,
                visible=total - hidden,
                hidden=hidden,
                last_15_min=as_int(photos["short"]),
                last_60_min=as_int(photos["long"]),
                last_upload_at=photos["last_upload_at"],
            ),
            activities=[
                ActivityCounts(
                    id=r["extension"],
                    photos=as_int(r["photos"]),
                    visible=as_int(r["visible"]),
                    last_60_min=as_int(r["long"]),
                )
                for r in per_ext
            ],
        )
