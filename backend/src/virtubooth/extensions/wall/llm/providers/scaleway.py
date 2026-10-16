"""Scaleway Generative APIs (Paris, EU): DeepSeek V4.1 Flash over the
OpenAI-compatible Chat Completions API, thinking off (`reasoning_effort: none`).

Tested by the host (florence2_detect handoff, 2026-10-15): boxes are asked for as
coordinates normalised to 0–1000 (pixel coordinates landed off), the answer is
JSON in text (no `response_format`), and the model does not always keep the
schema („coordinates“ instead of „box“, the box under „label“), so the parser
takes any list of four numbers as the box and the first string as the label.
About 1 s and 0.09 ct per photo. `VB_SCALEWAY_BASE_URL` may point at a project
(`https://api.scaleway.ai/<project-id>/v1`); the default uses the key's default
project.
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, ClassVar

from .. import prompts
from ..ports import DetectedObject
from .base import ProviderError, TokenUsage
from .mistral import MistralProvider

BASE_URL = "https://api.scaleway.ai/v1"
DETECT_PROMPT = (
    "Detect all objects in the image. Return ONLY a JSON array, no prose: "
    '[{"label": str, "box": [x1, y1, x2, y2]}] '
    "with coordinates normalized to 0-1000 relative to image width/height."
)
MAX_OBJECTS = 100
_ARRAY = re.compile(r"\[.*\]", re.S)


class ScalewayProvider(MistralProvider):
    id = "scaleway"
    ping_extra: ClassVar[dict[str, Any]] = {"reasoning_effort": "none"}

    def __init__(self, api_key: str, **kwargs: Any) -> None:
        kwargs.setdefault("base_url", os.environ.get("VB_SCALEWAY_BASE_URL") or BASE_URL)
        super().__init__(api_key, **kwargs)

    def detect(
        self, image_jpeg: bytes, *, model: str, effort: str = "low"
    ) -> tuple[list[DetectedObject], TokenUsage]:
        url = "data:image/jpeg;base64," + base64.standard_b64encode(image_jpeg).decode("ascii")
        body = {
            "model": model,
            "max_tokens": 8192,
            "temperature": 0,
            "reasoning_effort": "none",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": url}},
                        {"type": "text", "text": DETECT_PROMPT},
                    ],
                }
            ],
        }
        text, usage = self._text(body)
        return parse_boxes(text, usage), usage

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
            "max_tokens": 8192,
            "temperature": 0,
            "reasoning_effort": "none",
            "messages": [
                {"role": "system", "content": system + prompts.schema_instruction(schema)},
                {"role": "user", "content": content},
            ],
        }
        text, usage = self._text(body)
        return prompts.parse_json_loose(text, usage), usage

    def _text(self, body: dict[str, Any]) -> tuple[str, TokenUsage]:
        answer = self._request("POST", "/chat/completions", body)
        raw = answer.get("usage") if isinstance(answer, dict) else None
        usage = TokenUsage(
            int((raw or {}).get("prompt_tokens") or 0),
            int((raw or {}).get("completion_tokens") or 0),
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
        return text, usage


def parse_boxes(text: str, usage: TokenUsage) -> list[DetectedObject]:
    """The first JSON array in the answer, read tolerantly: any list of four numbers
    is the box (0–1000, clamped), the first string the label."""
    match = _ARRAY.search(text)
    if not match:
        raise ProviderError("Antwort ohne Objektliste.", kind="bad_output", usage=usage)
    try:
        items = json.loads(match.group(0))
    except ValueError:
        raise ProviderError(
            "Antwort war kein gültiges JSON.", kind="bad_output", usage=usage
        ) from None
    out: list[DetectedObject] = []
    for item in items if isinstance(items, list) else []:
        values = list(item.values()) if isinstance(item, dict) else []
        box = next(
            (
                v
                for v in values
                if isinstance(v, list)
                and len(v) == 4
                and all(isinstance(n, int | float) and not isinstance(n, bool) for n in v)
            ),
            None,
        )
        label = next((v.strip() for v in values if isinstance(v, str) and v.strip()), None)
        if box is None or label is None:
            continue
        x1, y1, x2, y2 = (min(max(float(n), 0.0), 1000.0) / 1000 for n in box)
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        if x2 - x1 <= 0 or y2 - y1 <= 0:
            continue
        name = label.lower()[:60]
        out.append(DetectedObject(name, label[:60], 1.0, (x1, y1, x2 - x1, y2 - y1)))
        if len(out) >= MAX_OBJECTS:
            break
    return out
