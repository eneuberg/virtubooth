"""Guest identity: device recognition, the join dialog, Instagram handle.

There is no registration. A browser that scanned the party QR code calls
/api/identify on every page load. Unknown devices get the consent text back; once
the guest accepts it, /api/join creates a pseudonymous user and pins it to the
device with a signed cookie (plus a localStorage copy as a fallback). A browser
fingerprint is recorded as a moderation hint (see UsersRepo.sharing_fingerprint).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..api.schemas.guest import ConsentInfo, Fingerprint
from ..core import errors
from ..core.clock import now_iso
from ..db.database import Database
from ..domain.constants import AUTO_BAN_REASON
from ..domain.models import Photo, PhotoQuery, User, new_public_id, shown_name
from ..repositories.container import Repositories
from .events import AdminEvents

if TYPE_CHECKING:
    from ..runtime import Core

INSTAGRAM_MAX = 30
INSTAGRAM_RE = re.compile(rf"^[a-z0-9._]{{1,{INSTAGRAM_MAX}}}$")
MY_PHOTOS_MAX = 60
# the Live-Wall extension; while it is loaded, its photo analysis runs
WALL_EXTENSION = "wall"
# The join texts' paragraphs about the photo analysis. Changing them changes what
# guests agreed to: bump VB_CONSENT_VERSION when deploying (DEPLOY.md; security
# review 3, „Consent and privacy“). The night batch changed them (external AI):
# deploy it with a new VB_CONSENT_VERSION.
WALL_ANALYSIS_TEXT = (
    "Für die Live-Wall der Party werden Fotos automatisch auf dem Server ausgewertet: "
    "Gesichter und Hände zählen, Gesichtsausdruck und ungefähres Alter schätzen – nur zum "
    "Spaß, für Kategorien wie „Grinsekatzen“. Du kannst das für deine Fotos ausschalten."
)


# always in „Mehr dazu“, also while the host has no external AI switched on; it
# names the configured provider („Anthropic, USA“, „Mistral AI, EU“ or
# „DeutschlandGPT, Deutschland“); `photos=False` for a provider that only ever gets
# the recognised things as text (DeutschlandGPT: no photos)
def external_ai_text(provider: str = "Anthropic, USA", *, photos: bool = True) -> str:
    what = "Fotos und erkannte Dinge" if photos else "erkannte Dinge"
    return (
        f"Wenn der Gastgeber es einschaltet, können {what} (z. B. „Glas“, "
        f"„Hut“) zusätzlich von einem externen KI-Dienst ({provider}) ausgewertet werden – "
        "für lustige Kategorien auf der Live-Wall. Mit „Keine Weitergabe an externe KI“ "
        "schließt du deine Fotos davon aus; das kannst du jederzeit unter „Du“ ändern."
    )


EXTERNAL_AI_TEXT = external_ai_text()


# ------------------------------------------------------------ display names

DISPLAY_NAME_MIN = 2
DISPLAY_NAME_MAX = 24
RESERVED_NAMES = frozenset(
    {"admin", "host", "gastgeber", "moderator", "veranstalter", "virtubooth"}
)
_SPACES = re.compile(r"\s+")
# what two names may differ in and still count as the same name
_NAME_NOISE = re.compile(r"[\s._\-@#]+")
LENGTH_PROBLEM = "Der Name braucht 2 bis 24 Zeichen."
NAME_REFUSED = "Dieser Name geht leider nicht."
NAME_TAKEN = "Dieser Name ist schon vergeben."
# the admin guest's display name: a reserved word, so no other guest can have it
HOST_DISPLAY_NAME = "Gastgeber"


def name_key(name: str) -> str:
    """What two names are compared by: NFKC, case-folded, without spaces, „.“,
    „_“, „-“, „@“ and „#“ („Anna_B“ = „anna b“ = „@anna.b“)."""
    return _NAME_NOISE.sub("", unicodedata.normalize("NFKC", name).casefold())


def normalize_display_name(raw: str | None) -> str | None:
    """The name to store, or None for "back to the default" (null or blank).
    NFKC, trimmed, space runs collapsed; 2–24 characters; no control, format
    (bidi, zero-width), private-use or surrogate characters; no leading „@“
    (that is how Instagram names look). 400 `invalid_display_name`."""
    if raw is None:
        return None
    name = _SPACES.sub(" ", unicodedata.normalize("NFKC", raw)).strip()
    if not name:
        return None
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Co", "Cs") for ch in name):
        raise errors.bad_request(NAME_REFUSED, "invalid_display_name")
    if not DISPLAY_NAME_MIN <= len(name) <= DISPLAY_NAME_MAX:
        raise errors.bad_request(LENGTH_PROBLEM, "invalid_display_name")
    if name.startswith(("@", "＠")) or not any(ch.isalnum() for ch in name):
        raise errors.bad_request(NAME_REFUSED, "invalid_display_name")
    return name


# ---------------------------------------------------------------- external AI


