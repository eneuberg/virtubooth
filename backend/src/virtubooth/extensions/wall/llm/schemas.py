"""Request and response models of the LLM admin API (PLAN-NIGHT §4.4)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .config import BudgetConfig, LlmConfig, ProviderId


class KeyOut(BaseModel):
    """Never the key itself: whether one is stored for `provider`, and whether it
    can be read. One key per provider."""

    set: bool
    set_at: str | None
    provider: str | None
    valid: bool = Field(description="False: stored but unreadable (VB_SECRET_KEY changed).")


class KeyIn(BaseModel):
    provider: ProviderId
    key: str = Field(description="At most 400 characters, no whitespace. Write-only.")


class KeyTestIn(BaseModel):
    """`POST /llm/key/test`: which provider's key to test, with which model
    (defaults: the configured provider; its configured or default model)."""

    provider: ProviderId | None = None
    model: str | None = None


class KeyTestOut(BaseModel):
    ok: bool
    message: str


class ProviderOut(BaseModel):
    id: str
    title: str
    eu: bool = Field(description="Hosted in the EU.")
    available: bool
    reason: str | None
    vision: bool = Field(description="Can look at photos (object detection, test image).")
    thinking: bool = Field(description="Takes a „Denkaufwand“ (config.effort).")
    currency: str = Field(description="What it bills in: USD | EUR.")


class ModelOut(BaseModel):
    id: str
    provider: str
    title: str
    usd_in_mtok: float = Field(description="Per million input tokens, converted to USD.")
    usd_out_mtok: float
    currency: str = Field(description="The provider's currency (USD | EUR).")
    price_in_mtok: float = Field(description="Per million input tokens in `currency`.")
    price_out_mtok: float


class PollerOut(BaseModel):
    """„Eigenschaften abfragen“ (properties and verdicts): its own state and error."""

    state: Literal["off", "idle", "running", "blocked"]
    last_poll_at: str | None
    next_poll_at: str | None
    last_error: str | None = Field(description="The poll's last error (not the detection's).")


class DetectStatsOut(BaseModel):
    """Every detection call so far (like an analyzer's stats, but from `llm_usage`)."""

    processed: int
    errors: int
    avg_ms: float | None
    last_ms: float | None


class DetectionOut(BaseModel):
    """„Objekte mit KI“ (a step of the pipeline while it is the active detector)."""

    mode: Literal["local", "ai", "off"] = Field(
        description="The object detection: the local detector, the external AI or none "
        "(either/or; `ai` also while the master switch is off, then nothing runs)."
    )
    state: Literal["off", "idle", "running", "blocked"] = Field(
        description="off: not the active detector (or external AI off, no key); running: a "
        "photo is out."
    )
    pending: int = Field(description="Photos the external detector will still look at.")
    done: int
    failed: int
    last_run_at: str | None = Field(description="When the detector last finished a photo.")
    last_error: str | None = Field(description="The detection's last error (provider trouble).")
    fallback: int = Field(
        description="Photos whose objects come from the local detector in place of the AI "
        "(it could not deliver them: no key, key rejected, budget, provider down, an error)."
    )
    fallback_reason: str | None = Field(description="Why, for the latest of them (German).")
    fallback_now: str | None = Field(
        description="While the AI is the detector but the local one stands in for new "
        "photos: why (German); None while the AI takes them."
    )
    stats: DetectStatsOut
    cost_usd: float = Field(description="What detection has cost so far (estimate).")
    ai_unavailable: str | None = Field(
        description="Why „KI“ cannot be chosen right now (German: external AI off, no key "
        "for the provider, key rejected, budget, no vision); None while it can."
    )
    notice: str | None = Field(
        description="Why the choice switched from „KI“ to „Lokal“ by itself (the AI became "
        "unavailable); cleared when the host chooses again."
    )
    notice_at: str | None = None


class ObjectDetectionIn(BaseModel):
    mode: Literal["local", "ai", "off"]


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


class VerdictEffortOut(BaseModel):
    effort: Literal["low", "medium", "high"]
    input_tokens: int = Field(description="Estimated per comment (one call, one new winner).")
    output_tokens: int = Field(description="Including thinking (billed as output).")
    usd_per_comment: float = Field(description="Estimated price of one comment in USD.")
    price_per_comment: float = Field(description="The same in the model's `currency`.")
    measured: bool = Field(
        description="From real token counts (low effort); false: the thinking is an "
        "assumption (pricing.py)."
    )


class VerdictModelOut(BaseModel):
    id: str
    title: str
    tier: Literal["small", "mid"] = Field(description="small: Haiku class, mid: Sonnet class.")
    currency: str
    efforts: list[VerdictEffortOut]


class VerdictOptionsOut(BaseModel):
    """What the AI verdict of a category can use with the configured provider."""

    system_prompt: str = Field(description="Always sent: style and guardrails (English).")
    default_prompt: str = Field(
        description="The host's task when a category has none; `{title}` is its title."
    )
    default_model: str = Field(description="The provider's cheapest (`model: null`).")
    max_chars: int = Field(description="What a comment may be long (the prompt asks ≤ 120).")
    thinking: bool = Field(description="The provider takes an effort („Denkaufwand“).")
    models: list[VerdictModelOut] = Field(description="The configured provider's choices.")
    basis: str = Field(description="How the price is estimated (German).")


class LlmStatus(BaseModel):
    config: LlmConfig
    key: KeyOut = Field(description="The configured provider's key.")
    keys: list[KeyOut] = Field(description="Every provider's key state (one key each).")
    providers: list[ProviderOut]
    models: list[ModelOut]
    poller: PollerOut
    detection: DetectionOut
    usage: Usage
    verdict: VerdictOptionsOut


class PropertyIn(BaseModel):
    name: str = Field(description="^[a-z][a-z0-9_]{1,30}$, immutable")
    prompt: str = Field(description="1–2000 characters, immutable")


class PropertyUser(BaseModel):
    id: str = Field(description="The category's id.")
    title: str
    enabled: bool


class PropertyOut(BaseModel):
    id: int
    name: str
    prompt: str
    created_at: str
    status: Literal["polled", "idle", "paused", "trashed"] = Field(
        description="Derived, never stored: polled (an enabled category reads it and the AI "
        "is ready), idle („ruht“: no enabled category reads it), paused (the external AI is "
        "not ready), trashed (in the Papierkorb; scores stay readable)."
    )
    used_by: list[PropertyUser] = Field(description="The categories that read it.")
    deleted_at: str | None = Field(
        description="In the Papierkorb since (not polled, hidden from the editor); null = "
        "not in the Papierkorb. Trashing switches the enabled categories that read it off."
    )
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
    # analyzer → why it did not run (switched off, model missing, ...)
    skipped: dict[str, str] = Field(default_factory=dict)


class ExternalTestOut(BaseModel):
    source: str = Field(description="claude | mistral")
    model: str
    objects: list[ObjectOut]
    usage: UsageTotals | None
    error: str | None


class MergedObjectOut(ObjectOut):
    """An entry of the merged list (what the poll would rate)."""

    idx: int
    sources: list[str] = Field(description="local and/or the AI's source (claude | mistral).")
    local_pos: int | None = Field(description="Its object in `local.objects`, if any.")
    ai_pos: int | None = Field(description="Its object in `external.objects`, if any.")


class TestImageOut(BaseModel):
    __test__ = False  # not a pytest class

    width: int
    height: int
    local: TestRunOut | None
    external: ExternalTestOut | None
    merged: list[MergedObjectOut] = Field(
        description="Both lists merged as a photo's would be (local first, the AI's linked "
        "or appended)."
    )
