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
    # small (Haiku class) | mid (Sonnet class) | large (Opus class): the AI verdict
    # may use the provider's small and mid models
    tier: str = "small"

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
    ModelInfo("claude-sonnet-5-5", "anthropic", "Claude Sonnet 5.5", 2.00, 10.00, tier="mid"),
    ModelInfo(
        "claude-opus-5-5", "anthropic", "Claude Opus 5.5 (am stärksten)", 4.00, 20.00, tier="large"
    ),
    ModelInfo("mistral-small-2506", "mistral", "Mistral Small 3.2 (EU)", 0.10, 0.30),
    ModelInfo("mistral-medium-2508", "mistral", "Mistral Medium 3.1 (EU)", 0.40, 2.00, tier="mid"),
    ModelInfo(
        "claude-haiku-5.5",
        "deutschlandgpt",
        "Claude Haiku 5.5 (günstig, schnell)",
        0.83,
        4.13,
        currency="EUR",
    ),
    ModelInfo(
        "claude-sonnet-5.5",
        "deutschlandgpt",
        "Claude Sonnet 5.5",
        3.30,
        16.50,
        currency="EUR",
        tier="mid",
    ),
    ModelInfo(
        "claude-opus-5.5",
        "deutschlandgpt",
        "Claude Opus 5.5 (am stärksten)",
        6.60,
        33.00,
        currency="EUR",
        tier="large",
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


# ------------------------------------------------------------ AI verdict

VERDICT_TIERS = ("small", "mid")
VERDICT_MODEL_IDS = frozenset(m.id for m in MODELS if m.tier in VERDICT_TIERS)
EFFORTS = ("low", "medium", "high")


def verdict_models(provider: str) -> list[ModelInfo]:
    """The models the AI verdict may use with `provider` (Haiku and Sonnet class),
    cheapest first."""
    return sorted(
        (m for m in models_of(provider) if m.tier in VERDICT_TIERS),
        key=lambda m: VERDICT_TIERS.index(m.tier),
    )


def resolve_verdict_model(provider: str, model: str | None) -> str:
    """The model a category's verdict runs on with `provider`: its own when the
    provider has it, else the provider's model of the same tier (a provider
    change keeps „Haiku“ or „Sonnet“), else the provider's smallest."""
    choices = verdict_models(provider)
    if not choices:
        return DEFAULT_BY_PROVIDER[provider]
    if model is not None:
        if any(m.id == model for m in choices):
            return model
        info = BY_ID.get(model)
        same = [m for m in choices if info is not None and m.tier == info.tier]
        if same:
            return same[0].id
    return choices[0].id


# What one comment costs, estimated from real token counts (October 2026).
#
# Input: the live server's 13 detection calls (Claude Sonnet 5.5, low effort) all billed
# 1631 input tokens: a 768×1024 photo (⌈768·1024/750⌉ = 1049 image tokens) plus 582
# tokens for the 1022 characters of system prompt, task and JSON schema, i.e. 1.756
# characters per token with the structured-output and thinking overhead included. The
# verdict payload for one new winner (system prompt with the guardrails 1043, schema
# 439, task and one photo line with ~6 objects 573 characters: prompts.verdict_text)
# is 2055 characters → 1170 tokens; each further photo in the same call adds a
# 304-character line → 173 tokens.
# Output: the same 13 calls' answers fit `tokens = 0.518 · characters + 2.3` (the
# answers' JSON length from the stored objects; low effort thinks almost nothing). One
# comment as JSON is ~184 characters (a ~95-character sentence) → 98 tokens, each
# further comment 88.
# Effort: there is no verdict call on record yet, nor one with medium or high effort,
# so their thinking is an assumption: +400 (medium) and +1200 (high) output tokens per
# call (thinking is billed as output). Providers without thinking ignore the effort.
# With the comment cache a poll usually comments one new winner per category, so the
# estimate is one call for one comment.
VERDICT_TOKENS_IN = 1170
VERDICT_TOKENS_IN_PER_EXTRA = 173
VERDICT_TOKENS_OUT = 98
VERDICT_TOKENS_OUT_PER_EXTRA = 88
VERDICT_THINKING = {"low": 0, "medium": 400, "high": 1200}
VERDICT_MEASURED = {"low": True, "medium": False, "high": False}


def verdict_tokens(effort: str, comments: int = 1, *, thinking: bool = True) -> tuple[int, int]:
    """(input, output) tokens of one verdict call writing `comments` comments."""
    extra = max(0, comments - 1)
    tokens_in = VERDICT_TOKENS_IN + extra * VERDICT_TOKENS_IN_PER_EXTRA
    tokens_out = VERDICT_TOKENS_OUT + extra * VERDICT_TOKENS_OUT_PER_EXTRA
    if thinking:
        tokens_out += VERDICT_THINKING.get(effort, 0)
    return tokens_in, tokens_out


def verdict_comment_usd(model: str, effort: str, *, thinking: bool = True) -> float:
    """The estimated price of one comment (one call for one new winner) in USD."""
    tokens_in, tokens_out = verdict_tokens(effort, thinking=thinking)
    return cost_micro_usd(model, tokens_in, tokens_out) / 1_000_000
