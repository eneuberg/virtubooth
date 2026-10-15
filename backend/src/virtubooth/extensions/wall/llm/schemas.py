"""Request and response models of the LLM admin API (PLAN-NIGHT §4.4)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import BudgetConfig, LlmConfig, ProviderId


class KeyOut(BaseModel):
    """Never the key itself: whether one is stored, and whether it can be read."""

    set: bool
    set_at: str | None
    provider: str | None
    valid: bool = Field(description="False: stored but unreadable (VB_SECRET_KEY changed).")


class KeyIn(BaseModel):
    provider: ProviderId
    key: str = Field(description="At most 400 characters, no whitespace. Write-only.")


class KeyTestOut(BaseModel):
    ok: bool
    message: str


class ProviderOut(BaseModel):
    id: str
    title: str
    eu: bool = Field(description="Hosted in the EU.")
    available: bool
    reason: str | None


class ModelOut(BaseModel):
    id: str
    provider: str
    title: str
    usd_in_mtok: float
    usd_out_mtok: float


class PollerOut(BaseModel):
    state: Literal["off", "idle", "running", "blocked"]
    last_poll_at: str | None
    next_poll_at: str | None
    last_error: str | None


class DetectionOut(BaseModel):
    pending: int = Field(description="Photos the external detector will still look at.")
    done: int
    failed: int


class UsageTotals(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class UsageByKind(BaseModel):
    kind: str = Field(description="detect | property | verdict | test")
    ref: str | None = Field(description="Property name, category id or photo id.")
    calls: int
    tokens: int
    cost_usd: float


class Usage(BaseModel):
    party: UsageTotals
    today: UsageTotals
    by_kind: list[UsageByKind]
    budget: BudgetConfig
    blocked: bool
    reason: str | None = Field(description="„Budget erreicht – externe KI pausiert …“")


class LlmStatus(BaseModel):
    config: LlmConfig
    key: KeyOut
    providers: list[ProviderOut]
    models: list[ModelOut]
    poller: PollerOut
    detection: DetectionOut
    usage: Usage


class PropertyIn(BaseModel):
    name: str = Field(description="^[a-z][a-z0-9_]{1,30}$, immutable")
    prompt: str = Field(description="1–2000 characters, immutable")


class PropertyOut(BaseModel):
    id: int
    name: str
    prompt: str
    created_at: str
    archived_at: str | None
    scored_photos: int
    last_scored_at: str | None


class PropertiesOut(BaseModel):
    properties: list[PropertyOut]


class PollOut(BaseModel):
    started: bool
    reason: str | None


class BoxOut(BaseModel):
    x: float
    y: float
    w: float
    h: float


class ObjectOut(BaseModel):
    label: str
    label_de: str
    score: float
    box: BoxOut | None


class TestRunOut(BaseModel):
    """The local pipeline's result on the test image (D1's TestRun)."""

    __test__ = False  # not a pytest class

    width: int
    height: int
    facts: dict[str, float]
    boxes: list[dict[str, Any]]
    details: list[dict[str, Any]]
    objects: list[ObjectOut]
    durations_ms: dict[str, int]
    error: str | None


class ExternalTestOut(BaseModel):
    objects: list[ObjectOut]
    usage: UsageTotals | None
    error: str | None


class TestImageOut(BaseModel):
    __test__ = False  # not a pytest class

    width: int
    height: int
    local: TestRunOut | None
    external: ExternalTestOut | None
