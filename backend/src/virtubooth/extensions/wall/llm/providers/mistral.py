"""Mistral AI (La Plateforme, hosted in the EU) over plain HTTP.

Chat Completions with JSON-schema output (`response_format` json_schema,
strict), images as base64 data URLs. Same timeout and retry policy as the
Anthropic provider (60 s; 2 retries on 408/409/429/5xx and connection
errors). `ping` reads the models list (free) and asks for one token only when the
model is not listed. See night/d2/EU-PROVIDER.md
for why this provider exists and what is unverified.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Sequence
from typing import Any, ClassVar

import httpx2

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

BASE_URL = "https://api.mistral.ai/v1"
TIMEOUT_S = 60.0
MAX_RETRIES = 2
RETRY_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
MAX_TOKENS = {"detect": 4000, "score": 16000, "verdict": 1000}


class MistralProvider:
    id = "mistral"
    # extra fields for the one-token ping request (Scaleway: thinking off)
    ping_extra: ClassVar[dict[str, Any]] = {}

    def __init__(
        self,
        api_key: str,
        *,
        http_client: httpx2.Client | None = None,
        base_url: str = BASE_URL,
        retry_wait_s: float = 1.0,
    ) -> None:
        self._client = http_client or httpx2.Client(timeout=TIMEOUT_S)
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._base = base_url.rstrip("/")
        self._wait = retry_wait_s

    # no thinking here: `effort` is accepted and ignored

    def detect(
        self, image_jpeg: bytes, *, model: str, effort: str = "low"
    ) -> tuple[list[DetectedObject], TokenUsage]:
        url = "data:image/jpeg;base64," + base64.standard_b64encode(image_jpeg).decode("ascii")
        content = [
            {"type": "text", "text": prompts.DETECT_TEXT},
            {"type": "image_url", "image_url": url},
        ]
        data, usage = self._json(
            model, prompts.DETECT_SYSTEM, content, "objects", prompts.DETECT_SCHEMA, "detect"
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
            model, prompts.SCORE_SYSTEM, text, "scores", prompts.SCORE_SCHEMA, "score"
        )
        return prompts.parse_scores(data, usage), usage

    def verdict(
        self, prompt: str, lines: Sequence[PhotoLine], *, model: str, effort: str = "low"
    ) -> tuple[VerdictOut, TokenUsage]:
        text = prompts.verdict_text(prompt, lines)
        data, usage = self._json(
            model, prompts.VERDICT_SYSTEM, text, "verdict", prompts.VERDICT_SCHEMA, "verdict"
        )
        return prompts.parse_verdict(data, usage), usage

    def ping(self, model: str) -> TokenUsage:
        r = self._send("GET", "/models", None)
        if r.status_code == 404:
            raise ProviderError(
                "Adresse des KI-Dienstes nicht gefunden (HTTP 404): Basis-URL bzw. Projekt prüfen.",
                kind="other",
            )
        if r.status_code >= 400:
            raise _status_error(r.status_code)
        try:
            listed = {str(m.get("id")) for m in r.json().get("data") or [] if isinstance(m, dict)}
        except (ValueError, AttributeError):
            listed = set()
        if model in listed:
            return TokenUsage()
        # not in the list (or no list): one token tells whether the model answers
        body = {
            "model": model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": PING_PROMPT}],
            **self.ping_extra,
        }
        r = self._send("POST", "/chat/completions", body)
        if r.status_code == 404 or (r.status_code in (400, 422) and "model" in r.text.lower()):
            raise ProviderError(model_unknown(model), kind="model")
        if r.status_code >= 400:
            raise _status_error(r.status_code)
        try:
            raw = r.json().get("usage") or {}
        except (ValueError, AttributeError):
            raw = {}
        return TokenUsage(
            int(raw.get("prompt_tokens") or 0), int(raw.get("completion_tokens") or 0)
        )

    # ---------------------------------------------------------- internals

    def _json(
        self,
        model: str,
        system: str,
        content: str | list[dict[str, Any]],
        name: str,
        schema: dict[str, Any],
        kind: str,
    ) -> tuple[Any, TokenUsage]:
        body = {
            "model": model,
            "max_tokens": MAX_TOKENS[kind],
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "schema": schema, "strict": True},
            },
        }
        answer = self._request("POST", "/chat/completions", body)
        raw_usage = answer.get("usage") if isinstance(answer, dict) else None
        usage = TokenUsage(
            int((raw_usage or {}).get("prompt_tokens") or 0),
            int((raw_usage or {}).get("completion_tokens") or 0),
        )
        try:
            choice = answer["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Antwort ohne Inhalt.", kind="bad_output", usage=usage) from None
        if choice.get("finish_reason") == "length":
            raise ProviderError("Antwort abgeschnitten (zu lang).", kind="bad_output", usage=usage)
        if not isinstance(text, str):
            raise ProviderError("Antwort ohne Text.", kind="bad_output", usage=usage)
        return prompts.parse_json(text, usage), usage

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> Any:
        r = self._send(method, path, body)
        if r.status_code >= 400:
            raise _status_error(r.status_code)
        try:
            return r.json()
        except ValueError:
            raise ProviderError("Antwort war kein gültiges JSON.", kind="bad_output") from None

    def _send(self, method: str, path: str, body: dict[str, Any] | None) -> httpx2.Response:
        """The response, after retrying 408/409/429/5xx and connection errors;
        ProviderError (`network`) when the service cannot be reached."""
        for attempt in range(MAX_RETRIES + 1):
            last = attempt == MAX_RETRIES
            try:
                r = self._client.request(
                    method,
                    self._base + path,
                    headers=self._headers,
                    content=None if body is None else json.dumps(body),
                    timeout=TIMEOUT_S,
                )
            except httpx2.TimeoutException:
                if last:
                    raise ProviderError(
                        "Zeitüberschreitung beim KI-Dienst.", kind="network"
                    ) from None
            except httpx2.HTTPError:
                if last:
                    raise ProviderError("KI-Dienst nicht erreichbar.", kind="network") from None
            else:
                if r.status_code not in RETRY_STATUS or last:
                    return r
            time.sleep(self._wait * (2**attempt))
        raise ProviderError("KI-Dienst nicht erreichbar.", kind="network")  # pragma: no cover


def _status_error(status: int) -> ProviderError:
    if status == 401:
        return ProviderError(KEY_REJECTED, kind="auth")
    if status == 403:
        return ProviderError(KEY_FORBIDDEN, kind="auth")
    if status == 429:
        return ProviderError("Zu viele Anfragen beim KI-Dienst (Limit).", kind="rate")
    if status == 404:
        return ProviderError("Modell beim Anbieter nicht gefunden.", kind="model")
    if status >= 500:
        return ProviderError(f"KI-Dienst gestört (HTTP {status}).", kind="server")
    return ProviderError(f"Anfrage abgelehnt (HTTP {status}).", kind="other")
