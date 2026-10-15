"""LLM providers behind one interface (`base.Provider`).

`make_provider(provider_id, api_key)` builds the client for the configured
provider; `PROVIDERS` lists what the admin can choose."""

from __future__ import annotations

from dataclasses import dataclass

from .base import Provider, ProviderError


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    title: str
    eu: bool
    # the source name in photo_objects / photo_detection_runs
    source: str
    # who and where, for the guests' privacy text („Mehr dazu“)
    privacy: str
    # can look at photos (object detection, the test image): only when verified
    vision: bool = True
    # adaptive thinking with a „Denkaufwand“ (config.effort)
    thinking: bool = False
    # what the provider bills in (pricing.py converts to the meter's USD)
    currency: str = "USD"


PROVIDERS: tuple[ProviderInfo, ...] = (
    ProviderInfo(
        "anthropic",
        "Anthropic (Claude, USA)",
        eu=False,
        source="claude",
        privacy="Anthropic, USA",
        thinking=True,
    ),
    ProviderInfo("mistral", "Mistral AI (EU)", eu=True, source="mistral", privacy="Mistral AI, EU"),
    # Claude models through DeutschlandGPT's Anthropic-compatible endpoint, billed in
    # EUR. Images through that endpoint are not verified (immobot sends listing photos
    # there, but nothing confirms the endpoint passes them on): poll only for now.
    ProviderInfo(
        "deutschlandgpt",
        "DeutschlandGPT (Claude, Deutschland)",
        eu=True,
        source="deutschlandgpt",
        privacy="DeutschlandGPT, Deutschland",
        vision=False,
        thinking=True,
        currency="EUR",
    ),
    # DeepSeek V4.1 Flash on Scaleway (Paris), thinking off; boxes as 0–1000
    # coordinates, tested by the host (about 1 s and 0.09 ct per photo)
    ProviderInfo(
        "scaleway",
        "Scaleway (DeepSeek, EU)",
        eu=True,
        source="scaleway",
        privacy="Scaleway, Frankreich (EU)",
        currency="EUR",
    ),
)
BY_ID = {p.id: p for p in PROVIDERS}


def make_provider(provider_id: str, api_key: str) -> Provider:
    if provider_id == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider(api_key)
    if provider_id == "mistral":
        from .mistral import MistralProvider

        return MistralProvider(api_key)
    if provider_id == "deutschlandgpt":
        from .deutschlandgpt import DeutschlandGptProvider

        return DeutschlandGptProvider(api_key)
    if provider_id == "scaleway":
        from .scaleway import ScalewayProvider

        return ScalewayProvider(api_key)
    raise ProviderError(f"unknown provider {provider_id!r}", kind="other")


__all__ = ["BY_ID", "PROVIDERS", "Provider", "ProviderError", "ProviderInfo", "make_provider"]
