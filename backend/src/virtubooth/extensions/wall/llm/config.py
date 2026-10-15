"""`x.llm.config`: the host's external-AI settings (PLAN-NIGHT §3).

Stored as JSON in the settings table. A stored value that no longer validates
(hand-edited, an older shape) reads as the defaults, never as an error.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ....core.clock import now_iso
from ....repositories.app_settings import AppSettingsRepo
from . import pricing

CONFIG_KEY: Final = "x.llm.config"
ProviderId = Literal["anthropic", "mistral"]


class DetectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local: bool = Field(True, description="The local object detector runs (D1's `objects`).")
    external: bool = Field(False, description="The external AI also lists objects per photo.")


class BudgetConfig(BaseModel):
    """The cost brake: null = no limit of that kind."""

    model_config = ConfigDict(extra="forbid")

    party_usd: float | None = Field(5.0, ge=0, le=10_000)
    party_calls: int | None = Field(None, ge=0, le=10_000_000)
    daily_usd: float | None = Field(2.0, ge=0, le=10_000)
    daily_calls: int | None = Field(None, ge=0, le=10_000_000)


class LlmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(False, description="Master switch: nothing is sent while off.")
    provider: ProviderId = "anthropic"
    model: str = pricing.DEFAULT_MODEL
    poll_interval_s: int = Field(180, ge=60, le=3600)
    detect: DetectConfig = Field(default_factory=DetectConfig)
    image_max_px: int = Field(1024, ge=256, le=2048, description="Long edge sent for detection.")
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    rev: int = 0
    updated_at: str | None = None
    by: str | None = None

    @model_validator(mode="after")
    def _model_fits_provider(self) -> LlmConfig:
        info = pricing.BY_ID.get(self.model)
        if info is None or info.provider != self.provider:
            raise ValueError(f"model {self.model!r} is not a {self.provider} model")
        return self


class LlmConfigIn(BaseModel):
    """`PUT /llm/config`: the fields to change (missing ones stay). Ranges are
    checked after merging (400 `invalid_llm_config`), not by the request schema."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    provider: ProviderId | None = None
    model: str | None = None
    poll_interval_s: int | None = None
    detect: DetectConfig | None = None
    image_max_px: int | None = None
    budget: dict[str, float | int | None] | None = None


def load_config(app_settings: AppSettingsRepo) -> LlmConfig:
    raw = app_settings.get(CONFIG_KEY)
    if not raw:
        return LlmConfig()
    try:
        return LlmConfig.model_validate(raw)
    except ValidationError:
        return LlmConfig()


def merged(current: LlmConfig, change: LlmConfigIn) -> LlmConfig:
    """The new config; raises ValueError (German message) when it is invalid."""
    data: dict[str, Any] = current.model_dump()
    patch = change.model_dump(exclude_none=True)
    if "budget" in patch:
        # an explicit null switches a limit off: take the budget as sent
        patch["budget"] = {**data["budget"], **(change.budget or {})}
    if "provider" in patch and "model" not in patch and patch["provider"] != current.provider:
        patch["model"] = pricing.DEFAULT_BY_PROVIDER[patch["provider"]]
    data.update(patch)
    try:
        return LlmConfig.model_validate(data)
    except ValidationError as exc:
        raise ValueError(_message(exc)) from exc


def _message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(p) for p in first.get("loc", ()))
    if where.startswith("poll_interval_s"):
        return "Das Abfrage-Intervall muss zwischen 1 und 60 Minuten liegen."
    if where.startswith("budget"):
        return "Das Budget muss eine Zahl ab 0 sein (leer = keine Grenze)."
    if where.startswith("image_max_px"):
        return "Die Bildgröße muss zwischen 256 und 2048 px liegen."
    if not where or where.startswith("model"):
        return "Dieses Modell gibt es bei diesem Anbieter nicht."
    return f"Ungültige Einstellung: {where}."


def save_config(app_settings: AppSettingsRepo, config: LlmConfig, *, by: str) -> LlmConfig:
    at = now_iso()
    stored = config.model_copy(update={"rev": config.rev + 1, "updated_at": at, "by": by})
    app_settings.put(CONFIG_KEY, stored.model_dump(mode="json"), at=at)
    return stored
