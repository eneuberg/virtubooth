"""Admin JSON API, mounted at /api/admin. Every route requires an admin session.

Login/logout/session live in virtubooth/admin_auth.py (core).

Photos are addressed by their public id, users by their numeric id. Every
mutation goes through the repo with the admin's actor name (audit log) and
publishes an event so every open admin screen stays in sync:

  photo.hidden / photo.unhidden   {"photo": admin_view}
  photo.deleted                   {"id": public id, "photo": admin_view}
  user.banned / user.unbanned     {"user": admin_view, "photos": [admin_view, ...]}
  fingerprint.banned / .unbanned  {"fp_hash": ...}

Core itself publishes photo.created ({"photo": admin_view}) and user.created.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StringConstraints

from .. import errors
from ..context import Core
from ..deps import Admin, admin_from_cookie, get_core, require_admin
from ..events import sse_stream
from ..repo import Photo, PhotoQuery, User
from . import queries

PHOTO_ID_PATTERN = r"^[A-Za-z0-9_-]{8,32}$"
FP_HASH_PATTERN = r"^[0-9a-f]{16,64}$"
EXT_ID_PATTERN = r"^[a-z][a-z0-9-]{1,30}$"
MAX_ID = 2**62
BULK_MAX = 200
USER_PHOTOS_MAX = 1000
# an open event stream re-checks the admin session this often (logout, expiry)
SESSION_RECHECK_SECONDS = 30.0

_PHOTO_ID_RE = re.compile(PHOTO_ID_PATTERN)
_EXT_ID_RE = re.compile(EXT_ID_PATTERN)

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])

PhotoId = Annotated[str, Path(pattern=PHOTO_ID_PATTERN)]
UserId = Annotated[int, Path(ge=1, lt=MAX_ID)]
FpHash = Annotated[str, Path(pattern=FP_HASH_PATTERN)]
PhotoIdItem = Annotated[str, StringConstraints(pattern=PHOTO_ID_PATTERN)]


# ------------------------------------------------------------------ helpers


def _blank(value: str | None) -> str | None:
    value = value.strip() if value is not None else None
    return value or None


def _parse_hidden(raw: str | None) -> bool | None:
    """hidden=true|hidden → only hidden, false|visible → only visible, all/'' → both."""
    value = (_blank(raw) or "all").lower()
    if value in ("all", "both"):
        return None
    if value in ("1", "true", "yes", "hidden"):
        return True
    if value in ("0", "false", "no", "visible"):
        return False
    raise errors.bad_request("Ungültiger Filter für versteckt/sichtbar.", "invalid_filter")


def _parse_bool_filter(raw: str | None) -> bool | None:
    value = (_blank(raw) or "all").lower()
    if value in ("all", "both"):
        return None
    if value in ("1", "true", "yes"):
        return True
    if value in ("0", "false", "no"):
        return False
    raise errors.bad_request("Ungültiger Filter.", "invalid_filter")


def _cursor(core: Core, public_id: str | None) -> int | None:
    if public_id is None:
        return None
    internal = core.repo.photo_internal_id(public_id)
    if internal is None:
        raise errors.bad_request("Unbekannter Cursor.", "invalid_cursor")
    return internal


def _photo_or_404(core: Core, photo_id: str) -> Photo:
    photo = core.repo.get_photo(photo_id)
    if photo is None:
        raise errors.not_found("Foto nicht gefunden.")
    return photo


def _user_or_404(core: Core, user_id: int) -> User:
    user = core.repo.get_user(user_id)
    if user is None:
        raise errors.not_found("Gast nicht gefunden.")
    return user


def _user_photos(core: Core, user_id: int) -> list[dict[str, Any]]:
    photos = core.repo.list_photos(PhotoQuery(user_id=user_id, limit=USER_PHOTOS_MAX))
    return [p.admin_view() for p in photos]


def _user_ref(user: User) -> dict[str, Any]:
    return {"id": user.id, "name": user.name, "instagram": user.instagram, "banned": user.banned}


# ------------------------------------------------------------------- photos


@router.get("/photos")
def list_photos(
    core: Core = Depends(get_core),
    extension: Annotated[str | None, Query(max_length=40)] = None,
    hidden: Annotated[str | None, Query(max_length=10)] = None,
    user_id: Annotated[str | None, Query(max_length=20)] = None,
    before: Annotated[str | None, Query(max_length=40)] = None,
    after: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Newest first. Page with `before=<next>`; poll for news with `after=<newest id>`."""
    ext = _blank(extension)
    if ext is not None and not _EXT_ID_RE.fullmatch(ext):
        raise errors.bad_request("Ungültige Aktivität.", "invalid_filter")
    uid: int | None = None
    if _blank(user_id) is not None:
        try:
            uid = int(user_id)  # type: ignore[arg-type]
        except ValueError as exc:
            raise errors.bad_request("Ungültige Gast-ID.", "invalid_filter") from exc
        if not 1 <= uid < MAX_ID:
            raise errors.bad_request("Ungültige Gast-ID.", "invalid_filter")
    cursors = {}
    for name, raw in (("before", before), ("after", after)):
        value = _blank(raw)
        if value is not None and not _PHOTO_ID_RE.fullmatch(value):
            raise errors.bad_request("Unbekannter Cursor.", "invalid_cursor")
        cursors[name] = _cursor(core, value)
    hidden_filter = _parse_hidden(hidden)

    photos = core.repo.list_photos(
        PhotoQuery(
            extension=ext,
            user_id=uid,
            hidden=hidden_filter,
            before_id=cursors["before"],
            after_id=cursors["after"],
            limit=limit,
        )
    )
    result: dict[str, Any] = {
        "photos": [p.admin_view() for p in photos],
        "next": photos[-1].public_id if len(photos) == limit else None,
    }
    if cursors["before"] is None and cursors["after"] is None:
        result["total"] = queries.count_photos(
            core.db, extension=ext, user_id=uid, hidden=hidden_filter
        )
    return result


