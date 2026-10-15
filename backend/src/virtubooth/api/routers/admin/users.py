"""Admin guests: list, detail, ban, unban, pause one guest's uploads, reset a
display name."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Query

from ....core import errors
from ....domain.constants import MAX_ID
from ...deps import AdminDep, CoreDep
from ...schemas.admin import (
    BanIn,
    BanOut,
    DisplayNameResetOut,
    FingerprintOut,
    UnbanIn,
    UnbanOut,
    UserDetailOut,
    UserListOut,
    UserRef,
    UserStatsOut,
    UserUploadsIn,
    UserUploadsOut,
)
from ._params import UserId, blank, parse_bool_filter

router = APIRouter()


@router.get("/users")
def list_users(
    core: CoreDep,
    search: Annotated[str | None, Query(max_length=100, description="name, handle, or #id")] = None,
    banned: Annotated[str | None, Query(max_length=10, description="all | true | false")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    paused: Annotated[str | None, Query(max_length=10, description="all | true | false")] = None,
    code: Annotated[
        int | None, Query(ge=1, lt=MAX_ID, description="only guests who joined via this QR code")
    ] = None,
) -> UserListOut:
    users = core.repos.users.list(
        banned=parse_bool_filter(banned),
        search=blank(search),
        limit=limit + 1,  # one more: is there a next page?
        offset=offset,
        paused=parse_bool_filter(paused),
        code_id=code,
    )
    page = users[:limit]
    return UserListOut(
        users=core.services.views.users(page),
        next_offset=offset + len(page) if len(users) > limit else None,
    )


@router.get("/users/{user_id}")
def get_user(user_id: UserId, core: CoreDep) -> UserDetailOut:
    """A guest with their fingerprints (and who else showed them), photos and
    photo statistics."""
    repos, views = core.repos, core.services.views
    user = repos.users.get(user_id)
    if user is None:
        raise errors.not_found("Gast nicht gefunden.")
    peers = repos.read_models.fingerprint_peers(user_id)
    return UserDetailOut(
        user=views.user(user),
        fingerprints=[
            FingerprintOut(
                fp_hash=f.fp_hash,
                first_seen=f.first_seen,
                last_seen=f.last_seen,
                shared_with=f.shared_with,
                banned=f.banned,
                current=f.fp_hash == user.fp_hash,
                users=[UserRef.of(r) for r in peers.get(f.fp_hash, [])],
            )
            for f in repos.users.fingerprints(user_id)
        ],
        sharing=[UserRef.of(u) for u in repos.users.sharing_fingerprint(user_id)],
        photos=views.user_photos(user_id),
        stats=UserStatsOut.model_validate(repos.read_models.user_stats(user_id)),
    )


@router.post("/users/{user_id}/ban")
def ban_user(user_id: UserId, body: BanIn, core: CoreDep, admin: AdminDep) -> BanOut:
    """Ban a guest: their photos are hidden (reason `ban`). `fingerprint`: ban
    their device too, so new identities on it start banned."""
    result = core.services.moderation.ban_user(
        user_id, reason=body.reason, fingerprint=body.fingerprint, actor=admin.actor
    )
    return BanOut(
        user=result.user,
        changed=result.changed,
        fingerprint_banned=result.fingerprint_banned,
        photos=result.photos,
    )


@router.post("/users/{user_id}/unban")
def unban_user(
    user_id: UserId,
    core: CoreDep,
    admin: AdminDep,
    body: Annotated[UnbanIn | None, Body()] = None,
) -> UnbanOut:
    """Unban a guest (only ban-hidden photos come back). `fingerprint`: lift
    their device bans too, releasing the identities those auto-banned."""
    result = core.services.moderation.unban_user(
        user_id, fingerprint=body is not None and body.fingerprint, actor=admin.actor
    )
    return UnbanOut(
        user=result.user,
        changed=result.changed,
        fingerprints_unbanned=result.fingerprints_unbanned,
        users_unbanned=result.users_unbanned,
        photos=result.photos,
    )


@router.delete("/users/{user_id}/display-name")
def reset_display_name(user_id: UserId, core: CoreDep, admin: AdminDep) -> DisplayNameResetOut:
    """Take the guest's display name back to the default (moderation)."""
    user, changed = core.services.identity.reset_display_name(user_id, actor=admin.actor)
    return DisplayNameResetOut(user=core.services.views.user(user), changed=changed)


@router.post("/users/{user_id}/uploads")
def set_user_uploads(
    user_id: UserId, body: UserUploadsIn, core: CoreDep, admin: AdminDep
) -> UserUploadsOut:
    """Pause or allow one guest's uploads (not a ban: photos stay up)."""
    user, changed = core.services.upload_controls.set_user_paused(
        user_id, body.paused, actor=admin.actor
    )
    return UserUploadsOut(user=user, changed=changed)
