"""DeutschlandGPT: Claude models through its Anthropic-compatible endpoint
(`https://api.deutschlandgpt.de/anthropic`, the Messages API with the
Anthropic SDK), hosted in Germany, billed in EUR (pricing.py).

As immobot found live (github.com/eneuberg/immobot, app/llm.py): the endpoint
takes `thinking: adaptive` and `output_config.effort` but ignores
`output_config.format` on most models, so the JSON schema goes into the system
prompt and the answer is read tolerantly (a code fence, text around the
object). No betas. Model ids use dots (`claude-haiku-5.5`).

Images: not verified through this endpoint, so `ProviderInfo.vision` is off
and object detection / the test image's AI part are refused before a call;
`detect` refuses too, should it be reached anyway.
"""

from __future__ import annotations

from ..ports import DetectedObject
from .anthropic import AnthropicProvider
from .base import ProviderError, TokenUsage

BASE_URL = "https://api.deutschlandgpt.de/anthropic"
NO_VISION = "DeutschlandGPT kann hier keine Fotos ansehen (nicht geprüft)."


class DeutschlandGptProvider(AnthropicProvider):
    id = "deutschlandgpt"
    structured = False
    base_url = BASE_URL

    def detect(
        self, image_jpeg: bytes, *, model: str, effort: str = "low"
    ) -> tuple[list[DetectedObject], TokenUsage]:
        raise ProviderError(NO_VISION, kind="other", usage=TokenUsage())