@router.get("/photos/{photo_id}")
def get_photo(photo_id: PhotoId, core: Core = Depends(get_core)) -> dict[str, Any]:
    return {"photo": _photo_or_404(core, photo_id).admin_view()}


def _set_hidden(core: Core, admin: Admin, photo_id: str, hide: bool) -> tuple[bool, Photo | None]:
    if hide:
        changed = core.repo.hide_photo(photo_id, admin.actor)
    else:
        changed = core.repo.unhide_photo(photo_id, admin.actor)
    photo = core.repo.get_photo(photo_id)
    if changed and photo is not None:
        core.bus.publish("photo.hidden" if hide else "photo.unhidden", {"photo": photo.admin_view()})
    return changed, photo


def _delete(core: Core, admin: Admin, photo_id: str) -> bool:
    if not core.repo.delete_photo(photo_id, admin.actor):
        return False
    photo = core.repo.get_photo(photo_id, include_deleted=True)
    core.bus.publish(
        "photo.deleted", {"id": photo_id, "photo": photo.admin_view() if photo else None}
    )
    return True


@router.post("/photos/{photo_id}/hide")
def hide_photo(
    photo_id: PhotoId, core: Core = Depends(get_core), admin: Admin = Depends(require_admin)
) -> dict[str, Any]:
    _photo_or_404(core, photo_id)
    changed, photo = _set_hidden(core, admin, photo_id, True)
    if photo is None:
        raise errors.not_found("Foto nicht gefunden.")
    return {"photo": photo.admin_view(), "changed": changed}


@router.post("/photos/{photo_id}/unhide")
def unhide_photo(
    photo_id: PhotoId, core: Core = Depends(get_core), admin: Admin = Depends(require_admin)
) -> dict[str, Any]:
    _photo_or_404(core, photo_id)
    changed, photo = _set_hidden(core, admin, photo_id, False)
    if photo is None:
        raise errors.not_found("Foto nicht gefunden.")
    return {"photo": photo.admin_view(), "changed": changed}


@router.delete("/photos/{photo_id}")
def delete_photo(
    photo_id: PhotoId, core: Core = Depends(get_core), admin: Admin = Depends(require_admin)
) -> dict[str, Any]:
    if not _delete(core, admin, photo_id):
        raise errors.not_found("Foto nicht gefunden.")
    return {"ok": True, "id": photo_id}


