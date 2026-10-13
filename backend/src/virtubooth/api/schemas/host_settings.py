"""Request and response models of the admin settings (`/api/admin/settings...`):
the event name and the admin password. Extensions keep their own settings
models (e.g. the Fotobox filters in `extensions/booth`)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...core.passwords import MAX_LENGTH as PASSWORD_MAX


class EventSettings(BaseModel):
    """The event name everywhere guests see it (Start, join sheet title, the
    Fotobox's party frame, posters, archive manifest)."""

    name: str = Field(description="The name in use: the host's, else `default_name`.")
    default_name: str = Field(description="VB_PARTY_NAME (default „Party“).")
    custom: bool = Field(description="The host set a name in the admin.")
    updated_at: str | None = Field(description="When the host set it; null: never.")
    by: str | None = Field(description="Who set it (audit actor); null: never.")


class EventSettingsOut(EventSettings):
    changed: bool


class EventNameIn(BaseModel):
    name: str | None = Field(
        max_length=200,
        description="1–60 characters after normalising (whitespace runs become one "
        "space); null or blank: back to VB_PARTY_NAME.",
    )


class PasswordState(BaseModel):
    source: Literal["env", "admin"] = Field(
        description="env: VB_ADMIN_PASSWORD applies; admin: the password set in the "
        "admin (or by `virtubooth reset-admin-password`), VB_ADMIN_PASSWORD no longer "
        "logs in."
    )
    changed_at: str | None = Field(description="When it was set; null for env.")


class AdminSettingsOut(BaseModel):
    event: EventSettings
    password: PasswordState


class PasswordChangeIn(BaseModel):
    current: str = Field(max_length=PASSWORD_MAX)
    new: str = Field(max_length=PASSWORD_MAX, description="At least 12 characters.")


class PasswordChangedOut(BaseModel):
    ok: Literal[True]
    sessions_ended: int = Field(description="Other admin sessions that were logged out.")
