"""All services of one app, wired once in `Core`."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .admin_auth import AdminAuthService
from .codes import CodesService
from .events import AdminEvents
from .exports import ExportService
from .host_settings import HostSettingsService
from .identity import IdentityService
from .instagram import InstagramService
from .join_controls import JoinControlsService
from .moderation import ModerationService
from .posters import PosterService
from .presence import PresenceService
from .theme import ThemeService
from .upload_controls import UploadControlsService
from .uploads import UploadService
from .views import AdminViews

if TYPE_CHECKING:
    from pathlib import Path

    from ..runtime import Core


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Services:
    events: AdminEvents
    views: AdminViews
    identity: IdentityService
    codes: CodesService
    uploads: UploadService
    moderation: ModerationService
    upload_controls: UploadControlsService
    admin_auth: AdminAuthService
    exports: ExportService
    host_settings: HostSettingsService
    instagram: InstagramService
    join_controls: JoinControlsService
    posters: PosterService
    presence: PresenceService
    theme: ThemeService

    @classmethod
    def create(cls, core: Core) -> Services:
        db, repos = core.db, core.repos
        events = AdminEvents(db, core.bus)
        views = AdminViews(repos)
        return cls(
            events=events,
            views=views,
            identity=IdentityService(core, db, repos, events),
            codes=CodesService(core, db, repos, events),
            uploads=UploadService(core, db, repos, events),
            moderation=ModerationService(
                db, repos, events, views, derived_files=_derived_files(core)
            ),
            upload_controls=UploadControlsService(db, repos, events, views),
            admin_auth=AdminAuthService(core, db, repos),
            exports=ExportService(core, db, repos, events),
            host_settings=HostSettingsService(core, db, repos, events),
            instagram=InstagramService(db, repos, events),
            join_controls=JoinControlsService(db, repos, events),
            posters=PosterService(core, db, repos),
            presence=PresenceService(core, repos),
            theme=ThemeService(db, repos, events),
        )


def _derived_files(core: Core) -> Callable[[str], list[Path]]:
    """Every extension's `derived_files` of one photo."""

    def derived(public_id: str) -> list[Path]:
        out: list[Path] = []
        for ext in core.extensions.values():
            if ext.derived_files is None:
                continue
            try:
                out.extend(ext.derived_files(core, public_id))
            except Exception:
                log.exception("extension %s: derived_files failed", ext.id)
        return out

    return derived
