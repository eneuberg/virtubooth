"""Guest identity: device recognition, the join dialog, Instagram handle.

There is no registration. A browser that scanned the party QR code calls
/api/identify on every page load. Unknown devices get the consent text back; once
the guest accepts it, /api/join creates a pseudonymous user and pins it to the
device with a signed cookie (plus a localStorage copy as a fallback). A browser
fingerprint is recorded as a moderation hint (see UsersRepo.sharing_fingerprint).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..api.schemas.guest import ConsentInfo, Fingerprint
from ..core import errors
from ..core.clock import now_iso
from ..db.database import Database
from ..domain.constants import AUTO_BAN_REASON
from ..domain.models import Photo, PhotoQuery, User, new_public_id
from ..repositories.container import Repositories
from .events import AdminEvents

if TYPE_CHECKING:
    from ..runtime import Core

INSTAGRAM_MAX = 30
INSTAGRAM_RE = re.compile(rf"^[a-z0-9._]{{1,{INSTAGRAM_MAX}}}$")
MY_PHOTOS_MAX = 60


def normalize_instagram(raw: str | None) -> str | None:
    """'@Name', 'name' or a profile link -> 'name'; None/blank -> None.
    Raises a 400 whose message says what exactly is wrong."""
    if raw is None:
        return None
    handle = raw.strip()
    if "instagram.com/" in handle:
        handle = handle.split("instagram.com/", 1)[1].split("/")[0].split("?")[0]
    handle = handle.lstrip("@").strip().lower()
    if not handle:
        return None
    if not INSTAGRAM_RE.match(handle) or ".." in handle:
        raise errors.bad_request(_instagram_problem(handle), "invalid_instagram")
    return handle


def _instagram_problem(handle: str) -> str:
    if len(handle) > INSTAGRAM_MAX:
        return (
            f"Instagram-Namen haben höchstens {INSTAGRAM_MAX} Zeichen, deiner hat {len(handle)}."
        )
    if any(c in "äöüß" for c in handle):
        return (
            "Instagram-Namen haben keine Umlaute und kein ß. "
            "Schau nochmal, wie deiner genau geschrieben wird."
        )
    if any(c.isalpha() and not c.isascii() for c in handle):
        return "Instagram-Namen haben keine Akzente (é, ñ, …), nur die Buchstaben a bis z."
    if any(c.isspace() for c in handle):
        return "Instagram-Namen haben keine Leerzeichen."
    if ".." in handle:
        return "Zwei Punkte hintereinander gibt es in Instagram-Namen nicht."
    return "In Instagram-Namen gehen nur Buchstaben (a bis z), Zahlen, Punkt und Unterstrich."


def create_user(
    db: Database,
    repos: Repositories,
    *,
    consent_version: str,
    instagram: str | None,
    fp_hash: str | None,
    fp_components: dict[str, Any],
    ip: str,
    user_agent: str,
    banned_reason: str | None = None,
) -> User:
    """A new identity. While the new-guest lock is on it starts paused."""
    with db.tx():
        # read in the same transaction: a guest joining while the lock is
        # lifted is either restored with the others or not paused at all
        lock = repos.app_settings.upload_lock()
        uid = repos.users.create(
            public_id=new_public_id(),
            at=now_iso(),
            consent_version=consent_version,
            instagram=instagram,
            fp_hash=fp_hash,
            fp_components=fp_components,
            ip=ip,
            user_agent=user_agent,
            banned_reason=banned_reason,
            lock_period=lock.period if lock.enabled else None,
        )
        user = repos.users.get(uid)
    assert user is not None
    return user


@dataclass(frozen=True)
class JoinResult:
    user: User
    created: bool
    instagram_kept: bool


class IdentityService:
    def __init__(self, core: Core, db: Database, repos: Repositories, events: AdminEvents) -> None:
        self.core = core
        self.db = db
        self.repos = repos
        self.events = events

    def consent_info(self) -> ConsentInfo:
        s = self.core.settings
        insta = f" ({s.instagram_account})" if s.instagram_account else ""
        return ConsentInfo(
            version=s.consent_version,
            title=f"Willkommen bei {s.party_name}! 🎉",
            paragraphs=[
                "Kurz bevor's losgeht: Wenn du hier Fotos machst, speichern wir sie "
                f"und dürfen sie auf Instagram{insta} posten.",
                "Damit wir Missbrauch verhindern können, erkennt die Seite dein Gerät "
                "wieder: eine anonyme Geräte-ID, kein Name. Bei Ärger können wir einzelne "
                "Geräte sperren.",
                "Wenn du das nicht möchtest, nutze die Fotobox bitte nicht.",
            ],
            instagram_prompt="Dein Instagram (freiwillig). Dann markieren wir dich!",
            accept_label="Alles klar, los geht's! 🍻",
            party_name=s.party_name,
            instagram_account=s.instagram_account,
        )

    def uploads_stopped(self) -> bool:
        return self.repos.app_settings.upload_stop().enabled

    def identify(
        self,
        user: User | None,
        *,
        uid_token: str | None,
        fp: Fingerprint | None,
        ip: str,
        user_agent: str,
    ) -> User | None:
        """The device's user (by cookie, else by the localStorage token) after
        noting that it was seen; None for an unknown device."""
        if user is None and uid_token:
            # cookie gone (cleared, ITP, new tab type) but localStorage survived
            public_id = self.core.signer.unsign("uid", uid_token)
            user = self.repos.users.get_by_public_id(public_id) if public_id else None
        if user is None:
            return None
        self.repos.users.touch(
            user.id,
            at=now_iso(),
            ip=ip,
            user_agent=user_agent,
            fp_hash=fp.hash if fp else None,
            fp_components=fp.components if fp else None,
        )
        return user

    def join(
        self,
        existing: User | None,
        *,
        version: str,
        instagram: str | None,
        fp: Fingerprint,
        ip: str,
        user_agent: str,
    ) -> JoinResult:
        if existing is not None:
            return self._rejoin(existing, instagram)
        if version != self.core.settings.consent_version:
            raise errors.ApiError(
                409, "consent_outdated", "Die Hinweise wurden gerade aktualisiert. Bitte neu laden."
            )
        handle = normalize_instagram(instagram)
        limiter = self.core.limits.new_user_ip
        if not limiter.hit(ip):
            raise errors.rate_limited(limiter.retry_after(ip))
        with self.db.tx():
            banned_reason = AUTO_BAN_REASON if self.repos.bans.is_banned(fp.hash) else None
            user = self.create_user(
                consent_version=version,
                instagram=handle,
                fp_hash=fp.hash,
                fp_components=fp.components,
                ip=ip,
                user_agent=user_agent,
                banned_reason=banned_reason,
            )
            self.events.user_created(user)
        return JoinResult(user, created=True, instagram_kept=False)

    def _rejoin(self, user: User, raw_instagram: str | None) -> JoinResult:
        """The device joined already, typically in a second tab that showed the
        join dialog before the first one was accepted. Keep the user; take the
        handle this dialog brought if the user has none yet. A different handle
        never replaces the stored one (that's what PATCH /api/me is for):
        `instagram_kept` tells the UI to say so."""
        kept = False
        handle = normalize_instagram(raw_instagram)
        if handle and handle != user.instagram and not user.banned:
            if user.instagram:
                kept = True
            else:
                self.repos.users.set_instagram(user.id, handle)
                user = self.repos.users.get(user.id) or user
        return JoinResult(user, created=False, instagram_kept=kept)

    def create_user(
        self,
        *,
        consent_version: str,
        instagram: str | None,
        fp_hash: str | None,
        fp_components: dict[str, Any],
        ip: str,
        user_agent: str,
        banned_reason: str | None = None,
    ) -> User:
        return create_user(
            self.db,
            self.repos,
            consent_version=consent_version,
            instagram=instagram,
            fp_hash=fp_hash,
            fp_components=fp_components,
            ip=ip,
            user_agent=user_agent,
            banned_reason=banned_reason,
        )

    def set_instagram(self, user: User, raw: str | None) -> User:
        self.repos.users.set_instagram(user.id, normalize_instagram(raw))
        updated = self.repos.users.get(user.id)
        assert updated is not None
        return updated

    def my_photos(self, user: User) -> list[Photo]:
        """The guest's own photos that are still up, newest first."""
        return self.repos.photos.list(PhotoQuery(user_id=user.id, hidden=False, limit=MY_PHOTOS_MAX))
