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
    # required: leaving it out would skip the fingerprint-ban check
    fp: Fingerprint


class MeIn(BaseModel):
    """null or blank clears the handle."""

    instagram: str | None = Field(default=None, max_length=100)


# ----------------------------------------------------------------- responses


class GuestUser(BaseModel):
    """What the guest's own browser may see about itself (exactly these keys)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    instagram: str | None
    banned: bool
    uploads_paused: bool

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


class NeedsConsentOut(BaseModel):
    """Unknown device: show the join dialog."""

    state: Literal["needs_consent"]
    consent: ConsentInfo


class IdentifiedOut(BaseModel):
    """A known device. `uid_token` is also set as the `vb_uid` cookie."""

    state: Literal["ok", "banned"]
    user: GuestUser
    uploads_stopped: bool
    uid_token: str


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
