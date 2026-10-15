"""Scaleway (DeepSeek V4.1 Flash): request shape, 0–1000 boxes, tolerant parsing."""

from __future__ import annotations

import json

import httpx2
import pytest

from virtubooth.extensions.wall.llm.providers import BY_ID, make_provider
from virtubooth.extensions.wall.llm.providers.base import ProviderError, TokenUsage
from virtubooth.extensions.wall.llm.providers.scaleway import ScalewayProvider, parse_boxes


def answer(text: str) -> dict:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 700, "completion_tokens": 120},
    }


def test_detect_sends_the_tested_request_and_reads_normalised_boxes():
    seen: list[dict] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append({"url": str(request.url), "auth": request.headers["authorization"],
                     "body": json.loads(request.content)})  # fmt: skip
        return httpx2.Response(200, json=answer(
            'Here: [{"label": "person", "box": [100, 200, 500, 1000]},'
            ' {"coordinates": [0, 0, 250, 250], "label": "Bottle"}]'
        ))  # fmt: skip

    p = ScalewayProvider("k", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    objs, usage = p.detect(b"\xff\xd8jpeg", model="deepseek-v4.1-flash")
    body = seen[0]["body"]
    assert seen[0]["url"] == "https://api.scaleway.ai/v1/chat/completions"
    assert seen[0]["auth"] == "Bearer k"
    assert body["reasoning_effort"] == "none" and body["temperature"] == 0
    assert "response_format" not in body
    assert body["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/jpeg")
    assert usage == TokenUsage(700, 120)
    assert [(o.label, o.box) for o in objs] == [
        ("person", (0.1, 0.2, 0.4, 0.8)),
        ("bottle", (0.0, 0.0, 0.25, 0.25)),
    ]


def test_parse_boxes_is_tolerant_and_clamps():
    objs = parse_boxes(
        '[{"label": [10, 10, 2000, 500], "name": "Hat"}, {"label": "x"}, {"box": [5, 5, 5, 9], "label": "flat"}]',
        TokenUsage(),
    )
    assert [(o.label, o.box) for o in objs] == [("hat", (0.01, 0.01, 0.99, 0.49))]
    with pytest.raises(ProviderError):
        parse_boxes("no objects here", TokenUsage())


def test_registered_with_vision_and_a_base_url_override(monkeypatch):
    info = BY_ID["scaleway"]
    assert info.vision and info.eu and info.currency == "EUR" and info.source == "scaleway"
    monkeypatch.setenv("VB_SCALEWAY_BASE_URL", "https://api.scaleway.ai/project-x/v1")
    p = make_provider("scaleway", "k")
    assert isinstance(p, ScalewayProvider) and p._base == "https://api.scaleway.ai/project-x/v1"