def external_ai_active(repos: Repositories) -> bool:
    """Switched on, and something would actually be sent (the Live-Wall's LLM
    flags, `extensions/wall/llm/flags.py`): the join dialog shows the
    „Keine Weitergabe an externe KI“ switch only then."""
    from ..extensions.wall.llm.flags import external_ai_active as active

    return active(repos)


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
        return f"Instagram-Namen haben höchstens {INSTAGRAM_MAX} Zeichen, deiner hat {len(handle)}."
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
    code_id: int | None = None,
    analysis_opt_out: bool = False,
    ai_opt_out: bool = False,
) -> User:
    """A new identity. While the new-guest lock is on it starts paused.
    `code_id`: the QR code it joined through."""
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
            code_id=code_id,
            analysis_opt_out=analysis_opt_out,
            ai_opt_out=ai_opt_out,
        )
        user = repos.users.get(uid)
    assert user is not None
    return user


@dataclass(frozen=True)
class JoinResult:
    user: User
    created: bool
    instagram_kept: bool


@dataclass(frozen=True)
class HostGuestResult:
    """`switched`: the browser was signed in as another guest (`previous`)
    and now is the admin guest."""

    user: User
    created: bool
    previous: User | None

    @property
    def switched(self) -> bool:
        return self.previous is not None


