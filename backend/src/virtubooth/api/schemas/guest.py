"""Request and response models of the guest API (`/api/...`)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...domain.constants import FP_HASH_PATTERN
from ...domain.models import Photo, User

_FP_MAX_KEYS = 32
MetaValue = str | int | float | bool | None


# ------------------------------------------------------------------ requests


class Fingerprint(BaseModel):
    """Device traits: a moderation hint, never an identity."""

    hash: str = Field(pattern=FP_HASH_PATTERN)
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
    # the localStorage copy of uid_token, for when the cookie is gone
    uid: str | None = Field(default=None, max_length=256)


class JoinIn(BaseModel):
    accept: Literal[True]
    version: str = Field(max_length=32)
    instagram: str | None = Field(default=None, max_length=100)
    # „Meine Fotos nicht automatisch auswerten“ (Live-Wall photo analysis)
    analysis_opt_out: bool = False
    # „Keine Weitergabe an externe KI“ (only offered while `ConsentInfo.external_ai`)
    ai_opt_out: bool = False
    # required: leaving it out would skip the fingerprint-ban check
    fp: Fingerprint


class MeIn(BaseModel):
    """Change what is sent; a field left out stays. null or blank clears it
    (`display_name`: back to the default). A body with neither field clears
    the handle (as before display names)."""

    instagram: str | None = Field(default=None, max_length=100)
    display_name: str | None = Field(
        default=None,
        max_length=100,
        description="2–24 characters after normalising (NFKC, spaces collapsed); no "
        "invisible or bidi characters, no leading „@“, not another guest's name.",
    )


class MeExternalAiIn(BaseModel):
    """„Keine Weitergabe an externe KI“: true = none of my photos, labels or my
    name ever go to an external AI service."""

    opt_out: bool


class MeAnalysisIn(BaseModel):
    """„Meine Fotos nicht automatisch auswerten“: true = the Live-Wall analysis
    looks only at image values (brightness, colour, sharpness) of my photos."""

    opt_out: bool


# ----------------------------------------------------------------- responses


class GuestUser(BaseModel):
    """What the guest's own browser may see about itself (exactly these keys)."""

    model_config = ConfigDict(from_attributes=True)

    name: str = Field(description="The pseudonym (internal; never changes).")
    display_name: str | None = Field(description="The name the guest chose; null: default.")
    shown_name: str = Field(
        description="How others see the guest: display name, else „@<instagram>“, else "
        "the pseudonym."
    )
    instagram: str | None
    banned: bool
    uploads_paused: bool
    analysis_opt_out: bool
    ai_opt_out: bool

    @classmethod
    def of(cls, user: User) -> GuestUser:
        return cls.model_validate(user)


class ConsentInfo(BaseModel):
    version: str
    title: str
    paragraphs: list[str]
    instagram_prompt: str
    accept_label: str
    party_name: str
    instagram_account: str
    # the Live-Wall's photo analysis runs: offer „Meine Fotos nicht automatisch auswerten“
    analysis: bool = False
    # the host has an external AI on: offer „Keine Weitergabe an externe KI“
    external_ai: bool = False


class NeedsConsentOut(BaseModel):
    """Unknown device: show the join dialog. `join_closed`: the host stopped
    new joins for a moment; show a calm "try again soon" instead of the button
    (a join would get 403 `join_closed`)."""

    state: Literal["needs_consent"]
    consent: ConsentInfo
    join_closed: bool = False


class IdentifiedOut(BaseModel):
    """A known device. `uid_token` is also set as the `vb_uid` cookie.
    `join_text`: the join texts of the current version, so a joined guest can read
    them again ("Was passiert mit meinen Fotos?")."""

    state: Literal["ok", "banned"]
    user: GuestUser
    uploads_stopped: bool
    uid_token: str
    join_text: ConsentInfo


IdentifyOut = Annotated[NeedsConsentOut | IdentifiedOut, Field(discriminator="state")]


class JoinOut(IdentifiedOut):
    """201 for a new guest, 200 when the device had joined already (second tab):
    then a different handle is not taken over (`instagram_kept`)."""

    already_joined: bool
    instagram_kept: bool


class MeOut(BaseModel):
    user: GuestUser


class GuestPhoto(BaseModel):
    """One of the guest's own photos. The image is at `url` (`thumb_url`: 400 px)."""

    id: str
    extension: str
    seq: int
    created_at: str
    width: int
    height: int
    url: str
    thumb_url: str

    @classmethod
    def of(cls, photo: Photo) -> GuestPhoto:
        return cls(
            id=photo.public_id,
            extension=photo.extension,
            seq=photo.seq,
            created_at=photo.created_at,
            width=photo.width,
            height=photo.height,
            url=photo.url,
            thumb_url=photo.thumb_url,
        )


class DeletedOut(BaseModel):
    ok: Literal[True]


class MyPhotosOut(BaseModel):
    """The caller's own visible photos, newest first (at most 60)."""

    photos: list[GuestPhoto]


class PublicExtension(BaseModel):
    id: str
    title: str
    emoji: str
    tagline: str
    url: str
    uploads: bool


class ExtensionsOut(BaseModel):
    party_name: str
    instagram_account: str
    extensions: list[PublicExtension]


class UploadOutBase(BaseModel):
    """The stored photo plus whatever the extension's `on_upload` returned
    (the per-extension fields are listed in the generated `UploadOut`)."""

    model_config = ConfigDict(extra="allow")

    photo: GuestPhoto


class HealthOut(BaseModel):
    ok: Literal[True]
    probe_mac: str | None = Field(
        default=None,
        description="With `?probe=<nonce>`: proof that this server answered (the admin's "
        "public-address check); otherwise null.",
    )


class HereIn(BaseModel):
    """The guest page's heartbeat: every minute while it is visible, and once
    with `visible: false` when it is hidden or closed."""

    visible: bool = True


class HereOut(BaseModel):
    ok: Literal[True]
