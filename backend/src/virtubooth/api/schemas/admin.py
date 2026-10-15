"""Request and response models of the admin API (`/api/admin/...`).

User references carry `auto_banned` everywhere: true when the guest is banned
only because it joined showing a banned fingerprint (it may just own the same
phone model).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ...domain import models as m
from ...domain.constants import PHOTO_ID_PATTERN
from ...domain.overview import is_online
from .guest import MetaValue

BULK_MAX = 200
PhotoIdItem = Annotated[str, StringConstraints(pattern=PHOTO_ID_PATTERN)]
HiddenReason = Literal["admin", "ban"]
PauseSource = Literal["admin", "new_guest_lock"]


# -------------------------------------------------------------------- auth


class LoginIn(BaseModel):
    password: str = Field(max_length=256)


class OkOut(BaseModel):
    ok: Literal[True]


class SessionOut(BaseModel):
    authenticated: bool


# ------------------------------------------------------------------ photos


class PhotoUser(BaseModel):
    """The guest who took a photo."""

    id: int
    name: str
    instagram: str | None
    banned: bool
    auto_banned: bool
    uploads_paused: bool


class AdminPhoto(BaseModel):
    id: str = Field(description="Public photo id (also the cursor for paging).")
    extension: str
    seq: int = Field(description="Per-extension number, never reused.")
    created_at: str
    width: int
    height: int
    bytes: int
    meta: dict[str, MetaValue]
    hidden: bool
    hidden_at: str | None
    hidden_reason: HiddenReason | None
    deleted: bool
    url: str
    thumb_url: str
    user: PhotoUser

    @classmethod
    def of(cls, p: m.Photo) -> AdminPhoto:
        return cls(
            id=p.public_id,
            extension=p.extension,
            seq=p.seq,
            created_at=p.created_at,
            width=p.width,
            height=p.height,
            bytes=p.bytes,
            meta=p.meta,
            hidden=p.hidden,
            hidden_at=p.hidden_at,
            hidden_reason=cast(HiddenReason | None, p.hidden_reason),
            deleted=p.deleted,
            url=p.url,
            thumb_url=p.thumb_url,
            user=PhotoUser(
                id=p.user_id,
                name=p.user_name,
                instagram=p.user_instagram,
                banned=p.user_banned,
                auto_banned=p.user_auto_banned,
                uploads_paused=p.user_uploads_paused,
            ),
        )


class PhotoListOut(BaseModel):
    """Newest first. `next`: pass as `before` for the next page (null: no more).
    `total` (matching photos) only on the first page (no cursor)."""

    photos: list[AdminPhoto]
    next: str | None
    total: int | None = None


class PhotoOut(BaseModel):
    photo: AdminPhoto


class PhotoChangeOut(BaseModel):
    photo: AdminPhoto
    changed: bool


class DeletePhotoOut(BaseModel):
    ok: Literal[True]
    id: str


class BulkIn(BaseModel):
    ids: list[PhotoIdItem] = Field(min_length=1, max_length=BULK_MAX)
    action: Literal["hide", "unhide", "delete"]


class BulkOut(BaseModel):
    action: Literal["hide", "unhide", "delete"]
    changed: list[str]
    unchanged: list[str]
    missing: list[str]


# ------------------------------------------------------------------- users


class UserRef(BaseModel):
    """A guest as other lists mention it."""

    id: int
    name: str
    instagram: str | None
    banned: bool
    auto_banned: bool

    @classmethod
    def of(cls, ref: m.UserRef | m.User) -> UserRef:
        return cls(
            id=ref.id,
            name=ref.name,
            instagram=ref.instagram,
            banned=ref.banned,
            auto_banned=ref.auto_banned,
        )


class AutoBan(BaseModel):
    """The fingerprint ban an auto-banned guest joined on (null once lifted)."""

    model_config = ConfigDict(from_attributes=True)

    fp_hash: str
    source_user_id: int | None
    source_user_name: str | None


class CodeRef(BaseModel):
    """The QR code a guest joined through (see /api/admin/codes)."""

    id: int = Field(description="The code's number.")
    name: str = Field(description="„<animal> <id>“, e.g. „Gorilla 2“.")
    active: bool = Field(description="False: the code was deleted (revoked) since.")


class AdminUser(BaseModel):
    """Everything about a guest. The same shape in every response and event."""

    id: int
    name: str = Field(description="The pseudonym (internal name, never changes).")
    display_name: str | None = Field(description="The name the guest chose; null: default.")
    shown_name: str = Field(
        description="How other guests see them: display name, else „@<instagram>“, else "
        "the pseudonym."
    )
    instagram: str | None
    analysis_opt_out: bool = Field(description="„Gast möchte keine Auswertung“.")
    ai_opt_out: bool = Field(description="„Keine externe KI“.")
    created_at: str
    last_seen_at: str
    consent_at: str
    consent_version: str
    fp_hash: str | None
    fp_components: dict[str, Any]
    first_ip: str
    last_ip: str
    user_agent: str
    banned: bool
    banned_at: str | None
    ban_reason: str | None
    photo_count: int = Field(description="Non-deleted photos.")
    uploads_paused: bool
    uploads_paused_at: str | None
    uploads_paused_source: PauseSource | None
    uploads_lock_period: int | None
    auto_banned: bool
    auto_ban: AutoBan | None
    online_seconds: int = Field(description="Visible time added up, seconds.")
    online_sessions: int = Field(description="Visits: a new one starts after 150 s without a beat.")
    online_now: bool = Field(
        description="The page is open and visible right now (a beat within 150 s)."
    )
    code: CodeRef | None = Field(description="The QR code it joined through; null: unknown.")

    @classmethod
    def of(
        cls, u: m.User, auto_ban: m.AutoBanSource | None, code: CodeRef | None = None
    ) -> AdminUser:
        return cls(
            id=u.id,
            name=u.name,
            display_name=u.display_name,
            shown_name=u.shown_name,
            instagram=u.instagram,
            analysis_opt_out=u.analysis_opt_out,
            ai_opt_out=u.ai_opt_out,
            created_at=u.created_at,
            last_seen_at=u.last_seen_at,
            consent_at=u.consent_at,
            consent_version=u.consent_version,
            fp_hash=u.fp_hash,
            fp_components=u.fp_components,
            first_ip=u.first_ip,
            last_ip=u.last_ip,
            user_agent=u.user_agent,
            banned=u.banned,
            banned_at=u.banned_at,
            ban_reason=u.ban_reason,
            photo_count=u.photo_count,
            uploads_paused=u.uploads_paused,
            uploads_paused_at=u.uploads_paused_at,
            uploads_paused_source=cast(PauseSource | None, u.uploads_paused_source),
            uploads_lock_period=u.uploads_lock_period,
            auto_banned=u.auto_banned,
            auto_ban=AutoBan.model_validate(auto_ban) if auto_ban and u.auto_banned else None,
            online_seconds=u.online_seconds,
            online_sessions=u.online_sessions,
            online_now=is_online(u.online_at),
            code=code,
        )


class UserListOut(BaseModel):
    """Newest first. `next_offset`: pass as `offset` for the next page (null: no more)."""

    users: list[AdminUser]
    next_offset: int | None


class FingerprintOut(BaseModel):
    fp_hash: str
    first_seen: str
    last_seen: str
    shared_with: int = Field(description="How many other guests showed it.")
    banned: bool
    current: bool = Field(description="The one the guest showed last.")
    users: list[UserRef]


class ActivityCountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="The activity (extension) id.")
    photos: int = Field(description="Non-deleted photos.")


class UserStatsOut(BaseModel):
    """A guest's photos at a glance (the user page's „Statistik“)."""

    model_config = ConfigDict(from_attributes=True)

    photos: int = Field(description="Non-deleted photos.")
    visible: int
    hidden: int
    deleted: int
    by_activity: list[ActivityCountOut] = Field(description="Non-deleted photos, most first.")
    first_photo_at: str | None = Field(description="First upload (deleted ones included).")
    last_photo_at: str | None = Field(description="Last upload (deleted ones included).")


class UserDetailOut(BaseModel):
    user: AdminUser
    fingerprints: list[FingerprintOut]
    sharing: list[UserRef] = Field(description="Guests that showed any of these fingerprints.")
    photos: list[AdminPhoto] = Field(description="Newest first, at most 1000.")
    stats: UserStatsOut


class BanIn(BaseModel):
    reason: str = Field(default="", max_length=200)
    # also ban the device fingerprint: new identities showing it start banned
    fingerprint: bool = False


class UnbanIn(BaseModel):
    # also lift the bans on every fingerprint this guest showed (and with them
    # the bans of other identities that only started banned because of them)
    fingerprint: bool = False


class DisplayNameResetOut(BaseModel):
    user: AdminUser
    changed: bool


class BanOut(BaseModel):
    user: AdminUser
    changed: bool
    fingerprint_banned: bool
    photos: list[AdminPhoto]


class UnbanOut(BaseModel):
    user: AdminUser
    changed: bool
    fingerprints_unbanned: list[str]
    users_unbanned: list[UserRef] = Field(description="Auto-banned guests released too.")
    photos: list[AdminPhoto]


class UserUploadsIn(BaseModel):
    paused: bool


class UserUploadsOut(BaseModel):
    user: AdminUser
    changed: bool


# --------------------------------------------------------------- device bans


class DeviceBanOut(BaseModel):
    fp_hash: str
    created_at: str
    reason: str
    source_user_id: int | None
    source_user_name: str | None
    users: list[UserRef]

    @classmethod
    def of(cls, ban: m.DeviceBan) -> DeviceBanOut:
        return cls(
            fp_hash=ban.fp_hash,
            created_at=ban.created_at,
            reason=ban.reason,
            source_user_id=ban.source_user_id,
            source_user_name=ban.source_user_name,
            users=[UserRef.of(u) for u in ban.users],
        )


class DeviceBansOut(BaseModel):
    bans: list[DeviceBanOut] = Field(description="Newest first.")


class DeviceUnbanOut(BaseModel):
    ok: Literal[True]
    fp_hash: str
    users_unbanned: list[UserRef]


# ------------------------------------------------------------------ overview


class ExtensionCountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    photos: int
    hidden: int


class StatsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    photos: int
    visible: int
    hidden: int
    deleted: int
    last_upload_at: str | None
    guests: int
    banned: int
    instagram: int = Field(description="Guests (devices) that gave a handle.")
    instagram_handles: int = Field(description="Distinct handles.")
    uploaders: int
    fingerprint_bans: int
    extensions: dict[str, ExtensionCountOut]


class InstagramUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    banned: bool
    auto_banned: bool
    photos: int


class InstagramHandleOut(BaseModel):
    handle: str
    users: list[InstagramUserOut]
    photos: int
    visible: int
    hidden: int
    last_upload_at: str | None
    recent: list[AdminPhoto] = Field(description="Up to 8 visible photos, newest first.")
    done: bool = Field(description="Marked „Erledigt“ (posted and tagged) on the board.")


class InstagramOut(BaseModel):
    """Most active handles first."""

    handles: list[InstagramHandleOut]


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: str
    actor: str
    action: str
    target: str
    details: dict[str, Any]


class AuditOut(BaseModel):
    """Newest first. `next`: pass as `before` for the next page (null: no more)."""

    entries: list[AuditEntryOut]
    next: int | None


class AdminExtension(BaseModel):
    id: str
    title: str
    emoji: str
    tagline: str
    url: str | None
    uploads: bool
    meta_labels: dict[str, str]
    loaded: bool = Field(description="False: only old photos still use this id.")


class AdminExtensionsOut(BaseModel):
    extensions: list[AdminExtension]


# ------------------------------------------------------------ upload controls


class StopState(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    since: str | None
    by: str | None


class StopIn(BaseModel):
    enabled: bool


class StopOut(StopState):
    changed: bool


class PauseState(BaseModel):
    """The new-guest lock. `period` is null while it is off; `affected`: guests
    this period paused and still paused by it."""

    enabled: bool
    since: str | None
    period: int | None
    by: str | None
    affected: int
    paused_total: int


class PauseIn(BaseModel):
    enabled: bool
    # turning it off: True = unpause the guests this pause period paused,
    # False = they stay paused. Required then, so nobody picks by accident.
    restore: bool | None = None


class PauseOut(PauseState):
    changed: bool
    restored: int
    kept: int
