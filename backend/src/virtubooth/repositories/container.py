"""All repositories over one database (also what the CLI tools open)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..db.database import Database
from .admin_read_models import AdminReadModels
from .admin_sessions import AdminSessionsRepo
from .app_settings import AppSettingsRepo
from .audit import AuditRepo
from .bans import FingerprintBansRepo
from .exports import ExportJobsRepo
from .instagram import InstagramRepo
from .photos import PhotosRepo
from .users import UsersRepo


@dataclass(frozen=True)
class Repositories:
    db: Database
    users: UsersRepo
    photos: PhotosRepo
    bans: FingerprintBansRepo
    app_settings: AppSettingsRepo
    admin_sessions: AdminSessionsRepo
    audit: AuditRepo
    read_models: AdminReadModels
    exports: ExportJobsRepo
    instagram: InstagramRepo

    @classmethod
    def create(cls, db: Database, data_dir: Path) -> Repositories:
        return cls(
            db=db,
            users=UsersRepo(db),
            photos=PhotosRepo(db, data_dir),
            bans=FingerprintBansRepo(db),
            app_settings=AppSettingsRepo(db),
            admin_sessions=AdminSessionsRepo(db),
            audit=AuditRepo(db),
            read_models=AdminReadModels(db),
            exports=ExportJobsRepo(db),
            instagram=InstagramRepo(db),
        )
