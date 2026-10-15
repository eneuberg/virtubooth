"""Anthropic (Claude) through the official `anthropic` SDK.

Non-streaming Messages API calls with structured output
(`output_config.format` = a JSON schema per call), 60 s timeout, the SDK's
2 retries (408/409/429/5xx, connection errors) and low effort: this is
labelling and rating, not reasoning. Images go in as base64 JPEG blocks.
`ping` reads the model's entry from the Models API (free) to check the key.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

import anthropic
import httpx2
from anthropic.types import MessageParam

from .. import prompts
from ..ports import DetectedObject
from .base import PhotoLine, ProviderError, TokenUsage, VerdictOut

TIMEOUT_S = 60.0
MAX_RETRIES = 2
# headroom for adaptive thinking (billed as output) plus the JSON answer
MAX_TOKENS = {"detect": 8000, "score": 16000, "verdict": 4000}


class AnthropicProvider:
    id = "anthropic"

    def __init__(
        self,
        api_key: str,
        *,
        http_client: httpx2.Client | None = None,
        base_url: str | None = None,
    ) -> None:
        # an explicit key: the SDK reads no environment or profile credentials
        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=TIMEOUT_S,
            max_retries=MAX_RETRIES,
            http_client=http_client,
        )

    # ------------------------------------------------------------- calls

    def detect(self, image_jpeg: bytes, *, model: str) -> tuple[list[DetectedObject], TokenUsage]:
        image = base64.standard_b64encode(image_jpeg).decode("ascii")
        content: list[Any] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": image},
            },
            {"type": "text", "text": prompts.DETECT_TEXT},
        ]
        data, usage = self._json(
            model, prompts.DETECT_SYSTEM, content, prompts.DETECT_SCHEMA, MAX_TOKENS["detect"]
        )
        return prompts.parse_detection(data, usage), usage

    def score(
        self, prompt: str, lines: Sequence[PhotoLine], *, model: str, relative: bool = False
    ) -> tuple[dict[str, list[float | None]], TokenUsage]:
        text = prompts.score_text(prompt, lines, relative=relative)
        data, usage = self._json(
            model,
            prompts.SCORE_SYSTEM,
            [{"type": "text", "text": text}],
            prompts.SCORE_SCHEMA,
            MAX_TOKENS["score"],
        )
        return prompts.parse_scores(data, usage), usage

    def verdict(
        self, prompt: str, lines: Sequence[PhotoLine], *, model: str
    ) -> tuple[VerdictOut, TokenUsage]:
        data, usage = self._json(
            model,
            prompts.VERDICT_SYSTEM,
            [{"type": "text", "text": prompts.verdict_text(prompt, lines)}],
            prompts.VERDICT_SCHEMA,
            MAX_TOKENS["verdict"],
        )
        return prompts.parse_verdict(data, usage), usage

    def ping(self, model: str) -> TokenUsage:
        try:
            self.client.models.retrieve(model)
        except anthropic.APIError as exc:
            raise _error(exc) from exc
        return TokenUsage()

    # ---------------------------------------------------------- internals

    def _json(
        self, model: str, system: str, content: list[Any], schema: dict[str, Any], max_tokens: int
    ) -> tuple[Any, TokenUsage]:
        messages: list[MessageParam] = [{"role": "user", "content": content}]
        try:
            msg = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except anthropic.APIError as exc:
            raise _error(exc) from exc
        usage = TokenUsage(msg.usage.input_tokens or 0, msg.usage.output_tokens or 0)
        if msg.stop_reason == "refusal":
            raise ProviderError("Die KI hat die Anfrage abgelehnt.", kind="refused", usage=usage)
        if msg.stop_reason == "max_tokens":
            raise ProviderError("Antwort abgeschnitten (zu lang).", kind="bad_output", usage=usage)
        text = next((b.text for b in msg.content if b.type == "text"), None)
        if text is None:
            raise ProviderError("Antwort ohne Text.", kind="bad_output", usage=usage)
        return prompts.parse_json(text, usage), usage


def _error(exc: anthropic.APIError) -> ProviderError:
    """A ProviderError with a short German message (never the request, never the key)."""
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return ProviderError("Der API-Schlüssel wurde abgelehnt.", kind="auth")
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderError("Zu viele Anfragen beim KI-Dienst (Limit).", kind="rate")
    if isinstance(exc, anthropic.NotFoundError):
        return ProviderError("Modell nicht gefunden.", kind="other")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return ProviderError(f"KI-Dienst gestört (HTTP {exc.status_code}).", kind="server")
        return ProviderError(f"Anfrage abgelehnt (HTTP {exc.status_code}).", kind="other")
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderError("Zeitüberschreitung beim KI-Dienst.", kind="network")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("KI-Dienst nicht erreichbar.", kind="network")
    return ProviderError("Unerwartete Antwort des KI-Dienstes.", kind="other")
