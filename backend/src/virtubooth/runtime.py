"""`Core`: everything a request handler, service or extension needs.

Built once per app by `create_app`. Tests swap `settings` (via
`settings.replace(...)`), single limiters and extensions on it; services read
those through `core` at call time, so the swap takes effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .core.events import EventBus
from .core.ratelimit import Limits
from .core.security import Signer
from .db.database import Database
from .extensions.sdk import Extension
from .repositories.container import Repositories
from .services.container import Services
from .settings import Settings
from .web.frontend import WebFrontend


@dataclass
class Core:
    settings: Settings
    db: Database
    repos: Repositories
    bus: EventBus
    signer: Signer
    limits: Limits
    web: WebFrontend
    extensions: dict[str, Extension] = field(default_factory=dict)
    services: Services = field(init=False)

    def __post_init__(self) -> None:
        self.services = Services.create(self)

    @classmethod
    def create(
        cls, settings: Settings, extensions: list[Extension], web: WebFrontend
    ) -> Core:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        db = Database(settings.data_dir / "virtubooth.db")
        return cls(
            settings=settings,
            db=db,
            repos=Repositories.create(db, settings.data_dir),
            bus=EventBus(),
            signer=Signer(settings.secret_key.get_secret_value()),
            limits=Limits.from_settings(settings),
            web=web,
            extensions={e.id: e for e in extensions},
        )
