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
from .providers import BY_ID as PROVIDERS

CONFIG_KEY: Final = "x.llm.config"
ProviderId = Literal["anthropic", "mistral", "deutschlandgpt", "scaleway"]
Effort = Literal["low", "medium", "high"]


class DetectConfig(BaseModel):
    """Object detection is either/or: the local detector (D1's `objects` analyzer,
    switched in `x.wall.analyzers`) OR the external AI (`external`), never both.
    Switching one on switches the other off (`set_detection`)."""

    model_config = ConfigDict(extra="forbid")

    external: bool = Field(
        False,
        description="„Objekte mit KI“: the external AI lists the objects of each photo the "
        "pipeline analyses while this is on (and the master switch is on); the local "
        "detector is off meanwhile. Older photos are never sent afterwards.",
    )

    @model_validator(mode="before")
    @classmethod
    def _older_shape(cls, data: Any) -> Any:
        """Before the either/or, `detect` also held `local` (the objects analyzer's
        switch, which `x.wall.analyzers` keeps anyway): ignored here, in a stored
        config and in a request; `migrate` resolves a stored config with both on."""
        if isinstance(data, dict) and "local" in data:
            data = {k: v for k, v in data.items() if k != "local"}
        return data


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
    poll: bool = Field(
        True,
        description="„Eigenschaften abfragen“: every `poll_interval_s` the external AI rates "
        "the properties and writes the category verdicts. Independent of `detect.external`; "
        "a stored config from before this switch reads as on (the poll ran then whenever "
        "external AI was on).",
    )
    poll_interval_s: int = Field(180, ge=60, le=3600)
    detect: DetectConfig = Field(default_factory=DetectConfig)
    effort: Effort = Field(
        "low",
        description="„Denkaufwand“: how long the model thinks before answering (Anthropic "
        "and DeutschlandGPT; adaptive thinking with this effort). Thinking is billed as "
        "output tokens, so higher costs more. Ignored by providers without thinking.",
    )
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
        if self.detect.external and not PROVIDERS[self.provider].vision:
            raise ValueError(f"detect: {self.provider} cannot look at photos")
        return self

    @property
    def ai_detection(self) -> bool:
        """The external AI detects objects right now (master switch and its own)."""
        return self.enabled and self.detect.external


class LlmConfigIn(BaseModel):
    """`PUT /llm/config`: the fields to change (missing ones stay). Ranges are
    checked after merging (400 `invalid_llm_config`), not by the request schema."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    provider: ProviderId | None = None
    model: str | None = None
    poll: bool | None = None
    poll_interval_s: int | None = None
    detect: DetectConfig | None = None
    effort: Effort | None = None
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
    if "cannot look at photos" in str(first.get("msg", "")):
        return (
            "Dieser Anbieter kann keine Fotos ansehen: zuerst unter „Modelle“ die "
            "Objekterkennung auf „Lokal“ oder „Aus“ stellen."
        )
    if not where or where.startswith("model"):
        return "Dieses Modell gibt es bei diesem Anbieter nicht."
    return f"Ungültige Einstellung: {where}."


def save_config(app_settings: AppSettingsRepo, config: LlmConfig, *, by: str) -> LlmConfig:
    at = now_iso()
    stored = config.model_copy(update={"rev": config.rev + 1, "updated_at": at, "by": by})
    app_settings.put(CONFIG_KEY, stored.model_dump(mode="json"), at=at)
    return stored


def migrate(app_settings: AppSettingsRepo) -> str | None:
    """At start: make a stored config from before the either/or fit it. Both
    detectors on → the external AI wins when it actually ran (master switch on:
    the host chose it explicitly; the local one was on by default), and the
    local `objects` analyzer is switched off; with the master switch off the AI's
    switch is cleared and the local detector stays. Returns what was done
    ("ai", "local") or None (nothing to do). Idempotent."""
    from ..enrich import jobs

    raw = app_settings.get(CONFIG_KEY)
    detect = raw.get("detect") if raw else None
    if not isinstance(detect, dict):
        return None
    cfg = load_config(app_settings)
    local_on = "objects" not in jobs.disabled_analyzers(app_settings)
    legacy = "local" in detect
    if not (legacy or (cfg.detect.external and local_on)):
        return None
    outcome: str | None = None
    if cfg.detect.external and local_on:
        if cfg.enabled:
            jobs.save_disabled(
                app_settings, jobs.disabled_analyzers(app_settings) | {"objects"}, by="migration"
            )
            outcome = "ai"
        else:
            cfg = cfg.model_copy(update={"detect": DetectConfig(external=False)})
            outcome = "local"
    # rewritten in the new shape (without `local`), keeping rev/updated_at/by
    app_settings.put(CONFIG_KEY, cfg.model_dump(mode="json"), at=now_iso())
    return outcome


def set_ai_detection(app_settings: AppSettingsRepo, on: bool, *, by: str) -> LlmConfig:
    """Switch „Objekte mit KI“ (only `detect.external`; the caller switches the
    local `objects` analyzer the other way). Stored only when it changes."""
    cfg = load_config(app_settings)
    if cfg.detect.external == on:
        return cfg
    new = cfg.model_copy(update={"detect": DetectConfig(external=on)})
    if on:
        new = LlmConfig.model_validate(new.model_dump())  # the provider must see photos
    return save_config(app_settings, new, by=by)
