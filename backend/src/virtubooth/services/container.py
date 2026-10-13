"""All services of one app, wired once in `Core`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .admin_auth import AdminAuthService
from .events import AdminEvents
from .exports import ExportService
from .identity import IdentityService
from .instagram import InstagramService
from .join_controls import JoinControlsService
from .moderation import ModerationService
from .presence import PresenceService
from .upload_controls import UploadControlsService
from .uploads import UploadService
from .views import AdminViews

if TYPE_CHECKING:
    from ..runtime import Core


@dataclass(frozen=True)
class Services:
    events: AdminEvents
    views: AdminViews
    identity: IdentityService
    uploads: UploadService
    moderation: ModerationService
    upload_controls: UploadControlsService
    admin_auth: AdminAuthService
    exports: ExportService
    instagram: InstagramService
    join_controls: JoinControlsService
    presence: PresenceService

    @classmethod
    def create(cls, core: Core) -> Services:
        db, repos = core.db, core.repos
        events = AdminEvents(db, core.bus)
        views = AdminViews(repos)
        return cls(
            events=events,
            views=views,
            identity=IdentityService(core, db, repos, events),
            uploads=UploadService(core, db, repos, events),
            moderation=ModerationService(db, repos, events, views),
            upload_controls=UploadControlsService(db, repos, events, views),
            admin_auth=AdminAuthService(core, db, repos),
            exports=ExportService(core, db, repos, events),
            instagram=InstagramService(db, repos, events),
            join_controls=JoinControlsService(db, repos, events),
            presence=PresenceService(core, repos),
        )
