"""Typed publishing of admin events.

Every event is published only after the transaction it reports on committed
(`Database.on_commit`; right away outside a transaction), in the order the
service emitted them.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..api.schemas.admin import AdminPhoto, AdminUser, PauseState, StopState
from ..api.schemas.codes import AdminCode
from ..api.schemas.events import (
    CodeChangedData,
    ExportDeletedData,
    ExportUpdatedData,
    ExtensionSettingsData,
    FingerprintBannedData,
    FingerprintUnbannedData,
    InstagramDoneData,
    JoinStopData,
    PhotoAnalyzedData,
    PhotoDeletedData,
    PhotoEventData,
    SettingsEventData,
    ThemeChangedData,
    UploadPauseData,
    UploadsChangedData,
    UploadStopData,
    UserBanData,
    UserCreatedData,
    UserInstagramData,
)
from ..api.schemas.exports import ExportJob
from ..api.schemas.host_settings import EventSettings
from ..core.events import EventBus
from ..db.database import Database
from ..domain.models import User


class AdminEvents:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus

    def _emit(self, type_: str, payload: BaseModel) -> None:
        data = payload.model_dump(mode="json")
        bus = self.bus
        self.db.on_commit(lambda: bus.publish(type_, data))

    def photo_created(self, photo: AdminPhoto) -> None:
        self._emit("photo.created", PhotoEventData(photo=photo))

    def photo_hidden(self, photo: AdminPhoto) -> None:
        self._emit("photo.hidden", PhotoEventData(photo=photo))

    def photo_unhidden(self, photo: AdminPhoto) -> None:
        self._emit("photo.unhidden", PhotoEventData(photo=photo))

    def photo_deleted(self, public_id: str, photo: AdminPhoto | None) -> None:
        self._emit("photo.deleted", PhotoDeletedData(id=public_id, photo=photo))

    def photo_analyzed(self, public_ids: list[str]) -> None:
        """The analysis of these photos changed (the Live Wall's poller)."""
        if public_ids:
            self._emit("photo.analyzed", PhotoAnalyzedData(ids=public_ids))

    def user_created(self, user: User) -> None:
        self._emit(
            "user.created",
            UserCreatedData(
                id=user.id,
                name=user.name,
                instagram=user.instagram,
                banned=user.banned,
                auto_banned=user.auto_banned,
                uploads_paused=user.uploads_paused,
            ),
        )

    def user_instagram(self, user_id: int, instagram: str | None) -> None:
        """A guest set, changed or removed their handle (internal: not sent to
        admin streams; the wall updates the guest's photos)."""
        self._emit("user.instagram", UserInstagramData(id=user_id, instagram=instagram))

    def user_banned(self, user: AdminUser, photos: list[AdminPhoto]) -> None:
        self._emit("user.banned", UserBanData(user=user, photos=photos))

    def user_unbanned(self, user: AdminUser, photos: list[AdminPhoto]) -> None:
        self._emit("user.unbanned", UserBanData(user=user, photos=photos))

    def fingerprint_banned(self, fp_hash: str, user_id: int) -> None:
        self._emit("fingerprint.banned", FingerprintBannedData(fp_hash=fp_hash, user_id=user_id))

    def fingerprint_unbanned(self, fp_hash: str) -> None:
        self._emit("fingerprint.unbanned", FingerprintUnbannedData(fp_hash=fp_hash))

    def uploads_changed(self, users: list[AdminUser], paused: bool) -> None:
        self._emit("user.uploads_changed", UploadsChangedData(users=users, paused=paused))

    def upload_stop(self, state: StopState) -> None:
        self._emit("settings.upload_stop", UploadStopData(upload_stop=state))

    def upload_pause(self, state: PauseState, restored: list[int], kept: list[int]) -> None:
        self._emit(
            "settings.upload_pause",
            UploadPauseData(upload_pause=state, restored=restored, kept=kept),
        )

    def join_stop(self, state: StopState) -> None:
        self._emit("settings.join_stop", JoinStopData(join_stop=state))

    def settings_event(self, state: EventSettings) -> None:
        self._emit("settings.event", SettingsEventData(event=state))

    def theme_changed(self) -> None:
        """The theme was saved or reset (internal: the wall re-sends its config)."""
        self._emit("theme.changed", ThemeChangedData())

    def extension_settings(self, ext_id: str) -> None:
        self._emit("extension.settings", ExtensionSettingsData(id=ext_id))

    def export_updated(self, job: ExportJob) -> None:
        self._emit("export.updated", ExportUpdatedData(job=job))

    def export_deleted(self, job_id: str) -> None:
        self._emit("export.deleted", ExportDeletedData(id=job_id))

    def instagram_done(self, handle: str, done: bool) -> None:
        self._emit("instagram.done", InstagramDoneData(handle=handle, done=done))

    def code_changed(self, code: AdminCode, change: str) -> None:
        self._emit(
            "code.changed",
            CodeChangedData.model_validate({"code": code, "change": change}),
        )
