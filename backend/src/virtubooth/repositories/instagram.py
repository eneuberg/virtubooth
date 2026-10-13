"""Instagram board queries: which photos to post for a handle."""

from __future__ import annotations

from ..db.database import Database
from ..domain.models import Photo
from ._rows import PHOTO_COLS, photo_from_row


class InstagramRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def handle_exists(self, handle: str) -> bool:
        """Some guest gave this (normalized) handle."""
        return self.db.one("SELECT 1 FROM users WHERE instagram=? LIMIT 1", (handle,)) is not None

    def postable_photos(self, handle: str) -> list[Photo]:
        """The handle's photos worth posting, in upload order: visible (not
        hidden, not deleted) and taken by guests who are not banned."""
        rows = self.db.all(
            f"SELECT {PHOTO_COLS} FROM photos p JOIN users u ON u.id=p.user_id "
            "WHERE u.instagram=? AND u.banned_at IS NULL "
            "AND p.hidden_at IS NULL AND p.deleted_at IS NULL ORDER BY p.id",
            (handle,),
        )
        return [photo_from_row(r) for r in rows]
