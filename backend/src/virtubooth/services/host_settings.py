"""Einstellungen: the event name the host sets in the admin.

The name lives in the `settings` table (`event`) and overrides VB_PARTY_NAME
everywhere a guest or an export sees it; deleting it (reset) brings the env
value back. Admin screens follow through the `settings.event` event; guests
have no event stream and pick it up when they next fetch `/api/extensions`
(the guest app polls it every minute while visible).

The admin password lives in AdminAuthService (it shares the login's limits).
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from ..api.schemas.host_settings import AdminSettingsOut, EventSettings, PasswordState
from ..core import errors
from ..core.clock import now_iso
from ..db.database import Database
from ..repositories.app_settings import EVENT_KEY
from ..repositories.container import Repositories
from ..settings import Settings
from .events import AdminEvents

if TYPE_CHECKING:
    from ..runtime import Core

EVENT_NAME_MAX = 60
_WHITESPACE = re.compile(r"\s+")
# bidi embeddings, overrides and isolates: they could turn the rest of a page around
_BIDI_CONTROLS = frozenset("‪‫‬‭‮⁦⁧⁨⁩")


def invalid_event_name() -> errors.ApiError:
    return errors.bad_request("Der Name braucht 1 bis 60 Zeichen.", "invalid_event_name")


def normalize_event_name(raw: str | None) -> str | None:
    """The name to store, or None for "back to VB_PARTY_NAME" (null or blank).

    Strips, collapses every run of whitespace (line breaks included) to one
    space, then refuses control characters and names nobody can see (only
    invisible format characters such as zero-width spaces): 400
    `invalid_event_name`, like a name over 60 characters."""
    if raw is None:
        return None
    name = _WHITESPACE.sub(" ", raw).strip()
    if not name:
        return None
    for ch in name:
        if unicodedata.category(ch) in ("Cc", "Cs") or ch in _BIDI_CONTROLS:
            raise invalid_event_name()
    # spaces and format characters (Cf) alone show nothing; an emoji newer than
    # this Python's Unicode tables (Cn) still counts as visible
    visible = any(
        not unicodedata.category(ch).startswith("Z") and unicodedata.category(ch) != "Cf"
        for ch in name
    )
    if not visible or len(name) > EVENT_NAME_MAX:
        raise invalid_event_name()
    return name


def event_name(settings: Settings, repos: Repositories) -> str:
    """The event name in use: the host's, else VB_PARTY_NAME. For code without
    the services (the export runners)."""
    stored = repos.app_settings.event_name()
    return stored.name if stored is not None else settings.party_name


class HostSettingsService:
    def __init__(self, core: Core, db: Database, repos: Repositories, events: AdminEvents) -> None:
        self.core = core
        self.db = db
        self.repos = repos
        self.events = events

    def event_name(self) -> str:
        return event_name(self.core.settings, self.repos)

    def event(self) -> EventSettings:
        stored = self.repos.app_settings.event_name()
        default = self.core.settings.party_name
        return EventSettings(
            name=stored.name if stored else default,
            default_name=default,
            custom=stored is not None,
            updated_at=stored.at if stored else None,
            by=stored.by if stored else None,
        )

    def set_event_name(self, raw: str | None, *, actor: str) -> tuple[EventSettings, bool]:
        """Set the name (None or blank: back to VB_PARTY_NAME). Returns the new
        state and whether anything changed."""
        name = normalize_event_name(raw)
        with self.db.tx():
            stored = self.repos.app_settings.event_name()
            if (stored.name if stored else None) == name:
                return self.event(), False
            previous = self.event_name()
            at = now_iso()
            if name is None:
                self.repos.app_settings.delete(EVENT_KEY)
            else:
                self.repos.app_settings.put_event_name(name, by=actor, at=at)
            state = self.event()
            self.repos.audit.log(
                actor,
                "settings.event",
                details={"event_name": state.name, "previous": previous},
                at=at,
            )
            self.events.settings_event(state)
        return state, True

    def password(self) -> PasswordState:
        stored = self.repos.app_settings.admin_password()
        if stored is None:
            return PasswordState(source="env", changed_at=None)
        return PasswordState(source="admin", changed_at=stored.changed_at)

    def admin_settings(self) -> AdminSettingsOut:
        return AdminSettingsOut(event=self.event(), password=self.password())
