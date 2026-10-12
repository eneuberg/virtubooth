"""Read-only queries the admin screens need on top of `virtubooth.repo`.

Writes always go through the repo (it keeps the audit log); this module only
aggregates: counters, Instagram handles, fingerprint peers, paged audit log.
"""

from __future__ import annotations

import json
from typing import Any

from ..db import Database


def _int(value: Any) -> int:
    return int(value or 0)


def stats(db: Database) -> dict[str, Any]:
    photos = db.one(
        "SELECT COUNT(*) AS total, SUM(hidden_at IS NOT NULL) AS hidden, "
        "MAX(created_at) AS last_upload_at FROM photos WHERE deleted_at IS NULL"
    )
    deleted = db.one("SELECT COUNT(*) FROM photos WHERE deleted_at IS NOT NULL")
    users = db.one(
        "SELECT COUNT(*) AS total, SUM(banned_at IS NOT NULL) AS banned, "
        "SUM(instagram IS NOT NULL) AS instagram FROM users"
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
        "instagram": _int(users["instagram"]),
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
    }


def fingerprint_peers(db: Database, user_id: int) -> dict[str, list[dict[str, Any]]]:
    """For each fingerprint `user_id` showed: the other users that showed it too."""
    rows = db.all(
        "SELECT f.fp_hash, u.id, u.name, u.instagram, u.banned_at IS NOT NULL AS banned "
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
        "SELECT f.fp_hash, u.id, u.name, u.instagram, u.banned_at IS NOT NULL AS banned "
        "FROM user_fingerprints f JOIN users u ON u.id=f.user_id "
        "WHERE f.fp_hash IN (SELECT fp_hash FROM fingerprint_bans) ORDER BY u.id"
    )
    by_fp: dict[str, list[dict[str, Any]]] = {}
    for r in users:
        by_fp.setdefault(r["fp_hash"], []).append(_user_ref(r))
    return [dict(b) | {"users": by_fp.get(b["fp_hash"], [])} for b in bans]


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
