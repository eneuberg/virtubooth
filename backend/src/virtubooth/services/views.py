"""Admin views of domain objects: the shapes the admin API and the events send.

`AdminUser` needs a lookup (which fingerprint ban auto-banned a guest), so it
is built here and not on the schema alone.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..api.schemas.admin import AdminPhoto, AdminUser
from ..domain.models import Photo, PhotoQuery, User
from ..repositories.container import Repositories

USER_PHOTOS_MAX = 1000


class AdminViews:
    def __init__(self, repos: Repositories) -> None:
        self.repos = repos

    def users(self, users: Sequence[User]) -> list[AdminUser]:
        auto = [u.id for u in users if u.auto_banned]
        sources = self.repos.read_models.auto_ban_sources(auto)
        return [AdminUser.of(u, sources.get(u.id)) for u in users]

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
