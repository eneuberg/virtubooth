"""Guest identity: device recognition, consent banner, Instagram handle.

There is no registration. A browser that scanned the party QR code calls
/api/identify on every page load. Unknown devices get the consent text back; once
the guest accepts it, /api/join creates a pseudonymous user and pins it to the
device with a signed cookie (plus a localStorage copy as a fallback). A browser
fingerprint is recorded as a moderation hint (see repo.users_sharing_fingerprint).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import errors
from .context import Core
from .deps import get_core, guest_from_cookie, require_access, require_guest
from .repo import User
from .security import GUEST_COOKIE_MAX_AGE, UID_COOKIE, client_ip, set_cookie

router = APIRouter(prefix="/api")

INSTAGRAM_MAX = 30
INSTAGRAM_RE = re.compile(rf"^[a-z0-9._]{{1,{INSTAGRAM_MAX}}}$")
_FP_MAX_KEYS = 32


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
            f"Instagram-Namen haben höchstens {INSTAGRAM_MAX} Zeichen, "
            f"deiner hat {len(handle)}."
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


class Fingerprint(BaseModel):
    hash: str = Field(pattern=r"^[0-9a-f]{16,64}$")
    components: dict[str, Any] = Field(default_factory=dict)

    @field_validator("components")
    @classmethod
    def _sanitize(cls, value: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, item in list(value.items())[:_FP_MAX_KEYS]:
            key = str(key)[:32]
            if isinstance(item, bool | int | float) or item is None:
                clean[key] = item
            else:
                clean[key] = str(item)[:200]
        return clean


class IdentifyIn(BaseModel):
    fp: Fingerprint | None = None
    uid: str | None = Field(default=None, max_length=256)


class ConsentIn(BaseModel):
    accept: Literal[True]
    version: str = Field(max_length=32)
    instagram: str | None = Field(default=None, max_length=100)
    # required: leaving it out would skip the fingerprint-ban check
    fp: Fingerprint


class MeUpdate(BaseModel):
    instagram: str | None = Field(default=None, max_length=100)


def consent_info(core: Core) -> dict[str, Any]:
    s = core.settings
    insta = f" ({s.instagram_account})" if s.instagram_account else ""
    return {
        "version": s.consent_version,
        "title": f"Willkommen bei {s.party_name}! 🎉",
        "paragraphs": [
            "Kurz bevor's losgeht: Wenn du hier Fotos machst, speichern wir sie "
            f"und dürfen sie auf Instagram{insta} posten.",
            "Damit wir Missbrauch verhindern können, erkennt die Seite dein Gerät "
            "wieder: eine anonyme Geräte-ID, kein Name. Bei Ärger können wir einzelne "
            "Geräte sperren.",
            "Wenn du das nicht möchtest, nutze die Fotobox bitte nicht.",
        ],
        "instagram_prompt": "Dein Instagram (freiwillig). Dann markieren wir dich!",
        "accept_label": "Alles klar, los geht's! 🍻",
        "party_name": s.party_name,
        "instagram_account": s.instagram_account,
    }


def _identified(
    request: Request,
    core: Core,
    user: User,
    *,
    status: int = 200,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    token = core.signer.sign("uid", user.public_id)
    response = JSONResponse(
        {
            "state": "banned" if user.banned else "ok",
            "user": user.guest_view(),
            "uid_token": token,
            **(extra or {}),
        },
        status_code=status,
    )
    set_cookie(response, request, core.settings, UID_COOKIE, token, max_age=GUEST_COOKIE_MAX_AGE)
    return response


@router.post("/identify", dependencies=[Depends(require_access)])
def identify(body: IdentifyIn, request: Request, core: Core = Depends(get_core)) -> JSONResponse:
    user = guest_from_cookie(request, core)
    if user is None and body.uid:
        # cookie gone (cleared, ITP, new tab type) but localStorage survived
        public_id = core.signer.unsign("uid", body.uid)
        user = core.repo.get_user_by_public_id(public_id) if public_id else None
    if user is None:
        return JSONResponse({"state": "needs_consent", "consent": consent_info(core)})
    core.repo.touch_user(
        user.id,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:300],
        fp_hash=body.fp.hash if body.fp else None,
        fp_components=body.fp.components if body.fp else None,
    )
    return _identified(request, core, user)


@router.post("/join", dependencies=[Depends(require_access)])
def consent(body: ConsentIn, request: Request, core: Core = Depends(get_core)) -> JSONResponse:
    existing = guest_from_cookie(request, core)
    if existing is not None:
        return _rejoined(request, core, existing, body.instagram)
    if body.version != core.settings.consent_version:
        raise errors.ApiError(
            409, "consent_outdated", "Die Hinweise wurden gerade aktualisiert. Bitte neu laden."
        )
    instagram = normalize_instagram(body.instagram)
    ip = client_ip(request)
    if not core.limits.new_user_ip.hit(ip):
        raise errors.rate_limited(core.limits.new_user_ip.retry_after(ip))

    fp_hash = body.fp.hash
    banned_reason = None
    if core.repo.is_fingerprint_banned(fp_hash):
        banned_reason = "Gerät gesperrt (Fingerprint)"
    user = core.repo.create_user(
        consent_version=body.version,
        instagram=instagram,
        fp_hash=fp_hash,
        fp_components=body.fp.components,
        ip=ip,
        user_agent=request.headers.get("user-agent", "")[:300],
        banned_reason=banned_reason,
    )
    core.bus.publish("user.created", {"id": user.id, "name": user.name, "banned": user.banned})
    return _identified(request, core, user, status=201, extra={"already_joined": False})


def _rejoined(request: Request, core: Core, user: User, raw_instagram: str | None) -> JSONResponse:
    """The device joined already, typically in a second tab that showed the join
    dialog before the first one was accepted. Keep the user; take the handle
    this dialog brought if the user has none yet. A different handle never
    replaces the stored one (that's what PATCH /api/me is for):
    `instagram_kept` tells the UI to say so."""
    extra: dict[str, Any] = {"already_joined": True, "instagram_kept": False}
    handle = normalize_instagram(raw_instagram)
    if handle and handle != user.instagram and not user.banned:
        if user.instagram:
            extra["instagram_kept"] = True
        else:
            core.repo.set_instagram(user.id, handle)
            user = core.repo.get_user(user.id) or user
    return _identified(request, core, user, extra=extra)


@router.patch("/me")
def update_me(
    body: MeUpdate, user: User = Depends(require_guest), core: Core = Depends(get_core)
) -> dict[str, Any]:
    core.repo.set_instagram(user.id, normalize_instagram(body.instagram))
    updated = core.repo.get_user(user.id)
    assert updated is not None
    return {"user": updated.guest_view()}
