"""Models the admin can pick and what they cost per million tokens, in the
provider's currency (`currency`; `usd_*` is that converted to USD).

Anthropic ids and prices: the `claude-api` skill's model table (cached
2026-10-06). Claude Haiku 5.5 costs more above 100K input tokens per request
(`long_*`); the poll's chunks stay far below that. Mistral: list prices as
published by aggregators in October 2026, not confirmed on mistral.ai (see
night/d2/EU-PROVIDER.md) – the meter is an estimate either way.
DeutschlandGPT: EUR net, from its API's pricing field on 2026-10-12 (as
immobot's app/settings.py has them).

Currency: the meter and the budget stay in USD. A EUR price is converted with
the fixed rate EUR_USD (1 € = 1.10 $, immobot's default), so a DeutschlandGPT
call costs its EUR price × 1.10 on the meter; the model list shows the EUR
price the provider bills. Thinking tokens are output tokens (billed and
counted as such), so the output price covers them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 1 € in $ (fixed, documented above): DeutschlandGPT bills in EUR, the meter is USD
EUR_USD = 1.10
RATES = {"USD": 1.0, "EUR": EUR_USD}


@dataclass(frozen=True)
class ModelInfo:
    id: str
    provider: str
    title: str
    # per million tokens in `currency`
    in_mtok: float
    out_mtok: float
    # above this many input tokens in one request the long-context prices apply
    long_from: int | None = None
    long_in_mtok: float | None = None
    long_out_mtok: float | None = None
    currency: str = "USD"

    @property
    def usd_in_mtok(self) -> float:
        return round(self.in_mtok * RATES[self.currency], 6)

    @property
    def usd_out_mtok(self) -> float:
        return round(self.out_mtok * RATES[self.currency], 6)


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
    ModelInfo(
        "claude-haiku-5.5",
        "deutschlandgpt",
        "Claude Haiku 5.5 (günstig, schnell)",
        0.83,
        4.13,
        currency="EUR",
    ),
    ModelInfo(
        "claude-sonnet-5.5", "deutschlandgpt", "Claude Sonnet 5.5", 3.30, 16.50, currency="EUR"
    ),
    ModelInfo(
        "claude-opus-5.5",
        "deutschlandgpt",
        "Claude Opus 5.5 (am stärksten)",
        6.60,
        33.00,
        currency="EUR",
    ),
    ModelInfo(
        "deepseek-v4.1-flash",
        "scaleway",
        "DeepSeek V4.1 Flash (EU, schnell)",
        0.60,
        1.80,
        currency="EUR",
    ),
)

BY_ID = {m.id: m for m in MODELS}
DEFAULT_BY_PROVIDER = {
    "anthropic": DEFAULT_MODEL,
    "mistral": "mistral-small-2506",
    "deutschlandgpt": "claude-haiku-5.5",
    "scaleway": "deepseek-v4.1-flash",
}


def models_of(provider: str) -> list[ModelInfo]:
    return [m for m in MODELS if m.provider == provider]


def cost_micro_usd(model: str, input_tokens: int, output_tokens: int) -> int:
    """The estimated price of one request in millionths of a dollar (rounded up,
    so a meter never shows a paid call as free; EUR converted at EUR_USD).
    `output_tokens` includes thinking. Unknown models cost nothing."""
    info = BY_ID.get(model)
    if info is None:
        return 0
    rate_in, rate_out = info.in_mtok, info.out_mtok
    if info.long_from is not None and input_tokens > info.long_from:
        rate_in = info.long_in_mtok or rate_in
        rate_out = info.long_out_mtok or rate_out
    # per million tokens == micro-units per token
    micro = (max(0, input_tokens) * rate_in + max(0, output_tokens) * rate_out) * RATES[
        info.currency
    ]
    return math.ceil(round(micro, 6))