class BulkIn(BaseModel):
    ids: list[PhotoIdItem] = Field(min_length=1, max_length=BULK_MAX)
    action: Literal["hide", "unhide", "delete"]


@router.post("/photos/bulk")
def bulk(
    body: BulkIn, core: Core = Depends(get_core), admin: Admin = Depends(require_admin)
) -> dict[str, Any]:
    changed: list[str] = []
    unchanged: list[str] = []
    missing: list[str] = []
    for photo_id in dict.fromkeys(body.ids):  # dedupe, keep order
        if core.repo.get_photo(photo_id) is None:
            missing.append(photo_id)
            continue
        if body.action == "delete":
            ok = _delete(core, admin, photo_id)
        else:
            ok, _ = _set_hidden(core, admin, photo_id, body.action == "hide")
        (changed if ok else unchanged).append(photo_id)
    return {"action": body.action, "changed": changed, "unchanged": unchanged, "missing": missing}


# -------------------------------------------------------------------- users


@router.get("/users")
def list_users(
    core: Core = Depends(get_core),
    search: Annotated[str | None, Query(max_length=100)] = None,
    banned: Annotated[str | None, Query(max_length=10)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> dict[str, Any]:
    users = core.repo.list_users(
        banned=_parse_bool_filter(banned), search=_blank(search), limit=limit, offset=offset
    )
    return {
        "users": [u.admin_view() for u in users],
        "next_offset": offset + len(users) if len(users) == limit else None,
    }


@router.get("/users/{user_id}")
def get_user(user_id: UserId, core: Core = Depends(get_core)) -> dict[str, Any]:
    user = _user_or_404(core, user_id)
    peers = queries.fingerprint_peers(core.db, user_id)
    fingerprints = [
        f | {"current": f["fp_hash"] == user.fp_hash, "users": peers.get(f["fp_hash"], [])}
        for f in core.repo.user_fingerprints(user_id)
    ]
    return {
        "user": user.admin_view(),
        "fingerprints": fingerprints,
        "sharing": [_user_ref(u) for u in core.repo.users_sharing_fingerprint(user_id)],
        "photos": _user_photos(core, user_id),
    }


class BanIn(BaseModel):
    reason: str = Field(default="", max_length=200)
    # also ban the device fingerprint: new identities showing it start banned
    fingerprint: bool = False


class UnbanIn(BaseModel):
    # also lift the bans on every fingerprint this guest showed
    fingerprint: bool = False


@router.post("/users/{user_id}/ban")
def ban_user(
    user_id: UserId,
    body: BanIn,
    core: Core = Depends(get_core),
    admin: Admin = Depends(require_admin),
) -> dict[str, Any]:
    user = _user_or_404(core, user_id)
    if body.fingerprint and not user.fp_hash:
        raise errors.bad_request(
            "Für diesen Gast ist kein Fingerprint bekannt.", "no_fingerprint"
        )
    reason = " ".join(body.reason.split())
    changed = core.repo.ban_user(user_id, reason, admin.actor)
    fp_banned = False
    if body.fingerprint and user.fp_hash:
        fp_banned = core.repo.ban_fingerprint(
            user.fp_hash, reason, admin.actor, source_user_id=user_id
        )
        if fp_banned:
            core.bus.publish("fingerprint.banned", {"fp_hash": user.fp_hash, "user_id": user_id})
    updated = _user_or_404(core, user_id)
    photos = _user_photos(core, user_id)
    if changed:
        core.bus.publish("user.banned", {"user": updated.admin_view(), "photos": photos})
    return {
        "user": updated.admin_view(),
        "changed": changed,
        "fingerprint_banned": fp_banned,
        "photos": photos,
    }


@router.post("/users/{user_id}/unban")
def unban_user(
    user_id: UserId,
    body: Annotated[UnbanIn | None, Body()] = None,
    core: Core = Depends(get_core),
    admin: Admin = Depends(require_admin),
) -> dict[str, Any]:
    _user_or_404(core, user_id)
    changed = core.repo.unban_user(user_id, admin.actor)
    lifted: list[str] = []
    if body is not None and body.fingerprint:
        for f in core.repo.user_fingerprints(user_id):
            if f["banned"] and core.repo.unban_fingerprint(f["fp_hash"], admin.actor):
                lifted.append(f["fp_hash"])
                core.bus.publish("fingerprint.unbanned", {"fp_hash": f["fp_hash"]})
    updated = _user_or_404(core, user_id)
    photos = _user_photos(core, user_id)
    if changed:
        core.bus.publish("user.unbanned", {"user": updated.admin_view(), "photos": photos})
    return {
        "user": updated.admin_view(),
        "changed": changed,
        "fingerprints_unbanned": lifted,
        "photos": photos,
    }


# --------------------------------------------------------- fingerprint bans


@router.get("/fingerprint-bans")
def fingerprint_bans(core: Core = Depends(get_core)) -> dict[str, Any]:
    return {"bans": queries.fingerprint_bans(core.db)}


@router.delete("/fingerprint-bans/{fp_hash}")
def unban_fingerprint(
    fp_hash: FpHash, core: Core = Depends(get_core), admin: Admin = Depends(require_admin)
) -> dict[str, Any]:
    if not core.repo.unban_fingerprint(fp_hash, admin.actor):
        raise errors.not_found("Diese Fingerprint-Sperre gibt es nicht.")
    core.bus.publish("fingerprint.unbanned", {"fp_hash": fp_hash})
    return {"ok": True, "fp_hash": fp_hash}


# ------------------------------------------------------------ overview data


@router.get("/stats")
def stats(core: Core = Depends(get_core)) -> dict[str, Any]:
    return queries.stats(core.db)


INSTAGRAM_PREVIEW = 8


@router.get("/instagram")
def instagram(core: Core = Depends(get_core)) -> dict[str, Any]:
    """All handles, most active first, each with its newest visible photos."""
    handles = queries.instagram_handles(core.db)
    for entry in handles:
        recent: list[Photo] = []
        for user in entry["users"]:
            if user["photos"]:
                recent += core.repo.list_photos(
                    PhotoQuery(user_id=user["id"], hidden=False, limit=INSTAGRAM_PREVIEW)
                )
        recent.sort(key=lambda p: p.id, reverse=True)
        entry["recent"] = [p.admin_view() for p in recent[:INSTAGRAM_PREVIEW]]
    return {"handles": handles}


@router.get("/audit")
def audit(
    core: Core = Depends(get_core),
    before: Annotated[int | None, Query(ge=1, lt=MAX_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    entries = queries.audit_page(core.db, before=before, limit=limit)
    return {"entries": entries, "next": entries[-1]["id"] if len(entries) == limit else None}


@router.get("/extensions")
def extensions(core: Core = Depends(get_core)) -> dict[str, Any]:
    """Loaded extensions plus ids that only still exist in old photos."""
    result = [e.admin_view() | {"loaded": True} for e in core.extensions.values()]
    for ext_id in queries.extensions_with_photos(core.db):
        if ext_id not in core.extensions:
            result.append(
                {
                    "id": ext_id,
                    "title": ext_id,
                    "emoji": "📷",
                    "tagline": "",
                    "url": None,
                    "uploads": True,
                    "meta_labels": {},
                    "loaded": False,
                }
            )
    return {"extensions": result}


# ------------------------------------------------------------------- events


async def admin_event_stream(request: Request, core: Core) -> AsyncIterator[str]:
    """All bus events as SSE. Ends once the admin session is gone (logout,
    expiry, password change); the browser then reconnects, gets 401 and goes
    to the login page."""
    recheck = SESSION_RECHECK_SECONDS
    checked = time.monotonic()
    async with aclosing(sse_stream(request, core.bus)) as stream:
        async for chunk in stream:
            now = time.monotonic()
            if now - checked >= recheck:
                checked = now
                if await run_in_threadpool(admin_from_cookie, request, core) is None:
                    return
            yield chunk


@router.get("/events")
async def events(request: Request, core: Core = Depends(get_core)) -> StreamingResponse:
    return StreamingResponse(
        admin_event_stream(request, core),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