class IdentityService:
    def __init__(self, core: Core, db: Database, repos: Repositories, events: AdminEvents) -> None:
        self.core = core
        self.db = db
        self.repos = repos
        self.events = events

    def consent_info(self) -> ConsentInfo:
        s = self.core.settings
        insta = f" ({s.instagram_account})" if s.instagram_account else ""
        name = self.core.services.host_settings.event_name()
        analysis = self.analysis_active()
        return ConsentInfo(
            version=s.consent_version,
            title=f"Willkommen bei {name}!",
            paragraphs=[
                "Kurz bevor’s losgeht: Wenn du hier Fotos machst, speichern wir sie "
                f"und dürfen sie auf Instagram{insta} posten.",
                "Damit wir Missbrauch verhindern können, erkennt die Seite dein Gerät "
                "wieder: eine anonyme Geräte-ID, kein Name. Bei Ärger können wir einzelne "
                "Geräte sperren.",
                "Die Gastgeber sehen zu jedem Gast eine kleine Statistik: wie viele Fotos du "
                "gemacht hast, wie lange die Seite bei dir offen war und über welchen QR-Code "
                "du gekommen bist.",
                *([WALL_ANALYSIS_TEXT] if analysis else []),
                external_ai_text(self.external_ai_provider(), photos=self.external_ai_photos()),
                "Wenn du das nicht möchtest, mach hier bitte keine Fotos.",
            ],
            instagram_prompt="Instagram-Name (freiwillig). Dann können wir dich markieren.",
            accept_label="Alles klar, los geht’s!",
            party_name=name,
            instagram_account=s.instagram_account,
            analysis=analysis,
            external_ai=self.external_ai(),
        )

    def analysis_active(self) -> bool:
        """The Live-Wall (and with it the photo analysis) is loaded."""
        return WALL_EXTENSION in self.core.extensions

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
        code_id: int | None = None,
        analysis_opt_out: bool = False,
        ai_opt_out: bool = False,
    ) -> JoinResult:
        """`code_id`: the QR code the browser scanned; stored on a new guest
        only (a device that joined already keeps its first code), like
        `analysis_opt_out` and `ai_opt_out` (the switches in the join sheet)."""
        if existing is not None:
            return self._rejoin(existing, instagram)
        if self.repos.app_settings.join_stop().enabled:
            raise errors.join_closed()
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
                code_id=code_id,
                analysis_opt_out=analysis_opt_out,
                ai_opt_out=ai_opt_out,
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
                with self.db.tx():
                    self.repos.users.set_instagram(user.id, handle)
                    self.events.user_instagram(user.id, handle)
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
        code_id: int | None = None,
        analysis_opt_out: bool = False,
        ai_opt_out: bool = False,
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
            code_id=code_id,
            analysis_opt_out=analysis_opt_out,
            ai_opt_out=ai_opt_out,
        )

    # ---------------------------------------------------------- admin guest

    def host_guest(
        self, current: User | None, *, ip: str, user_agent: str, actor: str
    ) -> HostGuestResult:
        """The admin guest („Als Gast teilnehmen“), created on first use: one
        per party (the admin password is shared, so there is no admin identity
        to tell hosts apart; `users_one_host` enforces it). It joins like a
        guest (the current consent version, display name „Gastgeber“, no
        Instagram) but through the admin session, not a QR code: no code, no
        new-guest lock, not refused by the join stop. `current`: the guest the
        calling browser is signed in as (replaced by the router). Audited."""
        with self.db.tx():
            user = self.repos.users.host()
            created = user is None
            at = now_iso()
            if user is None:
                uid = self.repos.users.create(
                    public_id=new_public_id(),
                    at=at,
                    consent_version=self.core.settings.consent_version,
                    instagram=None,
                    fp_hash=None,
                    fp_components={},
                    ip=ip,
                    user_agent=user_agent,
                    is_host=True,
                    display_name=HOST_DISPLAY_NAME,
                )
                user = self.repos.users.get(uid)
                assert user is not None
                self.events.user_created(user)
            previous = current if current is not None and current.id != user.id else None
            details: dict[str, Any] = {"created": created}
            if previous is not None:
                details["replaced"] = f"user:{previous.id}"
            self.repos.audit.log(actor, "host_guest.sign_in", f"user:{user.id}", details, at=at)
        return HostGuestResult(user, created, previous)

    def set_analysis_opt_out(self, user: User, opt_out: bool) -> User:
        """„Meine Fotos nicht automatisch auswerten“ on or off. Only the flag
        flips: what the analysis found stays as it is (frozen, PLAN-NIGHT N4);
        while it is on, the guest's photos are left out of every evaluation."""
        if self.repos.users.set_analysis_opt_out(user.id, opt_out):
            self.events.user_instagram(user.id, user.instagram)  # walls refresh the photos
        return self._reload(user)

    def set_ai_opt_out(self, user: User, opt_out: bool) -> User:
        """„Keine Weitergabe an externe KI“ on or off: checked live before every
        external call (detection, property poll, verdict)."""
        self.repos.users.set_ai_opt_out(user.id, opt_out)
        return self._reload(user)

    def external_ai(self) -> bool:
        return external_ai_active(self.repos)

    def external_ai_provider(self) -> str:
        """Who would get the data, for the privacy text („Anthropic, USA“)."""
        from ..extensions.wall.llm.flags import external_ai_provider

        return external_ai_provider(self.repos)

    def external_ai_photos(self) -> bool:
        """Whether the configured provider gets photos at all (not DeutschlandGPT)."""
        from ..extensions.wall.llm.flags import external_ai_photos

        return external_ai_photos(self.repos)

    # ------------------------------------------------------- display names

    def set_display_name(self, user: User, raw: str | None) -> User:
        """The guest's own display name (None or blank: back to the default).
        400 `invalid_display_name`, 409 `display_name_taken` (another guest's
        name or pseudonym, a reserved word or the event name)."""
        name = normalize_display_name(raw)
        if name is not None:
            self._check_free(user, name)
        with self.db.tx():
            if self.repos.users.set_display_name(user.id, name):
                self.repos.audit.log(
                    f"guest:{user.id}",
                    "user.display_name",
                    f"user:{user.id}",
                    {"display_name": name, "previous": user.display_name},
                    at=now_iso(),
                )
                # the same event a new handle sends: open walls rename the photos
                self.events.user_instagram(user.id, user.instagram)
        return self._reload(user)

    def reset_display_name(self, user_id: int, *, actor: str) -> tuple[User, bool]:
        """The admin takes a guest's display name back to the default."""
        user = self.repos.users.get(user_id)
        if user is None:
            raise errors.not_found("Gast nicht gefunden.")
        with self.db.tx():
            changed = self.repos.users.set_display_name(user_id, None)
            if changed:
                self.repos.audit.log(
                    actor,
                    "user.display_name_reset",
                    f"user:{user_id}",
                    {"previous": user.display_name},
                    at=now_iso(),
                )
                self.events.user_instagram(user_id, user.instagram)
        return self._reload(user), changed

    def _check_free(self, user: User, name: str) -> None:
        key = name_key(name)
        event = name_key(self.core.services.host_settings.event_name())
        # the admin guest may call itself „Gastgeber“ (its default); nobody else
        reserved = key in RESERVED_NAMES and not user.is_host
        if reserved or key == event or len(key) < DISPLAY_NAME_MIN:
            raise errors.bad_request(NAME_REFUSED, "invalid_display_name")
        for uid, pseudonym, instagram, display in self.repos.users.names():
            if uid == user.id:
                continue
            taken = {name_key(pseudonym), name_key(shown_name(display, instagram, pseudonym))}
            if instagram:
                taken.add(name_key(instagram))
            if key in taken:
                raise errors.ApiError(409, "display_name_taken", NAME_TAKEN)

    def _reload(self, user: User) -> User:
        updated = self.repos.users.get(user.id)
        assert updated is not None
        return updated

    # --------------------------------------------------------------- photos

    def delete_my_photo(self, user: User, public_id: str) -> None:
        """The guest deletes one of their own photos: the admin's delete path,
        audited as `guest:<id>`. 404 for someone else's, an unknown or an
        already deleted photo."""
        photo = self.repos.photos.get(public_id)
        if photo is None or photo.user_id != user.id or photo.deleted:
            raise errors.not_found("Foto nicht gefunden.")
        if not self.core.services.moderation.delete_photo(public_id, actor=f"guest:{user.id}"):
            raise errors.not_found("Foto nicht gefunden.")

    def set_instagram(self, user: User, raw: str | None) -> User:
        handle = normalize_instagram(raw)
        if handle != user.instagram:
            with self.db.tx():
                self.repos.users.set_instagram(user.id, handle)
                self.events.user_instagram(user.id, handle)
        updated = self.repos.users.get(user.id)
        assert updated is not None
        return updated

    def my_photos(self, user: User) -> list[Photo]:
        """The guest's own photos that are still up, newest first."""
        return self.repos.photos.list(
            PhotoQuery(user_id=user.id, hidden=False, limit=MY_PHOTOS_MAX)
        )
