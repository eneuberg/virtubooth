"""„Testen“: every provider's `ping` on a fake HTTP transport. The key is checked
with the models list (free); a model not listed there (an alias, an endpoint
without a list such as DeutschlandGPT) is asked for one token. The errors say
what is wrong: key rejected, no access/project, model unknown, address wrong,
unreachable. No network."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx2
import pytest

from virtubooth.extensions.wall.llm.providers.anthropic import AnthropicProvider
from virtubooth.extensions.wall.llm.providers.base import ProviderError
from virtubooth.extensions.wall.llm.providers.deutschlandgpt import DeutschlandGptProvider
from virtubooth.extensions.wall.llm.providers.mistral import MistralProvider
from virtubooth.extensions.wall.llm.providers.scaleway import ScalewayProvider

KEY = "test-key-0123456789"
Handler = Callable[[httpx2.Request], httpx2.Response]


class Api:
    """A fake provider API: the models list and a chat endpoint, recording requests."""

    def __init__(self, models: list[str], *, chat_status: int = 200, chat_error: str = "x",
                 list_status: int = 200) -> None:  # fmt: skip
        self.models = models
        self.chat_status = chat_status
        self.chat_error = chat_error
        self.list_status = list_status
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.endswith("/models"):
            if self.list_status != 200:
                return self._error(self.list_status, "nope")
            return httpx2.Response(200, json={
                "data": [{"id": m, "type": "model", "display_name": m,
                          "created_at": "2026-09-01T00:00:00Z"} for m in self.models],
                "object": "list", "has_more": False, "first_id": None, "last_id": None,
            })  # fmt: skip
        if self.chat_status != 200:
            return self._error(self.chat_status, self.chat_error)
        body = json.loads(request.content)
        if path.endswith("/messages"):
            return httpx2.Response(200, json={
                "id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                "content": [{"type": "text", "text": "O"}], "stop_reason": "max_tokens",
                "stop_sequence": None, "usage": {"input_tokens": 9, "output_tokens": 1},
            })  # fmt: skip
        return httpx2.Response(200, json={
            "choices": [{"message": {"content": "O"}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 1},
        })  # fmt: skip

    @staticmethod
    def _error(status: int, message: str) -> httpx2.Response:
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": "x", "message": message},
                          "message": message, "detail": message}
        )  # fmt: skip

    def paths(self) -> list[tuple[str, str]]:
        return [(r.method, r.url.path) for r in self.requests]


def client(api: Handler) -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(api))


def openai_like(cls: type[MistralProvider], api: Api) -> MistralProvider:
    return cls(KEY, http_client=client(api), retry_wait_s=0)


def anthropic_like(cls: type[AnthropicProvider], api: Api) -> AnthropicProvider:
    provider = cls(KEY, http_client=client(api))
    provider.client = provider.client.with_options(max_retries=0)
    return provider


# ------------------------------------------------------- Mistral, Scaleway


@pytest.mark.parametrize(
    ("cls", "model", "base"),
    [
        (MistralProvider, "mistral-small-2506", "/v1"),
        (ScalewayProvider, "deepseek-v4.1-flash", "/v1"),
    ],
)
def test_a_listed_model_needs_only_the_free_list(cls, model, base):
    api = Api([model, "other"])
    assert openai_like(cls, api).ping(model).input_tokens == 0
    assert api.paths() == [("GET", f"{base}/models")]
    assert api.requests[0].headers["authorization"] == f"Bearer {KEY}"


def test_scaleway_pings_its_own_address_with_thinking_off():
    """Scaleway serves no `GET /models/{id}` (that was the „Modell nicht gefunden“):
    the list, and for a model not in it one token without thinking."""
    api = Api(["llama-3.3-70b-instruct"])
    usage = openai_like(ScalewayProvider, api).ping("deepseek-v4.1-flash")
    assert (usage.input_tokens, usage.output_tokens) == (8, 1)
    assert [str(r.url) for r in api.requests] == [
        "https://api.scaleway.ai/v1/models",
        "https://api.scaleway.ai/v1/chat/completions",
    ]
    body = json.loads(api.requests[1].content)
    assert body["model"] == "deepseek-v4.1-flash" and body["max_tokens"] == 1
    assert body["reasoning_effort"] == "none"


def test_scaleway_project_address(monkeypatch):
    monkeypatch.setenv("VB_SCALEWAY_BASE_URL", "https://api.scaleway.ai/project-x/v1/")
    api = Api(["deepseek-v4.1-flash"])
    openai_like(ScalewayProvider, api).ping("deepseek-v4.1-flash")
    assert str(api.requests[0].url) == "https://api.scaleway.ai/project-x/v1/models"


@pytest.mark.parametrize(
    ("chat_status", "chat_error"), [(404, "model not found"), (400, "Invalid model: nope")]
)
def test_an_unknown_model_says_so(chat_status, chat_error):
    api = Api(["mistral-small-2506"], chat_status=chat_status, chat_error=chat_error)
    with pytest.raises(ProviderError) as exc:
        openai_like(MistralProvider, api).ping("nope")
    assert exc.value.kind == "model"
    assert "„nope“" in exc.value.message and "Schlüssel funktioniert" in exc.value.message


@pytest.mark.parametrize(
    ("status", "kind", "text"),
    [
        (401, "auth", "abgelehnt"),
        (403, "auth", "falsches Projekt"),
        (404, "other", "Basis-URL bzw. Projekt"),
        (500, "server", "HTTP 500"),
    ],
)
def test_the_list_tells_key_and_address_problems(status, kind, text):
    api = Api([], list_status=status)
    with pytest.raises(ProviderError) as exc:
        openai_like(ScalewayProvider, api).ping("deepseek-v4.1-flash")
    assert exc.value.kind == kind and text in exc.value.message
    assert KEY not in exc.value.message


def test_unreachable():
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    with pytest.raises(ProviderError) as exc:
        MistralProvider(KEY, http_client=client(boom), retry_wait_s=0).ping("m")
    assert exc.value.kind == "network" and "nicht erreichbar" in exc.value.message


# --------------------------------------------------- Anthropic, DeutschlandGPT


def test_anthropic_a_dated_id_in_the_list_counts():
    api = Api(["claude-haiku-5-5-20260901", "claude-opus-5-5"])
    provider = anthropic_like(AnthropicProvider, api)
    assert provider.ping("claude-haiku-5-5").input_tokens == 0
    assert provider.ping("claude-opus-5-5").input_tokens == 0
    assert [p for p in api.paths()] == [("GET", "/v1/models")] * 2
    assert api.requests[0].headers["x-api-key"] == KEY


def test_anthropic_an_unlisted_model_gets_one_token():
    api = Api(["claude-sonnet-5-5"])
    usage = anthropic_like(AnthropicProvider, api).ping("claude-haiku-5-5")
    assert (usage.input_tokens, usage.output_tokens) == (9, 1)
    assert api.paths() == [("GET", "/v1/models"), ("POST", "/v1/messages")]
    body = json.loads(api.requests[1].content)
    assert body["max_tokens"] == 1 and "thinking" not in body


def test_anthropic_unknown_model_and_rejected_key():
    api = Api([], chat_status=404, chat_error="model: nope")
    with pytest.raises(ProviderError) as exc:
        anthropic_like(AnthropicProvider, api).ping("nope")
    assert exc.value.kind == "model"
    for status, text in ((401, "abgelehnt"), (403, "keinen Zugriff")):
        api = Api([], list_status=status)
        with pytest.raises(ProviderError) as exc:
            anthropic_like(AnthropicProvider, api).ping("claude-haiku-5-5")
        assert exc.value.kind == "auth" and text in exc.value.message


def test_deutschlandgpt_without_a_models_list_asks_for_one_token():
    api = Api([], list_status=404)
    usage = anthropic_like(DeutschlandGptProvider, api).ping("claude-haiku-5.5")
    assert usage.output_tokens == 1
    assert api.paths() == [("GET", "/anthropic/v1/models"), ("POST", "/anthropic/v1/messages")]
    assert str(api.requests[0].url).startswith("https://api.deutschlandgpt.de/anthropic/")
