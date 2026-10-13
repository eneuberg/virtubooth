"""Admin views of domain objects: the shapes the admin API and the events send.

`AdminUser` needs lookups (which fingerprint ban auto-banned a guest, the QR
code it joined through), so it is built here and not on the schema alone.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..api.schemas.admin import AdminPhoto, AdminUser, CodeRef
from ..domain.models import Photo, PhotoQuery, User
from ..repositories.container import Repositories

USER_PHOTOS_MAX = 1000


class AdminViews:
    def __init__(self, repos: Repositories) -> None:
        self.repos = repos

    def users(self, users: Sequence[User]) -> list[AdminUser]:
        auto = [u.id for u in users if u.auto_banned]
        sources = self.repos.read_models.auto_ban_sources(auto)
        codes = self.code_refs() if any(u.code_id is not None for u in users) else {}
        return [
            AdminUser.of(u, sources.get(u.id), codes.get(u.code_id) if u.code_id else None)
            for u in users
        ]

    def code_refs(self) -> dict[int, CodeRef]:
        """Every QR code by number (codes are few: one query)."""
        return {
            c.id: CodeRef(id=c.id, name=c.name, active=c.active) for c in self.repos.codes.list()
        }

    def user(self, user: User) -> AdminUser:
        return self.users([user])[0]

    def user_by_id(self, user_id: int) -> AdminUser | None:
        user = self.repos.users.get(user_id)
        return self.user(user) if user else None

    @staticmethod
    def photos(photos: Sequence[Photo]) -> list[AdminPhoto]:
        return [AdminPhoto.of(p) for p in photos]

    def user_photos(self, user_id: int) -> list[AdminPhoto]:
        """All of a guest's photos, newest first (at most USER_PHOTOS_MAX)."""
        photos = self.repos.photos.list(PhotoQuery(user_id=user_id, limit=USER_PHOTOS_MAX))
        return self.photos(photos)
