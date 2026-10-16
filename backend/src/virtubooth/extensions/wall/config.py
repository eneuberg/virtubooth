"""The wall's settings (`WallConfig`, PLAN-WALL §4.1), stored as JSON in the
settings key `x.wall.config` (absent = the defaults below).

Input is validated strictly (no "12" for 12, no true for 1); unknown keys are
ignored, as are the server-set fields `rev`, `updated_at` and `by`. A bad value
is a 400 `invalid_wall_config` that names the field.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, field_validator

from ...core import errors
from ...domain.constants import EXT_ID_PATTERN
from ...repositories.app_settings import AppSettingsRepo

log = logging.getLogger("virtubooth.wall")

CONFIG_KEY = "x.wall.config"

Mode = Literal["spotlight", "gallery", "categories"]
MODES: tuple[Mode, ...] = ("spotlight", "gallery", "categories")
Algorithm = Literal[
    "newest", "random", "shuffle", "fair", "least_shown", "fresh_first", "highlights"
]
Transition = Literal[
    "crossfade", "kenburns", "spring", "dither", "pixelate", "glitch", "polaroid", "slot",
    "jelly", "stamp", "confetti", "random",
]  # fmt: skip
Speed = Literal["slow", "medium", "fast"]
Preset = Literal["blobs", "aurora", "disco", "confetti", "plain"]
Corner = Literal["bottom-right", "bottom-left", "top-right", "top-left"]

COLOR_PATTERN = r"^#[0-9a-f]{6}$"
CATEGORY_ID_PATTERN = r"^[a-z][a-z0-9_]{1,40}$"


def _lower(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


Color = Annotated[str, BeforeValidator(_lower), Field(pattern=COLOR_PATTERN)]
SourceId = Annotated[str, Field(pattern=EXT_ID_PATTERN)]

_STRICT = ConfigDict(strict=True, extra="ignore")


class WallPlaylistEntry(BaseModel):
    model_config = _STRICT

    mode: Mode
    enabled: bool = True
    duration_s: int = Field(60, ge=10, le=3600)


class WallSpotlight(BaseModel):
    model_config = _STRICT

    algorithm: Algorithm = "fresh_first"
    n: int = Field(12, ge=1, le=100, description="How many photos one round shows.")
    interval_s: int = Field(8, ge=3, le=120)
    transition: Transition = "random"
    transition_ms: int = Field(1200, ge=300, le=4000)


class WallGallery(BaseModel):
    model_config = _STRICT

    speed: Speed = "medium"
    rows: int = Field(3, ge=2, le=6)


class WallCategoriesConfig(BaseModel):
    """The categories themselves live in `wall_categories` (admin: /categories);
    an old `disabled` list is accepted and ignored (it was taken over into
    the categories' `enabled` once, when the presets were seeded)."""

    model_config = _STRICT

    per_category_s: int = Field(10, ge=4, le=60)
    disabled: list[str] = Field(
        default_factory=list,
        deprecated=True,
        description="Deprecated, always empty: switch categories on and off with "
        "PUT /admin/categories/{id}. Input is ignored.",
    )

    @field_validator("disabled", mode="plain")
    @classmethod
    def _ignored(cls, _value: Any) -> list[str]:
        return []


# the colours before the theme (Erscheinungsbild): a stored
# config that still has them never chose them, so it follows the theme
LEGACY_LOOK_COLORS: dict[str, str] = {
    "primary": "#a855f7",
    "secondary": "#ff4fa3",
    "background": "#2b2b31",
}
_WIE_THEME = "null: wie Theme (Erscheinungsbild)."


class WallLook(BaseModel):
    model_config = _STRICT

    preset: Preset = "blobs"
    primary: Color | None = Field(None, description="Theme `primary` when " + _WIE_THEME)
    secondary: Color | None = Field(None, description="Theme `accent` when " + _WIE_THEME)
    background: Color | None = Field(None, description="Theme `background` when " + _WIE_THEME)
    fps: Literal[30, 60] = 30
    calm: bool = False


class WallOverlay(BaseModel):
    model_config = _STRICT

    event_name: bool = True
    counter: bool = True
    qr: bool = False
    qr_code_id: int | None = Field(
        None, ge=1, description="The QR code shown in the corner; null = the lowest active one."
    )
    corner: Corner = "bottom-right"


def default_playlist() -> list[WallPlaylistEntry]:
    return [
        WallPlaylistEntry(mode="spotlight", enabled=True, duration_s=120),
        WallPlaylistEntry(mode="gallery", enabled=True, duration_s=45),
        WallPlaylistEntry(mode="categories", enabled=True, duration_s=60),
    ]


class WallSettings(BaseModel):
    """What the admin sets (WallConfig without the server-set fields)."""

    model_config = _STRICT

    playlist: list[WallPlaylistEntry] = Field(
        default_factory=default_playlist,
        description="Every mode exactly once, in playing order; at least one enabled.",
    )
    spotlight: WallSpotlight = Field(default_factory=WallSpotlight)
    gallery: WallGallery = Field(default_factory=WallGallery)
    categories: WallCategoriesConfig = Field(default_factory=WallCategoriesConfig)
    sources: list[SourceId] = Field(
        default_factory=list,
        max_length=50,
        description="Upload extensions shown on the wall; empty = all of them.",
    )
    delay_s: int = Field(20, ge=0, le=600, description="New photos appear after this delay.")
    show_instagram: bool = False
    look: WallLook = Field(default_factory=WallLook)
    overlay: WallOverlay = Field(default_factory=WallOverlay)

    @field_validator("playlist")
    @classmethod
    def _one_of_each(cls, playlist: list[WallPlaylistEntry]) -> list[WallPlaylistEntry]:
        if sorted(e.mode for e in playlist) != sorted(MODES):
            raise ValueError("every mode exactly once")
        if not any(e.enabled for e in playlist):
            raise ValueError("at least one mode enabled")
        return playlist

    @field_validator("sources")
    @classmethod
    def _unique_sources(cls, sources: list[str]) -> list[str]:
        return list(dict.fromkeys(sources))


class WallConfig(WallSettings):
    """The wall's settings as stored and sent."""

    rev: int = Field(0, description="Counts saves (server-set).")
    updated_at: str | None = Field(None, description="Server-set.")
    by: str | None = Field(None, description="Who saved last (server-set).")


def _field(exc: ValidationError) -> str:
    loc = exc.errors()[0]["loc"] if exc.errors() else ()
    parts = [str(p) for p in loc if isinstance(p, str)]
    return ".".join(parts) or "config"


def invalid_config(field: str) -> errors.ApiError:
    return errors.bad_request(f"Ungültige Einstellung: {field}.", "invalid_wall_config")


def parse_settings(
    data: Any, upload_ids: Collection[str], stale_ok: Collection[str] = ()
) -> WallSettings:
    """Validate admin input; raises 400 `invalid_wall_config` naming the field.
    A source in `stale_ok` (the stored config's) that is no longer loaded is
    dropped, so a config saved before an extension went away saves again; any
    other unknown source is refused."""
    if not isinstance(data, dict):
        raise invalid_config("config")
    try:
        settings = WallSettings.model_validate(data)
    except ValidationError as exc:
        raise invalid_config(_field(exc)) from None
    unknown = [s for s in settings.sources if s not in upload_ids]
    if any(s not in stale_ok for s in unknown):
        raise invalid_config("sources")
    if unknown:
        settings.sources = [s for s in settings.sources if s in upload_ids]
    return settings


def prune_sources(config: WallConfig, upload_ids: Collection[str]) -> WallConfig:
    """The config without sources that are no longer loaded (a stale id never
    reaches a screen or the admin). None left means all, as for an empty list."""
    kept = [s for s in config.sources if s in upload_ids]
    if kept == config.sources:
        return config
    return config.model_copy(update={"sources": kept})


def load_config(repo: AppSettingsRepo) -> WallConfig:
    """The stored config; the defaults when there is none (or it no longer validates)."""
    raw = repo.get(CONFIG_KEY)
    if not raw:
        return WallConfig()
    look = raw.get("look")
    if isinstance(look, dict):
        raw = raw | {
            "look": {k: (None if LEGACY_LOOK_COLORS.get(k) == v else v) for k, v in look.items()}
        }
    try:
        return WallConfig.model_validate(raw, strict=False)
    except ValidationError:
        log.warning("stored %s is invalid: using the defaults", CONFIG_KEY)
        return WallConfig()


def store_config(repo: AppSettingsRepo, config: WallConfig, *, at: str) -> None:
    repo.put(CONFIG_KEY, config.model_dump(mode="json"), at=at)


def changed_keys(old: WallConfig, new: WallConfig) -> list[str]:
    """Top-level keys whose value differs (for the audit log)."""
    before, after = old.model_dump(mode="json"), new.model_dump(mode="json")
    return [k for k in WallSettings.model_fields if before.get(k) != after.get(k)]
