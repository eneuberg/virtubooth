"""The `Core` object: everything a request handler or extension needs."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings
from .db import Database
from .events import EventBus
from .extension import Extension
from .ratelimit import RateLimiter
from .repo import Repo
from .security import Signer


@dataclass
class Limits:
    upload_user: RateLimiter
    upload_ip: RateLimiter
    upload_global: RateLimiter
    new_user_ip: RateLimiter
    api_ip: RateLimiter
    api_guest: RateLimiter
    login_ip: RateLimiter
    login_ip_hourly: RateLimiter
    login_failures_global: RateLimiter

    @classmethod
    def from_settings(cls, s: Settings) -> Limits:
        return cls(
            upload_user=RateLimiter(s.uploads_per_user_per_min, 60),
            upload_ip=RateLimiter(s.uploads_per_ip_per_min, 60),
            upload_global=RateLimiter(s.uploads_global_per_min, 60),
            new_user_ip=RateLimiter(s.new_users_per_ip_per_10min, 600),
            api_ip=RateLimiter(s.api_requests_per_ip_per_min, 60),
            api_guest=RateLimiter(s.api_requests_per_guest_per_min, 60),
            login_ip=RateLimiter(5, 60),
            login_ip_hourly=RateLimiter(20, 3600),
            # after 50 wrong passwords per hour from anywhere, wrong guesses get 429
            login_failures_global=RateLimiter(50, 3600),
        )

    def reset(self) -> None:
        for limiter in vars(self).values():
            limiter.reset()


@dataclass
class Core:
    settings: Settings
    db: Database
    repo: Repo
    bus: EventBus
    signer: Signer
    limits: Limits
    extensions: dict[str, Extension] = field(default_factory=dict)
