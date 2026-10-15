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


PROVIDERS: tuple[ProviderInfo, ...] = (
    ProviderInfo("anthropic", "Anthropic (Claude, USA)", eu=False, source="claude"),
    ProviderInfo("mistral", "Mistral AI (EU)", eu=True, source="mistral"),
)
BY_ID = {p.id: p for p in PROVIDERS}


def make_provider(provider_id: str, api_key: str) -> Provider:
    if provider_id == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider(api_key)
    if provider_id == "mistral":
        from .mistral import MistralProvider

        return MistralProvider(api_key)
    raise ProviderError(f"unknown provider {provider_id!r}", kind="other")


__all__ = ["BY_ID", "PROVIDERS", "Provider", "ProviderError", "ProviderInfo", "make_provider"]
