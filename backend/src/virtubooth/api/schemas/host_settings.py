"""Request and response models of the admin settings (`/api/admin/settings...`):
the event name, the admin password and the public address. Extensions keep their own settings
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


CheckStatus = Literal["ok", "unreachable", "mismatch", "auto", "unchecked"]


class AddressCheck(BaseModel):
    """Whether the public address reaches THIS server: it fetched
    `<address>/healthz?probe=<nonce>` and compared the answer's `probe_mac`."""

    status: CheckStatus = Field(
        description="ok: reaches this server; unreachable: no answer (DNS, refused, timeout, "
        "TLS); mismatch: something else answers (another server, a redirect, an error page); "
        "auto: no address set, the QR codes use the address the admin is open on; unchecked: "
        "not checked since the address changed."
    )
    url: str | None = Field(description="The address that was checked.")
    at: str | None = Field(description="When it was checked; null: never.")
    message: str = Field(description="German detail for the admin, e.g. „Zeitüberschreitung“.")


class PublicAddress(BaseModel):
    """The address QR codes, posters and the Live-Wall's code point to."""

    address: str | None = Field(description="Set in Allgemeines; null: not set.")
    effective: str | None = Field(
        description="What the codes use: `address`, else VB_PUBLIC_BASE_URL, else the "
        "origin this request came in on."
    )
    source: Literal["setting", "env", "auto"]
    check: AddressCheck


class PublicAddressIn(BaseModel):
    address: str | None = Field(
        max_length=300,
        description="http(s)://host[:port][/path], no query or fragment; null or blank: "
        "back to VB_PUBLIC_BASE_URL / automatic.",
    )


class AdminSettingsOut(BaseModel):
    event: EventSettings
    password: PasswordState
    public_address: PublicAddress


class PasswordChangeIn(BaseModel):
    current: str = Field(max_length=PASSWORD_MAX)
    new: str = Field(max_length=PASSWORD_MAX, description="At least 12 characters.")


class PasswordChangedOut(BaseModel):
    ok: Literal[True]
    sessions_ended: int = Field(description="Other admin sessions that were logged out.")
