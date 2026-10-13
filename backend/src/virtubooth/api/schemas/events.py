"""The admin live stream (`GET /api/admin/events`, Server-Sent Events).

Each SSE message is `event: <type>`, `data: <JSON of the event's data>` and
`id: <epoch>-<n>`. `AdminEvent` describes one message as an object
`{type, id, data}`: the SSE fields, with `data` already parsed. The browser
sends the last id back as `Last-Event-ID` when it reconnects; missed events are
replayed, or a `stream.resync` event (no id) says "refetch everything".
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, RootModel

from .admin import AdminPhoto, AdminUser, PauseState, StopState

EventId = Annotated[str, Field(description="`<epoch>-<n>`: the SSE `id:` line.")]


# ----------------------------------------------------------------- payloads


class PhotoEventData(BaseModel):
    photo: AdminPhoto


class PhotoDeletedData(BaseModel):
    id: str
    photo: AdminPhoto | None = Field(description="The tombstone (`deleted: true`).")


class UserCreatedData(BaseModel):
    id: int
    name: str
    instagram: str | None
    banned: bool
    auto_banned: bool
    uploads_paused: bool


class UserBanData(BaseModel):
    user: AdminUser
    photos: list[AdminPhoto]


class FingerprintBannedData(BaseModel):
    fp_hash: str
    user_id: int


class FingerprintUnbannedData(BaseModel):
    fp_hash: str


class UploadsChangedData(BaseModel):
    users: list[AdminUser]
    paused: bool


class UploadStopData(BaseModel):
    upload_stop: StopState


class UploadPauseData(BaseModel):
    upload_pause: PauseState
    restored: list[int]
    kept: list[int]


class StreamResyncData(BaseModel):
    reason: Literal["gap", "restart"] = Field(
        description="gap: missed events are no longer kept; restart: the server restarted."
    )


# ------------------------------------------------------------------- events


class PhotoCreatedEvent(BaseModel):
    type: Literal["photo.created"]
    id: EventId
    data: PhotoEventData


class PhotoHiddenEvent(BaseModel):
    type: Literal["photo.hidden"]
    id: EventId
    data: PhotoEventData


class PhotoUnhiddenEvent(BaseModel):
    type: Literal["photo.unhidden"]
    id: EventId
    data: PhotoEventData


class PhotoDeletedEvent(BaseModel):
    type: Literal["photo.deleted"]
    id: EventId
    data: PhotoDeletedData


class UserCreatedEvent(BaseModel):
    type: Literal["user.created"]
    id: EventId
    data: UserCreatedData


class UserBannedEvent(BaseModel):
    type: Literal["user.banned"]
    id: EventId
    data: UserBanData


class UserUnbannedEvent(BaseModel):
    type: Literal["user.unbanned"]
    id: EventId
    data: UserBanData


class FingerprintBannedEvent(BaseModel):
    type: Literal["fingerprint.banned"]
    id: EventId
    data: FingerprintBannedData


class FingerprintUnbannedEvent(BaseModel):
    type: Literal["fingerprint.unbanned"]
    id: EventId
    data: FingerprintUnbannedData


class UploadsChangedEvent(BaseModel):
    type: Literal["user.uploads_changed"]
    id: EventId
    data: UploadsChangedData


class UploadStopEvent(BaseModel):
    type: Literal["settings.upload_stop"]
    id: EventId
    data: UploadStopData


class UploadPauseEvent(BaseModel):
    type: Literal["settings.upload_pause"]
    id: EventId
    data: UploadPauseData


class StreamResyncEvent(BaseModel):
    """Not from the bus: sent first on a reconnect the history can't serve."""

    type: Literal["stream.resync"]
    data: StreamResyncData


AnyAdminEvent = Annotated[
    PhotoCreatedEvent
    | PhotoHiddenEvent
    | PhotoUnhiddenEvent
    | PhotoDeletedEvent
    | UserCreatedEvent
    | UserBannedEvent
    | UserUnbannedEvent
    | FingerprintBannedEvent
    | FingerprintUnbannedEvent
    | UploadsChangedEvent
    | UploadStopEvent
    | UploadPauseEvent
    | StreamResyncEvent,
    Field(discriminator="type"),
]


class AdminEvent(RootModel[AnyAdminEvent]):
    """One message of the admin event stream, discriminated by `type`."""


ADMIN_EVENT_TYPES: tuple[str, ...] = (
    "photo.created",
    "photo.hidden",
    "photo.unhidden",
    "photo.deleted",
    "user.created",
    "user.banned",
    "user.unbanned",
    "fingerprint.banned",
    "fingerprint.unbanned",
    "user.uploads_changed",
    "settings.upload_stop",
    "settings.upload_pause",
)
