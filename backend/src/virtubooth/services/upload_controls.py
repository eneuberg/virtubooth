"""Upload controls. Three levels, independent of each other and of bans:

- stop all uploads for a while (every guest, existing and new)
- pause new guests: whoever joins while it is on starts with uploads paused.
  Turning it off needs a choice: restore the guests this pause period paused,
  or keep them paused.
- pause or allow one guest

Paused guests get 403 uploads_paused, everyone gets 403 uploads_stopped during
a stop. Their photos stay visible and they can still browse.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..api.schemas.admin import AdminUser, PauseState, StopState
from ..core import errors
from ..core.clock import now_iso
from ..db.database import Database
from ..repositories.container import Repositories
from .events import AdminEvents
from .views import AdminViews


@dataclass(frozen=True)
class PauseChange:
    state: PauseState
    changed: bool
    restored: list[int]
    kept: list[int]


class UploadControlsService:
    def __init__(
        self, db: Database, repos: Repositories, events: AdminEvents, views: AdminViews
    ) -> None:
        self.db = db
        self.repos = repos
        self.events = events
        self.views = views

    # ------------------------------------------------------------ stop all

    def stop_state(self) -> StopState:
        return StopState.model_validate(self.repos.app_settings.upload_stop())

    def uploads_stopped(self) -> bool:
        return self.repos.app_settings.upload_stop().enabled

    def set_stop(self, enabled: bool, *, actor: str) -> tuple[StopState, bool]:
        with self.db.tx():
            if self.repos.app_settings.upload_stop().enabled == enabled:
                return self.stop_state(), False
            at = now_iso()
            self.repos.app_settings.put_upload_stop(
                enabled=enabled, since=at if enabled else None, by=actor, at=at
            )
            self.repos.audit.log(actor, "uploads.stop" if enabled else "uploads.resume", at=at)
            state = self.stop_state()
            self.events.upload_stop(state)
        return state, True

    # ----------------------------------------------------- pause new guests

    def pause_state(self) -> PauseState:
        """The new-guest lock plus how many guests it paused (`affected`, this
        period, still paused by it) and how many guests are paused at all."""
        lock = self.repos.app_settings.upload_lock()
        users = self.repos.users
        affected = users.count_paused(lock_period=lock.period) if lock.enabled else 0
        return PauseState(
            enabled=lock.enabled,
            since=lock.since,
            period=lock.period,
            by=lock.by,
            affected=affected,
            paused_total=users.count_paused(),
        )

    def set_pause(self, enabled: bool, *, restore: bool | None, actor: str) -> PauseChange:
        if not enabled and restore is None:
            raise errors.bad_request(
                "Bitte wählen: die pausierten neuen Gäste freischalten oder pausiert lassen.",
                "restore_required",
            )
        restored: list[int] = []
        kept: list[int] = []
        with self.db.tx():
            settings = self.repos.app_settings
            lock = settings.upload_lock()
            at = now_iso()
            if enabled:
                changed = not lock.enabled
                if changed:
                    period = settings.lock_period_counter() + 1
                    settings.put_upload_lock(enabled=True, since=at, period=period, by=actor, at=at)
                    self.repos.audit.log(actor, "uploads.lock_on", "", {"period": period}, at=at)
            else:
                changed = lock.enabled
                if changed:
                    period = settings.lock_period_counter()
                    ids = self.repos.users.paused_by_lock(period)
                    if restore and ids:
                        self.repos.users.unpause_lock_period(period)
                    restored, kept = (ids, []) if restore else ([], ids)
                    settings.put_upload_lock(enabled=False, since=None, period=period, by=actor, at=at)
                    self.repos.audit.log(
                        actor, "uploads.lock_off", "",
                        {"period": period, "restore": restore, "restored": len(restored),
                         "kept": len(kept)},
                        at=at,
                    )  # fmt: skip
            state = self.pause_state()
            if changed:
                self.events.upload_pause(state, restored, kept)
            if restored:
                self.events.uploads_changed(self._views(restored), paused=False)
        return PauseChange(state, changed, restored, kept)

    # ------------------------------------------------------------ one guest

    def set_user_paused(self, user_id: int, paused: bool, *, actor: str) -> tuple[AdminUser, bool]:
        """Pause (source 'admin') or allow one guest's uploads. Not a ban: their
        photos stay visible. Pausing clears a lock period; unpausing clears all."""
        with self.db.tx():
            current = self.repos.users.pause_source(user_id)
            if current is None:
                raise errors.not_found("Gast nicht gefunden.")
            was_paused, source = current
            changed = was_paused != paused
            if changed:
                at = now_iso()
                if paused:
                    self.repos.users.pause(user_id, at=at)
                    self.repos.audit.log(actor, "user.uploads_pause", f"user:{user_id}", at=at)
                else:
                    self.repos.users.unpause(user_id)
                    self.repos.audit.log(
                        actor, "user.uploads_unpause", f"user:{user_id}", {"source": source}, at=at
                    )
            view = self.views.user_by_id(user_id)
            assert view is not None
            if changed:
                self.events.uploads_changed([view], paused=paused)
        return view, changed

    def _views(self, user_ids: list[int]) -> list[AdminUser]:
        users = [u for u in (self.repos.users.get(i) for i in user_ids) if u is not None]
        return self.views.users(users)
