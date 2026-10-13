"""The join stop („Anmeldung stoppen“): while it is on, nobody new can join.

Guests who joined already keep working (their uploads follow the upload
switches as before); `POST /api/join` refuses new devices with 403
`join_closed`, and `/api/identify` tells an unknown device that joining is
closed (`join_closed: true`), so the join sheet can say so up front.
"""

from __future__ import annotations

from ..api.schemas.admin import StopState
from ..core.clock import now_iso
from ..db.database import Database
from ..repositories.container import Repositories
from .events import AdminEvents


class JoinControlsService:
    def __init__(self, db: Database, repos: Repositories, events: AdminEvents) -> None:
        self.db = db
        self.repos = repos
        self.events = events

    def state(self) -> StopState:
        return StopState.model_validate(self.repos.app_settings.join_stop())

    def join_stopped(self) -> bool:
        return self.repos.app_settings.join_stop().enabled

    def set_stop(self, enabled: bool, *, actor: str) -> tuple[StopState, bool]:
        with self.db.tx():
            if self.repos.app_settings.join_stop().enabled == enabled:
                return self.state(), False
            at = now_iso()
            self.repos.app_settings.put_join_stop(
                enabled=enabled, since=at if enabled else None, by=actor, at=at
            )
            self.repos.audit.log(actor, "join.stop" if enabled else "join.resume", at=at)
            state = self.state()
            self.events.join_stop(state)
        return state, True
