"""Anthropic (Claude) through the official `anthropic` SDK.

Non-streaming Messages API calls with structured output
(`output_config.format` = a JSON schema per call), the SDK's 2 retries
(408/409/429/5xx, connection errors), adaptive thinking with the configured
effort („Denkaufwand“, default low: this is labelling and rating, not
reasoning). Thinking is billed as output tokens and already counted in
`usage.output_tokens`; more effort gets more `max_tokens` and time. Images go
in as base64 JPEG blocks. `ping` reads the Models API's list (free) to check
the key and asks for one token only when the model is not listed there (an
alias, or DeutschlandGPT, which has no models list).

DeutschlandGPT (deutschlandgpt.py) is this class with its base URL and
`structured = False`.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

import anthropic
import httpx2
from anthropic.types import MessageParam, OutputConfigParam

from .. import prompts
from ..ports import DetectedObject
from .base import (
    KEY_FORBIDDEN,
    KEY_REJECTED,
    PING_PROMPT,
    PhotoLine,
    ProviderError,
    TokenUsage,
    VerdictOut,
    model_unknown,
)

MAX_RETRIES = 2
EFFORTS = ("low", "medium", "high")
# headroom for adaptive thinking (billed as output) plus the JSON answer, per effort
# (non-streaming: at most 16000, so the SDK's request-time limit never trips)
MAX_TOKENS = {
    "low": {"detect": 8000, "score": 16000, "verdict": 4000},
    "medium": {"detect": 12000, "score": 16000, "verdict": 8000},
    "high": {"detect": 16000, "score": 16000, "verdict": 12000},
}
TIMEOUT_S = {"low": 60.0, "medium": 120.0, "high": 180.0}


def _effort(effort: str) -> str:
    return effort if effort in EFFORTS else "low"


class AnthropicProvider:
    id = "anthropic"
    # output_config.format is honoured (the answer is exactly the schema's JSON)
    structured = True
    base_url: str | None = None

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
            base_url=base_url or self.base_url,
            timeout=TIMEOUT_S["low"],
            max_retries=MAX_RETRIES,
            http_client=http_client,
        )

    # ------------------------------------------------------------- calls

    def detect(
        self, image_jpeg: bytes, *, model: str, effort: str = "low"
    ) -> tuple[list[DetectedObject], TokenUsage]:
        image = base64.standard_b64encode(image_jpeg).decode("ascii")
        content: list[Any] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": image},
            },
            {"type": "text", "text": prompts.DETECT_TEXT},
        ]
        data, usage = self._json(
            model, prompts.DETECT_SYSTEM, content, prompts.DETECT_SCHEMA, "detect", effort
        )
        return prompts.parse_detection(data, usage), usage

    def score(
        self,
        prompt: str,
        lines: Sequence[PhotoLine],
        *,
        model: str,
        relative: bool = False,
        effort: str = "low",
    ) -> tuple[dict[str, list[float | None]], TokenUsage]:
        text = prompts.score_text(prompt, lines, relative=relative)
        data, usage = self._json(
            model,
            prompts.SCORE_SYSTEM,
            [{"type": "text", "text": text}],
            prompts.SCORE_SCHEMA,
            "score",
            effort,
        )
        return prompts.parse_scores(data, usage), usage

    def verdict(
        self, prompt: str, lines: Sequence[PhotoLine], *, model: str, effort: str = "low"
    ) -> tuple[list[VerdictOut], TokenUsage]:
        data, usage = self._json(
            model,
            prompts.VERDICT_SYSTEM,
            [{"type": "text", "text": prompts.verdict_text(prompt, lines)}],
            prompts.VERDICT_SCHEMA,
            "verdict",
            effort,
        )
        return prompts.parse_verdict(data, usage), usage

    def ping(self, model: str) -> TokenUsage:
        listed: set[str] = set()
        try:
            listed = {m.id for m in self.client.models.list(limit=1000).data}
        except anthropic.NotFoundError:
            pass  # no models list at this endpoint: the one-token request decides
        except anthropic.APIError as exc:
            raise _error(exc) from exc
        if model in listed or any(m.startswith(model + "-") for m in listed):
            return TokenUsage()
        try:
            msg = self.client.messages.create(
                model=model,
                max_tokens=1,
                messages=[{"role": "user", "content": PING_PROMPT}],
                timeout=TIMEOUT_S["low"],
            )
        except anthropic.NotFoundError:
            raise ProviderError(model_unknown(model), kind="model") from None
        except anthropic.BadRequestError as exc:
            if "model" in str(exc.message).lower():
                raise ProviderError(model_unknown(model), kind="model") from None
            raise _error(exc) from exc
        except anthropic.APIError as exc:
            raise _error(exc) from exc
        return TokenUsage(msg.usage.input_tokens or 0, msg.usage.output_tokens or 0)

    # ---------------------------------------------------------- internals

    def _json(
        self,
        model: str,
        system: str,
        content: list[Any],
        schema: dict[str, Any],
        kind: str,
        effort: str,
    ) -> tuple[Any, TokenUsage]:
        effort = _effort(effort)
        messages: list[MessageParam] = [{"role": "user", "content": content}]
        output_config: OutputConfigParam = {"effort": effort}  # type: ignore[typeddict-item]
        if self.structured:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        else:
            system += prompts.schema_instruction(schema)
        try:
            msg = self.client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS[effort][kind],
                system=system,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config=output_config,
                timeout=TIMEOUT_S[effort],
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
        if self.structured:
            return prompts.parse_json(text, usage), usage
        return prompts.parse_json_loose(text, usage), usage


def _error(exc: anthropic.APIError) -> ProviderError:
    """A ProviderError with a short German message (never the request, never the key)."""
    if isinstance(exc, anthropic.AuthenticationError):
        return ProviderError(KEY_REJECTED, kind="auth")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return ProviderError(KEY_FORBIDDEN, kind="auth")
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderError("Zu viele Anfragen beim KI-Dienst (Limit).", kind="rate")
    if isinstance(exc, anthropic.NotFoundError):
        return ProviderError("Modell beim Anbieter nicht gefunden.", kind="model")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code == 402:
            # DeutschlandGPT: credit used up or the key's spending limit reached
            return ProviderError("Guthaben oder Limit beim KI-Dienst aufgebraucht.", kind="rate")
        if exc.status_code >= 500:
            return ProviderError(f"KI-Dienst gestört (HTTP {exc.status_code}).", kind="server")
        return ProviderError(f"Anfrage abgelehnt (HTTP {exc.status_code}).", kind="other")
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderError("Zeitüberschreitung beim KI-Dienst.", kind="network")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("KI-Dienst nicht erreichbar.", kind="network")
    return ProviderError("Unerwartete Antwort des KI-Dienstes.", kind="other")
