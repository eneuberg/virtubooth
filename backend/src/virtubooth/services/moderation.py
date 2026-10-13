"""Moderation: hide, unhide and delete photos; ban and unban guests and devices.

Each operation is one transaction: the change, its audit entry and (via the
on-commit hook) its events. Photo files are removed only after the deletion
committed.

Lifting a fingerprint ban also unbans the identities that started banned only
because they joined showing it ("auto-banned"): one `user.unbanned` each.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..api.schemas.admin import AdminPhoto, AdminUser, UserRef
from ..core import errors
from ..core.clock import now_iso
from ..db.database import Database
from ..domain.constants import HIDDEN_BY_ADMIN
from ..domain.models import Photo, User
from ..repositories.container import Repositories
from .events import AdminEvents
from .views import AdminViews


@dataclass(frozen=True)
class PhotoChange:
    changed: bool
    photo: Photo | None


@dataclass(frozen=True)
class BulkResult:
    action: str
    changed: list[str]
    unchanged: list[str]
    missing: list[str]


@dataclass(frozen=True)
class BanResult:
    user: AdminUser
    changed: bool
    fingerprint_banned: bool
    photos: list[AdminPhoto]


@dataclass(frozen=True)
class UnbanResult:
    user: AdminUser
    changed: bool
    fingerprints_unbanned: list[str]
    users_unbanned: list[UserRef]
    photos: list[AdminPhoto]


class ModerationService:
    def __init__(
        self, db: Database, repos: Repositories, events: AdminEvents, views: AdminViews
    ) -> None:
        self.db = db
        self.repos = repos
        self.events = events
        self.views = views

    # ------------------------------------------------------------- photos

    def hide_photo(self, public_id: str, *, actor: str, reason: str = HIDDEN_BY_ADMIN) -> PhotoChange:
        with self.db.tx():
            changed = self.repos.photos.hide(public_id, at=now_iso(), reason=reason)
            photo = self.repos.photos.get(public_id)
            if changed:
                self.repos.audit.log(actor, "photo.hide", f"photo:{public_id}", at=now_iso())
                if photo is not None:
                    self.events.photo_hidden(AdminPhoto.of(photo))
        return PhotoChange(changed, photo)

    def unhide_photo(self, public_id: str, *, actor: str) -> PhotoChange:
        """Also brings back a photo a ban hid (the owner stays banned)."""
        with self.db.tx():
            changed = self.repos.photos.unhide(public_id)
            photo = self.repos.photos.get(public_id)
            if changed:
                self.repos.audit.log(actor, "photo.unhide", f"photo:{public_id}", at=now_iso())
                if photo is not None:
                    self.events.photo_unhidden(AdminPhoto.of(photo))
        return PhotoChange(changed, photo)

    def delete_photo(self, public_id: str, *, actor: str) -> bool:
        """Remove the files for good. The row stays as a tombstone so sequence
        numbers are never reused. False if it doesn't exist (or is gone)."""
        with self.db.tx():
            files = self.repos.photos.mark_deleted(public_id, at=now_iso())
            if files is None:
                return False
            self.repos.audit.log(actor, "photo.delete", f"photo:{public_id}", at=now_iso())
            tombstone = self.repos.photos.get(public_id, include_deleted=True)
            self.db.on_commit(lambda: _unlink(files))
            self.events.photo_deleted(public_id, AdminPhoto.of(tombstone) if tombstone else None)
        return True

    def bulk(self, ids: Sequence[str], action: str, *, actor: str) -> BulkResult:
        """One change (audit entry, event) per photo; de-duplicated, order kept."""
        changed: list[str] = []
        unchanged: list[str] = []
        missing: list[str] = []
        for public_id in dict.fromkeys(ids):
            if self.repos.photos.get(public_id) is None:
                missing.append(public_id)
                continue
            if action == "delete":
                ok = self.delete_photo(public_id, actor=actor)
            elif action == "hide":
                ok = self.hide_photo(public_id, actor=actor).changed
            else:
                ok = self.unhide_photo(public_id, actor=actor).changed
            (changed if ok else unchanged).append(public_id)
        return BulkResult(action, changed, unchanged, missing)

    # ---------------------------------------------------------------- bans

    def _user_or_404(self, user_id: int) -> User:
        user = self.repos.users.get(user_id)
        if user is None:
            raise errors.not_found("Gast nicht gefunden.")
        return user

    def ban_user(
        self, user_id: int, *, reason: str = "", fingerprint: bool = False, actor: str
    ) -> BanResult:
        """Ban a guest: their visible photos are hidden (reason 'ban'). With
        `fingerprint`, their current device fingerprint is banned too, so new
        identities showing it start banned."""
        user = self._user_or_404(user_id)
        if fingerprint and not user.fp_hash:
            raise errors.bad_request(
                "Für diesen Gast ist kein Fingerprint bekannt.", "no_fingerprint"
            )
        reason = " ".join(reason.split())
        with self.db.tx():
            at = now_iso()
            changed = self.repos.users.ban(user_id, at=at, reason=reason)
            if changed:
                self.repos.photos.hide_for_ban(user_id, at=at)
                self.repos.audit.log(actor, "user.ban", f"user:{user_id}", {"reason": reason}, at=at)
            fp_banned = False
            if fingerprint and user.fp_hash:
                fp_banned = self._ban_fingerprint(user.fp_hash, reason, actor, user_id)
                if fp_banned:
                    self.events.fingerprint_banned(user.fp_hash, user_id)
            view = self.views.user(self._user_or_404(user_id))
            photos = self.views.user_photos(user_id)
            if changed:
                self.events.user_banned(view, photos)
        return BanResult(view, changed, fp_banned, photos)

    def unban_user(self, user_id: int, *, fingerprint: bool = False, actor: str) -> UnbanResult:
        """Unban a guest: only the photos the ban hid come back. With
        `fingerprint`, every banned fingerprint of the guest is lifted too, and
        with it the identities it auto-banned."""
        self._user_or_404(user_id)
        with self.db.tx():
            changed = self._unban(user_id, actor)
            lifted: list[str] = []
            if fingerprint:
                for f in self.repos.users.fingerprints(user_id):
                    if f.banned and self._unban_fingerprint(f.fp_hash, actor):
                        lifted.append(f.fp_hash)
                        self.events.fingerprint_unbanned(f.fp_hash)
            view = self.views.user(self._user_or_404(user_id))
            photos = self.views.user_photos(user_id)
            if changed:
                self.events.user_unbanned(view, photos)
            released = self._release_auto_banned(lifted, actor)
        return UnbanResult(view, changed, lifted, released, photos)

    def lift_device_ban(self, fp_hash: str, *, actor: str) -> list[UserRef]:
        """Delete a fingerprint ban; returns the auto-banned guests released with it."""
        with self.db.tx():
            if not self._unban_fingerprint(fp_hash, actor):
                raise errors.not_found("Diese Fingerprint-Sperre gibt es nicht.")
            self.events.fingerprint_unbanned(fp_hash)
            return self._release_auto_banned([fp_hash], actor)

    def ban_fingerprint(
        self, fp_hash: str, *, reason: str, actor: str, source_user_id: int | None = None
    ) -> bool:
        """Ban a device fingerprint on its own (the admin API bans one through
        a guest, see `ban_user`)."""
        with self.db.tx():
            banned = self._ban_fingerprint(fp_hash, reason, actor, source_user_id)
            if banned and source_user_id is not None:
                self.events.fingerprint_banned(fp_hash, source_user_id)
        return banned

    # ------------------------------------------------------------ helpers

    def _unban(self, user_id: int, actor: str) -> bool:
        if not self.repos.users.unban(user_id):
            return False
        self.repos.photos.restore_after_ban(user_id)
        self.repos.audit.log(actor, "user.unban", f"user:{user_id}", at=now_iso())
        return True

    def _ban_fingerprint(
        self, fp_hash: str, reason: str, actor: str, source_user_id: int | None
    ) -> bool:
        at = now_iso()
        if not self.repos.bans.add(fp_hash, at=at, reason=reason, source_user_id=source_user_id):
            return False
        self.repos.audit.log(actor, "fingerprint.ban", f"fp:{fp_hash[:16]}", {"reason": reason}, at=at)
        return True

    def _unban_fingerprint(self, fp_hash: str, actor: str) -> bool:
        if not self.repos.bans.remove(fp_hash):
            return False
        self.repos.audit.log(actor, "fingerprint.unban", f"fp:{fp_hash[:16]}", at=now_iso())
        return True

    def _release_auto_banned(self, fp_hashes: list[str], actor: str) -> list[UserRef]:
        """After fingerprint bans were lifted (same transaction): unban the
        identities that were only banned because they joined showing one of
        them (same phone model, maybe not the same person)."""
        released: list[UserRef] = []
        for uid in self.repos.read_models.auto_banned_users(fp_hashes):
            if not self._unban(uid, actor):
                continue
            user = self._user_or_404(uid)
            self.events.user_unbanned(self.views.user(user), self.views.user_photos(uid))
            released.append(UserRef.of(user))
        return released


def _unlink(files: list[Path]) -> None:
    for path in files:
        path.unlink(missing_ok=True)
