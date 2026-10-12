"""Settings, read once from the environment (prefix VB_)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    party_token: str
    admin_password: str
    secret_key: str
    data_dir: Path

    party_name: str = "Party"
    instagram_account: str = ""
    consent_version: str = "1"
    timezone: str = "Europe/Berlin"
    # "auto" marks cookies Secure when the request arrived over https
    # (behind a proxy this needs uvicorn's proxy headers, see README)
    cookie_secure: str = "auto"
    # None = every discovered extension
    extensions: tuple[str, ...] | None = None
    # extra origins accepted by the CSRF origin check, e.g. "https://party.example.com"
    allowed_origins: tuple[str, ...] = ()
    public_base_url: str = ""

    max_upload_bytes: int = 8_000_000
    uploads_per_user_per_min: int = 10
    uploads_per_ip_per_min: int = 60
    uploads_global_per_min: int = 300
    new_users_per_ip_per_10min: int = 120
    # generous: a whole party on one WiFi shares a single IP
    api_requests_per_ip_per_min: int = 1200
    admin_session_hours: int = 12

    def __post_init__(self) -> None:
        if not TOKEN_RE.match(self.party_token):
            raise ConfigError("VB_PARTY_TOKEN must be 16-128 chars of [A-Za-z0-9_-]")
        if len(self.admin_password) < 12:
            raise ConfigError("VB_ADMIN_PASSWORD must be at least 12 characters")
        if len(self.secret_key) < 32:
            raise ConfigError("VB_SECRET_KEY must be at least 32 characters")
        if self.cookie_secure not in ("auto", "true", "false"):
            raise ConfigError("VB_COOKIE_SECURE must be auto, true or false")

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        def req(name: str) -> str:
            value = env.get(name, "").strip()
            if not value:
                raise ConfigError(f"{name} is not set (run `virtubooth gen-env` for a template)")
            return value

        def opt_int(name: str, default: int) -> int:
            raw = env.get(name, "").strip()
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise ConfigError(f"{name} must be an integer") from exc

        def csv(name: str) -> tuple[str, ...]:
            return tuple(p.strip() for p in env.get(name, "").split(",") if p.strip())

        defaults = cls.__dataclass_fields__
        exts = csv("VB_EXTENSIONS")
        return cls(
            party_token=req("VB_PARTY_TOKEN"),
            admin_password=req("VB_ADMIN_PASSWORD"),
            secret_key=req("VB_SECRET_KEY"),
            data_dir=Path(env.get("VB_DATA_DIR", "./data")).resolve(),
            party_name=env.get("VB_PARTY_NAME", "").strip() or "Party",
            instagram_account=env.get("VB_INSTAGRAM_ACCOUNT", "").strip(),
            consent_version=env.get("VB_CONSENT_VERSION", "").strip() or "1",
            timezone=env.get("VB_TIMEZONE", "").strip() or "Europe/Berlin",
            cookie_secure=env.get("VB_COOKIE_SECURE", "").strip().lower() or "auto",
            extensions=exts or None,
            allowed_origins=csv("VB_ALLOWED_ORIGINS"),
            public_base_url=env.get("VB_PUBLIC_BASE_URL", "").strip().rstrip("/"),
            max_upload_bytes=opt_int("VB_MAX_UPLOAD_BYTES", defaults["max_upload_bytes"].default),
            uploads_per_user_per_min=opt_int(
                "VB_UPLOADS_PER_USER_PER_MIN", defaults["uploads_per_user_per_min"].default
            ),
            uploads_per_ip_per_min=opt_int(
                "VB_UPLOADS_PER_IP_PER_MIN", defaults["uploads_per_ip_per_min"].default
            ),
            uploads_global_per_min=opt_int(
                "VB_UPLOADS_GLOBAL_PER_MIN", defaults["uploads_global_per_min"].default
            ),
            new_users_per_ip_per_10min=opt_int(
                "VB_NEW_USERS_PER_IP_PER_10MIN", defaults["new_users_per_ip_per_10min"].default
            ),
            admin_session_hours=opt_int(
                "VB_ADMIN_SESSION_HOURS", defaults["admin_session_hours"].default
            ),
        )
