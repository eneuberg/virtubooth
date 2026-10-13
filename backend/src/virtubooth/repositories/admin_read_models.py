"""Read-only aggregates the admin screens need (formerly admin/queries.py):
counters, Instagram handles, fingerprint peers, device bans, auto-ban sources."""

from __future__ import annotations

from collections.abc import Iterable

from ..db.database import Database
from ..domain.constants import AUTO_BAN_REASON
from ..domain.models import (
    ActivityCount,
    AutoBanSource,
    DeviceBan,
    ExtensionCount,
    InstagramHandle,
    InstagramUser,
    Stats,
    UserRef,
    UserStats,
)
from ._rows import REF_COLS, as_int, ref_from_row


class AdminReadModels:
    def __init__(self, db: Database) -> None:
        self.db = db

    def stats(self) -> Stats:
        photos = self.db.one(
            "SELECT COUNT(*) AS total, SUM(hidden_at IS NOT NULL) AS hidden, "
            "MAX(created_at) AS last_upload_at FROM photos WHERE deleted_at IS NULL"
        )
        deleted = self.db.one("SELECT COUNT(*) FROM photos WHERE deleted_at IS NOT NULL")
        users = self.db.one(
            "SELECT COUNT(*) AS total, SUM(banned_at IS NOT NULL) AS banned, "
            "SUM(instagram IS NOT NULL) AS instagram, "
            "COUNT(DISTINCT instagram) AS instagram_handles FROM users"
        )
        uploaders = self.db.one(
            "SELECT COUNT(DISTINCT user_id) FROM photos WHERE deleted_at IS NULL"
        )
        fp_bans = self.db.one("SELECT COUNT(*) FROM fingerprint_bans")
        per_ext = self.db.all(
            "SELECT extension, COUNT(*) AS total, SUM(hidden_at IS NOT NULL) AS hidden "
            "FROM photos WHERE deleted_at IS NULL GROUP BY extension ORDER BY extension"
        )
        assert photos is not None and users is not None
        total, hidden = as_int(photos["total"]), as_int(photos["hidden"])
        return Stats(
            photos=total,
            visible=total - hidden,
            hidden=hidden,
            deleted=as_int(deleted[0]) if deleted else 0,
            last_upload_at=photos["last_upload_at"],
            guests=as_int(users["total"]),
            banned=as_int(users["banned"]),
            instagram=as_int(users["instagram"]),
            instagram_handles=as_int(users["instagram_handles"]),
            uploaders=as_int(uploaders[0]) if uploaders else 0,
            fingerprint_bans=as_int(fp_bans[0]) if fp_bans else 0,
            extensions={
                r["extension"]: ExtensionCount(
                    photos=as_int(r["total"]), hidden=as_int(r["hidden"])
                )
                for r in per_ext
            },
        )

    def extensions_with_photos(self) -> list[str]:
        return [
            r[0] for r in self.db.all("SELECT DISTINCT extension FROM photos ORDER BY extension")
        ]

    def fingerprint_peers(self, user_id: int) -> dict[str, list[UserRef]]:
        """For each fingerprint `user_id` showed: the other users that showed it too."""
        rows = self.db.all(
            f"SELECT f.fp_hash, {REF_COLS} "
            "FROM user_fingerprints f JOIN users u ON u.id=f.user_id "
            "WHERE f.fp_hash IN (SELECT fp_hash FROM user_fingerprints WHERE user_id=?) "
            "AND f.user_id<>? ORDER BY u.id",
            (user_id, user_id),
        )
        peers: dict[str, list[UserRef]] = {}
        for r in rows:
            peers.setdefault(r["fp_hash"], []).append(ref_from_row(r))
        return peers

    def device_bans(self) -> list[DeviceBan]:
        """Every fingerprint ban, newest first, with the users that showed it."""
        bans = self.db.all(
            "SELECT b.fp_hash, b.created_at, b.reason, b.source_user_id, "
            "s.name AS source_user_name FROM fingerprint_bans b "
            "LEFT JOIN users s ON s.id=b.source_user_id ORDER BY b.created_at DESC"
        )
        users = self.db.all(
            f"SELECT f.fp_hash, {REF_COLS} "
            "FROM user_fingerprints f JOIN users u ON u.id=f.user_id "
            "WHERE f.fp_hash IN (SELECT fp_hash FROM fingerprint_bans) ORDER BY u.id"
        )
        by_fp: dict[str, list[UserRef]] = {}
        for r in users:
            by_fp.setdefault(r["fp_hash"], []).append(ref_from_row(r))
        return [
            DeviceBan(
                fp_hash=b["fp_hash"],
                created_at=b["created_at"],
                reason=b["reason"],
                source_user_id=b["source_user_id"],
                source_user_name=b["source_user_name"],
                users=by_fp.get(b["fp_hash"], []),
            )
            for b in bans
        ]

    def auto_banned_users(self, fp_hashes: Iterable[str]) -> list[int]:
        """Identities that started banned because they showed one of `fp_hashes`
        (now unbanned) and show no fingerprint that is still banned: lifting the
        fingerprint ban should let them in too."""
        hashes = list(dict.fromkeys(fp_hashes))
        if not hashes:
            return []
        marks = ",".join("?" * len(hashes))
        rows = self.db.all(
            "SELECT u.id FROM users u WHERE u.banned_at IS NOT NULL AND u.ban_reason=? "
            "AND EXISTS (SELECT 1 FROM user_fingerprints f "
            f"WHERE f.user_id=u.id AND f.fp_hash IN ({marks})) "
            "AND NOT EXISTS (SELECT 1 FROM user_fingerprints f JOIN fingerprint_bans b "
            "ON b.fp_hash=f.fp_hash WHERE f.user_id=u.id) ORDER BY u.id",
            (AUTO_BAN_REASON, *hashes),
        )
        return [int(r["id"]) for r in rows]

    def auto_ban_sources(self, user_ids: Iterable[int]) -> dict[int, AutoBanSource]:
        """For auto-banned identities: the fingerprint ban that hit them (if it
        still exists) and the guest that ban was made over."""
        ids = list(dict.fromkeys(user_ids))
        if not ids:
            return {}
        rows = self.db.all(
            "SELECT f.user_id, b.fp_hash, b.source_user_id, s.name AS source_user_name "
            "FROM user_fingerprints f JOIN fingerprint_bans b ON b.fp_hash=f.fp_hash "
            "LEFT JOIN users s ON s.id=b.source_user_id "
            f"WHERE f.user_id IN ({','.join('?' * len(ids))}) ORDER BY f.first_seen, b.created_at",
            ids,
        )
        sources: dict[int, AutoBanSource] = {}
        for r in rows:
            sources.setdefault(
                r["user_id"],
                AutoBanSource(
                    fp_hash=r["fp_hash"],
                    source_user_id=r["source_user_id"],
                    source_user_name=r["source_user_name"],
                ),
            )
        return sources

    def instagram_handles(self) -> list[InstagramHandle]:
        """Every Instagram handle with the guests that gave it and their photo
        counts, most active first. Several devices may share one handle."""
        rows = self.db.all(
            "SELECT u.instagram, u.id, u.name, u.banned_at IS NOT NULL AS banned, u.ban_reason, "
            "COUNT(p.id) AS photos, SUM(p.hidden_at IS NULL AND p.id IS NOT NULL) AS visible, "
            "MAX(p.created_at) AS last_upload_at "
            "FROM users u LEFT JOIN photos p ON p.user_id=u.id AND p.deleted_at IS NULL "
            "WHERE u.instagram IS NOT NULL GROUP BY u.id ORDER BY u.instagram, u.id"
        )
        handles: dict[str, InstagramHandle] = {}
        for r in rows:
            entry = handles.setdefault(r["instagram"], InstagramHandle(handle=r["instagram"]))
            entry.users.append(
                InstagramUser(
                    id=r["id"],
                    name=r["name"],
                    banned=bool(r["banned"]),
                    ban_reason=r["ban_reason"],
                    photos=as_int(r["photos"]),
                )
            )
            entry.photos += as_int(r["photos"])
            entry.visible += as_int(r["visible"])
            if r["last_upload_at"] and (
                entry.last_upload_at is None or r["last_upload_at"] > entry.last_upload_at
            ):
                entry.last_upload_at = r["last_upload_at"]
        for entry in handles.values():
            entry.hidden = entry.photos - entry.visible
        # most active first: those are the ones worth tagging
        return sorted(handles.values(), key=lambda e: (-e.photos, e.handle))

    def user_stats(self, user_id: int) -> UserStats:
        """One guest's photos: counts, per activity (most first), first and last
        upload. Two aggregate queries over the guest's rows."""
        totals = self.db.one(
            "SELECT SUM(deleted_at IS NULL) AS photos, "
            "SUM(deleted_at IS NULL AND hidden_at IS NOT NULL) AS hidden, "
            "SUM(deleted_at IS NOT NULL) AS deleted, "
            "MIN(created_at) AS first_at, MAX(created_at) AS last_at "
            "FROM photos WHERE user_id=?",
            (user_id,),
        )
        per_activity = self.db.all(
            "SELECT extension, COUNT(*) AS photos FROM photos "
            "WHERE user_id=? AND deleted_at IS NULL "
            "GROUP BY extension ORDER BY photos DESC, extension",
            (user_id,),
        )
        assert totals is not None
        photos, hidden = as_int(totals["photos"]), as_int(totals["hidden"])
        return UserStats(
            photos=photos,
            visible=photos - hidden,
            hidden=hidden,
            deleted=as_int(totals["deleted"]),
            by_activity=[
                ActivityCount(id=r["extension"], photos=as_int(r["photos"])) for r in per_activity
            ],
            first_photo_at=totals["first_at"],
            last_photo_at=totals["last_at"],
        )
