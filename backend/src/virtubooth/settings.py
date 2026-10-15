"""Settings, read once from the environment (prefix VB_) and validated at startup.

The app reads the process environment, never a .env file (Docker passes the
file as `env_file`; locally: `set -a && . ./.env && set +a`). Empty variables
count as unset. Secrets are `SecretStr`: call `.get_secret_value()` only where
the raw value is needed (signing, comparing) and never log it.

Tests build `Settings(...)` directly with `_env_file=None` after clearing every
`VB_*` variable, so the developer's own environment never leaks in.

VB_PARTY_TOKEN is optional and only read while the database has no QR code
(the first start, or the first start after the update that brought QR codes):
it becomes QR code 1's token (services/codes.py). After that the database is
the only source of tokens; Admin → QR-Codes manages them.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from contextvars import ContextVar
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field, SecretStr, ValidationError, ValidationInfo, field_validator
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from .core.clock import DEFAULT_TIMEZONE

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

# backend/src/virtubooth/settings.py -> the repository root (a source checkout)
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WEB_DIR = REPO_ROOT / "frontend" / "dist"


class ConfigError(RuntimeError):
    """A setting is missing or invalid. The message names the VB_* variable."""


def default_web_dir() -> Path | None:
    """`<repo>/frontend/dist` when running from a checkout with a built frontend."""
    return DEFAULT_WEB_DIR if DEFAULT_WEB_DIR.is_dir() else None


# Settings.from_env(mapping) reads that mapping instead of os.environ
_ENV_OVERRIDE: ContextVar[Mapping[str, str] | None] = ContextVar("vb_env_override", default=None)


class _MappingEnvSource(EnvSettingsSource):
    def __init__(self, settings_cls: type[BaseSettings], env: Mapping[str, str]) -> None:
        self._mapping = env
        super().__init__(settings_cls)

    def _load_env_vars(self) -> Mapping[str, str | None]:
        return {k.lower(): v for k, v in self._mapping.items() if v != ""}


Csv = Annotated[tuple[str, ...], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VB_",
        env_ignore_empty=True,
        frozen=True,
        extra="ignore",
        validate_default=True,
    )

    # only read while the database has no QR code (see the module docstring)
    party_token: SecretStr | None = None
    admin_password: SecretStr
    secret_key: SecretStr
    data_dir: Path = Path("./data")

    party_name: str = "Party"
    instagram_account: str = ""
    consent_version: str = "1"
    timezone: str = DEFAULT_TIMEZONE
    # "auto" marks cookies Secure when the request arrived over https
    # (behind a proxy this needs uvicorn's proxy headers, see README)
    cookie_secure: Literal["auto", "true", "false"] = "auto"
    # None = every discovered extension
    extensions: Annotated[tuple[str, ...] | None, NoDecode] = None
    # extra origins accepted by the CSRF origin check, e.g. "https://party.example.com"
    allowed_origins: Csv = ()
    public_base_url: str = ""

    max_upload_bytes: int = 8_000_000
    uploads_per_user_per_min: int = 10
    # a whole party on one WiFi shares an IP
    uploads_per_ip_per_min: int = 180
    uploads_global_per_min: int = 300
    new_users_per_ip_per_10min: int = 120
    # QR scans (?t=) from browsers without a visitor id, per IP: over it the
    # browser still gets in, but no new visitor row is written
    scans_per_ip_per_10min: int = 120
    # photos a guest may keep (not deleted), over every activity; 0 = no limit
    max_photos_per_guest: int = 300
    # uploads are refused while the data dir's disk has less free space (MB)
    min_free_mb: int = 2048
    # requests from identified guests count per device, the rest per IP
    api_requests_per_ip_per_min: int = 1200
    api_requests_per_guest_per_min: int = 300
    admin_session_hours: int = 12

    # the built frontend (Vite `dist`): index.html, admin.html, gate.html, assets/
    web_dir: Path | None = Field(default_factory=default_web_dir)
    # development: serve built-in placeholder pages when there is no web_dir.
    # Relaxes nothing security-relevant.
    dev: bool = False

    _INT_FIELDS: ClassVar[tuple[str, ...]] = (
        "max_upload_bytes",
        "uploads_per_user_per_min",
        "uploads_per_ip_per_min",
        "uploads_global_per_min",
        "new_users_per_ip_per_10min",
        "scans_per_ip_per_10min",
        "max_photos_per_guest",
        "min_free_mb",
        "api_requests_per_ip_per_min",
        "api_requests_per_guest_per_min",
        "admin_session_hours",
    )

    def __init__(self, **values: Any) -> None:
        try:
            super().__init__(**values)
        except ValidationError as exc:
            raise ConfigError(describe(exc)) from None

    # ------------------------------------------------------------ sources

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        override = _ENV_OVERRIDE.get()
        if override is not None:
            return (init_settings, _MappingEnvSource(settings_cls, override))
        # no .env file and no secrets dir: the process environment only
        return (init_settings, env_settings)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Settings from `env` (default: the process environment) only."""
        token = _ENV_OVERRIDE.set(dict(os.environ if env is None else env))
        try:
            return cls()
        finally:
            _ENV_OVERRIDE.reset(token)

    def replace(self, **changes: Any) -> Settings:
        """A validated copy with some fields changed (like dataclasses.replace)."""
        data = {name: getattr(self, name) for name in type(self).model_fields}
        data.update(changes)
        try:
            # model_validate skips __init__, i.e. the environment: only `data` counts
            return type(self).model_validate(data)
        except ValidationError as exc:
            raise ConfigError(describe(exc)) from None

    # --------------------------------------------------------- validators

    @field_validator("party_token", mode="after")
    @classmethod
    def _check_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value():
            return None
        if not TOKEN_RE.match(value.get_secret_value()):
            raise ValueError("VB_PARTY_TOKEN must be 16-128 chars of [A-Za-z0-9_-]")
        return value

    @field_validator("admin_password", mode="after")
    @classmethod
    def _check_password(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 12:
            raise ValueError("VB_ADMIN_PASSWORD must be at least 12 characters")
        return value

    @field_validator("secret_key", mode="after")
    @classmethod
    def _check_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("VB_SECRET_KEY must be at least 32 characters")
        return value

    @field_validator("party_token", "admin_password", "secret_key", mode="before")
    @classmethod
    def _strip_secret(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("cookie_secure", mode="before")
    @classmethod
    def _cookie_secure(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip().lower() or "auto"
            if value not in ("auto", "true", "false"):
                raise ValueError("VB_COOKIE_SECURE must be auto, true or false")
        return value

    @field_validator("party_name", "consent_version", "timezone", mode="before")
    @classmethod
    def _blank_is_default(cls, value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                assert info.field_name is not None
                return cls.model_fields[info.field_name].default
        return value

    @field_validator("instagram_account", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("public_base_url", mode="before")
    @classmethod
    def _base_url(cls, value: Any) -> Any:
        return value.strip().rstrip("/") if isinstance(value, str) else value

    @field_validator("extensions", mode="before")
    @classmethod
    def _extension_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = _csv(value)
        if value is not None and not value:
            return None  # empty list = every extension
        return tuple(value) if isinstance(value, list | tuple) else value

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _origin_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _csv(value)
        return tuple(value) if isinstance(value, list) else value

    @field_validator(*_INT_FIELDS, mode="before")
    @classmethod
    def _int(cls, value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, str):
            raw = value.strip()
            assert info.field_name is not None
            if not raw:
                return cls.model_fields[info.field_name].default
            try:
                return int(raw)
            except ValueError:
                raise ValueError(f"VB_{info.field_name.upper()} must be an integer") from None
        return value

    @field_validator("data_dir", mode="after")
    @classmethod
    def _resolve_dir(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("web_dir", mode="after")
    @classmethod
    def _resolve_web_dir(cls, value: Path | None) -> Path | None:
        return value.expanduser().resolve() if value is not None else None


# below this the startup log warns (the hard minimum stays 12, so an existing
# deployment keeps starting)
RECOMMENDED_PASSWORD_LENGTH = 16


def admin_password_warnings(password: str) -> list[str]:
    """Why VB_ADMIN_PASSWORD is weak, for the startup log; empty when it's fine.

    The login is rate limited and locks after repeated failures, but a short
    or repetitive password can still be guessed over days. Never includes the
    password itself."""
    hint = "use 16+ random characters (`virtubooth gen-env` prints one)"
    warnings: list[str] = []
    if len(password) < RECOMMENDED_PASSWORD_LENGTH:
        warnings.append(
            f"VB_ADMIN_PASSWORD has only {len(password)} characters: easy to guess; {hint}"
        )
    classes = sum(
        any(test(c) for c in password)
        for test in (str.islower, str.isupper, str.isdigit, lambda c: not c.isalnum())
    )
    if len(set(password)) < 8 or (classes < 2 and len(password) < 20):
        warnings.append(f"VB_ADMIN_PASSWORD has very little variety: easy to guess; {hint}")
    return warnings


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def describe(exc: ValidationError) -> str:
    """One readable line per problem, naming the environment variable."""
    problems: list[str] = []
    for err in exc.errors():
        field = str(err["loc"][0]) if err["loc"] else "?"
        env = f"VB_{field.upper()}"
        if err["type"] == "missing":
            problems.append(f"{env} is not set (run `virtubooth gen-env` for a template)")
            continue
        message = str(err["msg"]).removeprefix("Value error, ")
        problems.append(message if message.startswith("VB_") else f"{env}: {message}")
    return "; ".join(problems)
