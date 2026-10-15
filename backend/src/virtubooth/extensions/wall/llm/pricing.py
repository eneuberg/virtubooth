"""Models the admin can pick and what they cost (USD per million tokens).

Anthropic ids and prices: the `claude-api` skill's model table (cached
2026-10-06). Claude Haiku 5.5 costs more above 100K input tokens per request
(`long_*`); the poll's chunks stay far below that. Mistral: list prices as
published by aggregators in October 2026, not confirmed on mistral.ai (see
night/d2/EU-PROVIDER.md) – the meter is an estimate either way.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    id: str
    provider: str
    title: str
    usd_in_mtok: float
    usd_out_mtok: float
    # above this many input tokens in one request the long-context prices apply
    long_from: int | None = None
    long_in_mtok: float | None = None
    long_out_mtok: float | None = None


DEFAULT_MODEL = "claude-haiku-5-5"

MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        "claude-haiku-5-5",
        "anthropic",
        "Claude Haiku 5.5 (günstig, schnell)",
        0.10,
        0.50,
        long_from=100_000,
        long_in_mtok=0.50,
        long_out_mtok=2.50,
    ),
    ModelInfo("claude-sonnet-5-5", "anthropic", "Claude Sonnet 5.5", 2.00, 10.00),
    ModelInfo("claude-opus-5-5", "anthropic", "Claude Opus 5.5 (am stärksten)", 4.00, 20.00),
    ModelInfo("mistral-small-2506", "mistral", "Mistral Small 3.2 (EU)", 0.10, 0.30),
    ModelInfo("mistral-medium-2508", "mistral", "Mistral Medium 3.1 (EU)", 0.40, 2.00),
)

BY_ID = {m.id: m for m in MODELS}
DEFAULT_BY_PROVIDER = {"anthropic": DEFAULT_MODEL, "mistral": "mistral-small-2506"}


def models_of(provider: str) -> list[ModelInfo]:
    return [m for m in MODELS if m.provider == provider]


def cost_micro_usd(model: str, input_tokens: int, output_tokens: int) -> int:
    """The estimated price of one request in millionths of a dollar (rounded up,
    so a meter never shows a paid call as free). Unknown models cost nothing."""
    info = BY_ID.get(model)
    if info is None:
        return 0
    rate_in, rate_out = info.usd_in_mtok, info.usd_out_mtok
    if info.long_from is not None and input_tokens > info.long_from:
        rate_in = info.long_in_mtok or rate_in
        rate_out = info.long_out_mtok or rate_out
    # USD per million tokens == micro-USD per token
    micro = max(0, input_tokens) * rate_in + max(0, output_tokens) * rate_out
    return math.ceil(round(micro, 6))
