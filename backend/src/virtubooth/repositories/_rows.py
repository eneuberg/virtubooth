"""Column lists and row mapping shared by the repositories."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..domain.models import Photo, User, UserRef

USER_COLS = (
    "u.id, u.public_id, u.name, u.created_at, u.last_seen_at, u.consent_at, "
    "u.consent_version, u.instagram, u.fp_hash, u.fp_components, u.first_ip, "
    "u.last_ip, u.user_agent, u.banned_at, u.ban_reason, u.uploads_paused_at, "
    "u.uploads_paused_source, u.uploads_lock_period, u.online_seconds, u.online_sessions, "
    "u.online_at, u.code_id"
)
PHOTO_COLS = (
    "p.id, p.public_id, p.extension, p.user_id, p.seq, p.filename, p.thumb_filename, "
    "p.created_at, p.width, p.height, p.bytes, p.meta, p.hidden_at, p.hidden_reason, "
    "p.deleted_at, u.name AS user_name, u.instagram AS user_instagram, "
    "u.banned_at IS NOT NULL AS user_banned, "
    "u.uploads_paused_at IS NOT NULL AS user_uploads_paused, "
    "u.ban_reason AS user_ban_reason"
)
# a user as other lists mention it
REF_COLS = "u.id, u.name, u.instagram, u.banned_at IS NOT NULL AS banned, u.ban_reason"


def user_from_row(row: sqlite3.Row, photo_count: int = 0) -> User:
    d = dict(row)
    d.pop("photo_count", None)
    d["fp_components"] = json.loads(d["fp_components"] or "{}")
    return User(**d, photo_count=photo_count)


def photo_from_row(row: sqlite3.Row) -> Photo:
    d = dict(row)
    d["meta"] = json.loads(d["meta"] or "{}")
    d["user_banned"] = bool(d["user_banned"])
    d["user_uploads_paused"] = bool(d["user_uploads_paused"])
    return Photo(**d)


def ref_from_row(row: sqlite3.Row) -> UserRef:
    return UserRef(
        id=row["id"],
        name=row["name"],
        instagram=row["instagram"],
        banned=bool(row["banned"]),
        ban_reason=row["ban_reason"],
    )


def as_int(value: Any) -> int:
    return int(value or 0)
