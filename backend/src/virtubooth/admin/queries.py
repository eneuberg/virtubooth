"""Read-only queries the admin screens need on top of `virtubooth.repo`.

Writes always go through the repo (it keeps the audit log); this module only
aggregates: counters, Instagram handles, fingerprint peers, paged audit log.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from ..db import Database

# The ban reason core (identity.join) gives an identity that joined showing a
# banned fingerprint. Such guests may just own the same phone model.
AUTO_BAN_REASON = "Gerät gesperrt (Fingerprint)"


def _int(value: Any) -> int:
    return int(value or 0)


def is_auto_banned(banned: bool, ban_reason: str | None) -> bool:
    """Banned only because the identity started on a banned fingerprint."""
    return bool(banned) and ban_reason == AUTO_BAN_REASON


def stats(db: Database) -> dict[str, Any]:
    photos = db.one(
        "SELECT COUNT(*) AS total, SUM(hidden_at IS NOT NULL) AS hidden, "
        "MAX(created_at) AS last_upload_at FROM photos WHERE deleted_at IS NULL"
    )
    deleted = db.one("SELECT COUNT(*) FROM photos WHERE deleted_at IS NOT NULL")
    users = db.one(
        "SELECT COUNT(*) AS total, SUM(banned_at IS NOT NULL) AS banned, "
        "SUM(instagram IS NOT NULL) AS instagram, "
        "COUNT(DISTINCT instagram) AS instagram_handles FROM users"
    )
    uploaders = db.one("SELECT COUNT(DISTINCT user_id) FROM photos WHERE deleted_at IS NULL")
    fp_bans = db.one("SELECT COUNT(*) FROM fingerprint_bans")
    per_ext = db.all(
        "SELECT extension, COUNT(*) AS total, SUM(hidden_at IS NOT NULL) AS hidden "
        "FROM photos WHERE deleted_at IS NULL GROUP BY extension ORDER BY extension"
    )
    assert photos is not None and users is not None
    total, hidden = _int(photos["total"]), _int(photos["hidden"])
    return {
        "photos": total,
        "visible": total - hidden,
        "hidden": hidden,
        "deleted": _int(deleted[0]) if deleted else 0,
        "last_upload_at": photos["last_upload_at"],
        "guests": _int(users["total"]),
        "banned": _int(users["banned"]),
        # guests (devices) that gave a handle, and the distinct handles: one
        # person with two phones is two guests but one handle
        "instagram": _int(users["instagram"]),
        "instagram_handles": _int(users["instagram_handles"]),
        "uploaders": _int(uploaders[0]) if uploaders else 0,
        "fingerprint_bans": _int(fp_bans[0]) if fp_bans else 0,
        "extensions": {
            r["extension"]: {"photos": _int(r["total"]), "hidden": _int(r["hidden"])}
            for r in per_ext
        },
    }


def count_photos(
    db: Database,
    *,
    extension: str | None = None,
    user_id: int | None = None,
    hidden: bool | None = None,
) -> int:
    """Same filters as repo.list_photos (without the cursor)."""
    where, params = ["deleted_at IS NULL"], []
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
    row = db.one(f"SELECT COUNT(*) FROM photos WHERE {' AND '.join(where)}", params)
    return _int(row[0]) if row else 0


def extensions_with_photos(db: Database) -> list[str]:
    return [r[0] for r in db.all("SELECT DISTINCT extension FROM photos ORDER BY extension")]


def _user_ref(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "instagram": row["instagram"],
        "banned": bool(row["banned"]),
        "auto_banned": is_auto_banned(row["banned"], row["ban_reason"]),
    }


_REF_COLS = "u.id, u.name, u.instagram, u.banned_at IS NOT NULL AS banned, u.ban_reason"


def fingerprint_peers(db: Database, user_id: int) -> dict[str, list[dict[str, Any]]]:
    """For each fingerprint `user_id` showed: the other users that showed it too."""
    rows = db.all(
        f"SELECT f.fp_hash, {_REF_COLS} "
        "FROM user_fingerprints f JOIN users u ON u.id=f.user_id "
        "WHERE f.fp_hash IN (SELECT fp_hash FROM user_fingerprints WHERE user_id=?) "
        "AND f.user_id<>? ORDER BY u.id",
        (user_id, user_id),
    )
    peers: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        peers.setdefault(r["fp_hash"], []).append(_user_ref(r))
    return peers


def fingerprint_bans(db: Database) -> list[dict[str, Any]]:
    bans = db.all(
        "SELECT b.fp_hash, b.created_at, b.reason, b.source_user_id, "
        "s.name AS source_user_name FROM fingerprint_bans b "
        "LEFT JOIN users s ON s.id=b.source_user_id ORDER BY b.created_at DESC"
    )
    users = db.all(
        f"SELECT f.fp_hash, {_REF_COLS} "
        "FROM user_fingerprints f JOIN users u ON u.id=f.user_id "
        "WHERE f.fp_hash IN (SELECT fp_hash FROM fingerprint_bans) ORDER BY u.id"
    )
    by_fp: dict[str, list[dict[str, Any]]] = {}
    for r in users:
        by_fp.setdefault(r["fp_hash"], []).append(_user_ref(r))
    return [dict(b) | {"users": by_fp.get(b["fp_hash"], [])} for b in bans]


def auto_banned_users(db: Database, fp_hashes: Iterable[str]) -> list[int]:
    """Identities that started banned because they showed one of `fp_hashes`
    (now unbanned) and show no fingerprint that is still banned: lifting the
    fingerprint ban should let them in too."""
    hashes = list(dict.fromkeys(fp_hashes))
    if not hashes:
        return []
    marks = ",".join("?" * len(hashes))
    rows = db.all(
        "SELECT u.id FROM users u WHERE u.banned_at IS NOT NULL AND u.ban_reason=? "
        "AND EXISTS (SELECT 1 FROM user_fingerprints f "
        f"WHERE f.user_id=u.id AND f.fp_hash IN ({marks})) "
        "AND NOT EXISTS (SELECT 1 FROM user_fingerprints f JOIN fingerprint_bans b "
        "ON b.fp_hash=f.fp_hash WHERE f.user_id=u.id) ORDER BY u.id",
        (AUTO_BAN_REASON, *hashes),
    )
    return [r["id"] for r in rows]


def auto_ban_sources(db: Database, user_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    """For auto-banned identities: the fingerprint ban that hit them (if it
    still exists) and the guest that ban was made over."""
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    rows = db.all(
        "SELECT f.user_id, b.fp_hash, b.source_user_id, s.name AS source_user_name "
        "FROM user_fingerprints f JOIN fingerprint_bans b ON b.fp_hash=f.fp_hash "
        "LEFT JOIN users s ON s.id=b.source_user_id "
        f"WHERE f.user_id IN ({','.join('?' * len(ids))}) ORDER BY f.first_seen, b.created_at",
        ids,
    )
    sources: dict[int, dict[str, Any]] = {}
    for r in rows:
        sources.setdefault(
            r["user_id"],
            {
                "fp_hash": r["fp_hash"],
                "source_user_id": r["source_user_id"],
                "source_user_name": r["source_user_name"],
            },
        )
    return sources


def instagram_handles(db: Database) -> list[dict[str, Any]]:
    """Every Instagram handle with the guests that gave it and their photo counts.

    Several devices may share one handle (same person, two phones)."""
    rows = db.all(
        "SELECT u.instagram, u.id, u.name, u.banned_at IS NOT NULL AS banned, "
        "COUNT(p.id) AS photos, SUM(p.hidden_at IS NULL AND p.id IS NOT NULL) AS visible, "
        "MAX(p.created_at) AS last_upload_at "
        "FROM users u LEFT JOIN photos p ON p.user_id=u.id AND p.deleted_at IS NULL "
        "WHERE u.instagram IS NOT NULL GROUP BY u.id ORDER BY u.instagram, u.id"
    )
    handles: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = handles.setdefault(
            r["instagram"],
            {
                "handle": r["instagram"],
                "users": [],
                "photos": 0,
                "visible": 0,
                "last_upload_at": None,
            },
        )
        entry["users"].append(
            {
                "id": r["id"],
                "name": r["name"],
                "banned": bool(r["banned"]),
                "photos": _int(r["photos"]),
            }
        )
        entry["photos"] += _int(r["photos"])
        entry["visible"] += _int(r["visible"])
        if r["last_upload_at"] and (
            entry["last_upload_at"] is None or r["last_upload_at"] > entry["last_upload_at"]
        ):
            entry["last_upload_at"] = r["last_upload_at"]
    for entry in handles.values():
        entry["hidden"] = entry["photos"] - entry["visible"]
    # most active first: those are the ones worth tagging
    return sorted(handles.values(), key=lambda e: (-e["photos"], e["handle"]))


def audit_page(
    db: Database, *, before: int | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    sql, params = "SELECT * FROM audit_log", []
    if before is not None:
        sql += " WHERE id<?"
        params.append(before)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    return [dict(r) | {"details": json.loads(r["details"] or "{}")} for r in db.all(sql, params)]
