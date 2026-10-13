"""Domain objects: plain frozen dataclasses, no persistence, no serialisation.

The API's response shapes live in `virtubooth.api.schemas`; they are built from
these objects.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any, Literal

from .constants import AUTO_BAN_REASON


def is_auto_banned(banned: bool, ban_reason: str | None) -> bool:
    """Banned only because the identity started on a banned fingerprint."""
    return bool(banned) and ban_reason == AUTO_BAN_REASON


def new_public_id() -> str:
    # never a leading "-": spreadsheets read "-abc" as a formula, and some CLIs as a flag
    while (public_id := secrets.token_urlsafe(12)).startswith("-"):
        pass
    return public_id


@dataclass(frozen=True)
class User:
    id: int
    public_id: str
    name: str
    created_at: str
    last_seen_at: str
    consent_at: str
    consent_version: str
    instagram: str | None
    fp_hash: str | None
    fp_components: dict[str, Any]
    first_ip: str
    last_ip: str
    user_agent: str
    banned_at: str | None
    ban_reason: str | None
    photo_count: int = 0
    # uploads paused (not a ban: photos stay visible, the guest can browse)
    uploads_paused_at: str | None = None
    uploads_paused_source: str | None = None  # PAUSE_ADMIN | PAUSE_NEW_GUEST_LOCK
    uploads_lock_period: int | None = None  # the new-guest lock period that paused them
    # online time (POST /api/here, see services/presence.py): the visible time
    # added up, the visits, and the last beat of the visit open right now
    online_seconds: int = 0
    online_sessions: int = 0
    online_at: str | None = None
    # the QR code it joined through (party_codes.id; None: unknown)
    code_id: int | None = None

    @property
    def banned(self) -> bool:
        return self.banned_at is not None

    @property
    def auto_banned(self) -> bool:
        return is_auto_banned(self.banned, self.ban_reason)

    @property
    def uploads_paused(self) -> bool:
        return self.uploads_paused_at is not None


@dataclass(frozen=True)
class UserRef:
    """A guest as other lists mention it."""

    id: int
    name: str
    instagram: str | None
    banned: bool
    ban_reason: str | None = None

    @property
    def auto_banned(self) -> bool:
        return is_auto_banned(self.banned, self.ban_reason)


@dataclass(frozen=True)
class Photo:
    id: int
    public_id: str
    extension: str
    user_id: int
    seq: int
    filename: str
    thumb_filename: str
    created_at: str
    width: int
    height: int
    bytes: int
    meta: dict[str, Any]
    hidden_at: str | None
    hidden_reason: str | None
    deleted_at: str | None
    user_name: str = ""
    user_instagram: str | None = None
    user_banned: bool = False
    user_uploads_paused: bool = False
    user_ban_reason: str | None = None

    @property
    def hidden(self) -> bool:
        return self.hidden_at is not None

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def url(self) -> str:
        return f"/media/{self.public_id}"

    @property
    def thumb_url(self) -> str:
        return f"/media/{self.public_id}?thumb=1"

    @property
    def user_auto_banned(self) -> bool:
        return is_auto_banned(self.user_banned, self.user_ban_reason)


@dataclass
class PhotoQuery:
    extension: str | None = None
    user_id: int | None = None
    # None = both, True = only hidden, False = only visible
    hidden: bool | None = None
    include_deleted: bool = False
    # pagination by internal id: newest first, pass the last id you saw
    before_id: int | None = None
    # for live views: everything newer than this id (returned newest first too)
    after_id: int | None = None
    limit: int = 50
    order: Literal["desc", "asc"] = "desc"  # newest first, or upload order


@dataclass(frozen=True)
class UserFingerprint:
    """A fingerprint a user showed, with how many others showed it too."""

    fp_hash: str
    first_seen: str
    last_seen: str
    shared_with: int
    banned: bool


@dataclass(frozen=True)
class FingerprintBan:
    fp_hash: str
    created_at: str
    reason: str
    source_user_id: int | None


@dataclass(frozen=True)
class DeviceBan:
    """A fingerprint ban as the admin lists it: who it was made over, who showed it."""

    fp_hash: str
    created_at: str
    reason: str
    source_user_id: int | None
    source_user_name: str | None
    users: list[UserRef] = field(default_factory=list)


@dataclass(frozen=True)
class AutoBanSource:
    """For an auto-banned identity: the fingerprint ban that hit it."""

    fp_hash: str
    source_user_id: int | None
    source_user_name: str | None


@dataclass(frozen=True)
class AdminSession:
    token_hash: str
    created_at: str
    expires_at: str
    pw_tag: str
    ip: str
    user_agent: str


@dataclass(frozen=True)
class AuditEntry:
    id: int
    at: str
    actor: str
    action: str
    target: str
    details: dict[str, Any]


@dataclass(frozen=True)
class UploadLock:
    """The new-guest lock. `period` counts lock periods; it is None while off."""

    enabled: bool
    since: str | None
    period: int | None
    by: str | None


@dataclass(frozen=True)
class UploadStop:
    enabled: bool
    since: str | None
    by: str | None


@dataclass(frozen=True)
class ExtensionCount:
    photos: int
    hidden: int


@dataclass(frozen=True)
class Stats:
    photos: int
    visible: int
    hidden: int
    deleted: int
    last_upload_at: str | None
    guests: int
    banned: int
    # guests (devices) that gave a handle, and the distinct handles: one
    # person with two phones is two guests but one handle
    instagram: int
    instagram_handles: int
    uploaders: int
    fingerprint_bans: int
    extensions: dict[str, ExtensionCount]


@dataclass(frozen=True)
class InstagramUser:
    id: int
    name: str
    banned: bool
    ban_reason: str | None
    photos: int

    @property
    def auto_banned(self) -> bool:
        return is_auto_banned(self.banned, self.ban_reason)


@dataclass
class InstagramHandle:
    handle: str
    users: list[InstagramUser] = field(default_factory=list)
    photos: int = 0
    visible: int = 0
    hidden: int = 0
    last_upload_at: str | None = None


@dataclass(frozen=True)
class ActivityCount:
    id: str
    photos: int


@dataclass(frozen=True)
class UserStats:
    """One guest's photos for the admin's user page. `photos` and `by_activity`
    count the ones not deleted; first/last include deleted ones (uploads)."""

    photos: int
    visible: int
    hidden: int
    deleted: int
    by_activity: list[ActivityCount]
    first_photo_at: str | None
    last_photo_at: str | None
