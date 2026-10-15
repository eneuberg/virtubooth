"""DeutschlandGPT (Claude through its Anthropic-compatible endpoint, EUR) and the
„Denkaufwand“ (adaptive thinking with an effort) on mocked transports, the EUR
pricing, and the guests' privacy text per provider. No network."""

from __future__ import annotations

import json

import httpx2
import pytest

from virtubooth.extensions.wall.llm import config, pricing, prompts
from virtubooth.extensions.wall.llm.providers import BY_ID, make_provider
from virtubooth.extensions.wall.llm.providers.anthropic import AnthropicProvider
from virtubooth.extensions.wall.llm.providers.base import PhotoLine, ProviderError
from virtubooth.extensions.wall.llm.providers.deutschlandgpt import (
    BASE_URL,
    DeutschlandGptProvider,
)
from virtubooth.services.identity import external_ai_text

from ..llm_fakes import FakeProvider, add_guest, add_photo, add_property, setup_llm

KEY = "dgpt_live_0123456789abcdefWXYZ"
LINE = PhotoLine(ref="Pph000001", author="Gast", labels=("hat", "cup"))


def reply(text: str, *, usage=(2000, 500), model="claude-haiku-5.5"):
    """A DeutschlandGPT answer as immobot saw it live: an empty thinking block first."""
    return {
        "id": "msg_dgpt", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "thinking", "thinking": "", "signature": "x"},
                    {"type": "text", "text": text}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    }  # fmt: skip


def dgpt(handler) -> DeutschlandGptProvider:
    return DeutschlandGptProvider(
        KEY, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )


def test_request_goes_to_its_endpoint_in_the_anthropic_shape():
    sent: list[httpx2.Request] = []

    def handler(request):
        sent.append(request)
        return httpx2.Response(
            200, json=reply('{"photos": [{"id": "Pph000001", "scores": [0.9, 0.1]}]}')
        )

    scores, usage = dgpt(handler).score(
        "Wie cool?", [LINE], model="claude-haiku-5.5", effort="medium"
    )
    assert scores == {"Pph000001": [0.9, 0.1]}
    assert (usage.input_tokens, usage.output_tokens) == (2000, 500)
    req = sent[0]
    assert str(req.url) == BASE_URL + "/v1/messages"
    assert req.headers["x-api-key"] == KEY and "anthropic-version" in req.headers
    assert "anthropic-beta" not in req.headers
    body = json.loads(req.content)
    assert body["model"] == "claude-haiku-5.5"
    assert body["thinking"] == {"type": "adaptive"}
    # no `format`: the endpoint ignores it on most models; the schema is in the system prompt
    assert body["output_config"] == {"effort": "medium"}
    assert body["system"].endswith(prompts.schema_instruction(prompts.SCORE_SCHEMA))
    assert body["max_tokens"] == 16000


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"photos": [{"id": "Pph000001", "scores": [0.5, 0.5]}]}\n```',
        'Hier: {"photos": [{"id": "Pph000001", "scores": [0.5, 0.5]}]} – fertig',
    ],
)
def test_answers_around_the_json_are_read_tolerantly(text):
    scores, _ = dgpt(lambda r: httpx2.Response(200, json=reply(text))).score(
        "x", [LINE], model="claude-haiku-5.5"
    )
    assert scores == {"Pph000001": [0.5, 0.5]}


def test_no_json_at_all_is_bad_output_with_its_usage():
    with pytest.raises(ProviderError) as exc:
        dgpt(lambda r: httpx2.Response(200, json=reply("Keine Ahnung.", usage=(10, 5)))).score(
            "x", [LINE], model="claude-haiku-5.5"
        )
    assert exc.value.kind == "bad_output" and exc.value.usage.output_tokens == 5


def test_no_photos_are_sent():
    calls: list[httpx2.Request] = []
    with pytest.raises(ProviderError, match="keine Fotos"):
        dgpt(lambda r: calls.append(r) or httpx2.Response(500)).detect(b"jpeg", model="m")
    assert calls == []
    assert BY_ID["deutschlandgpt"].vision is False


@pytest.mark.parametrize(
    ("status", "kind"), [(401, "auth"), (402, "rate"), (429, "rate"), (500, "server")]
)
def test_errors(status, kind):
    def handler(request):
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": "x", "message": "no"}}
        )

    provider = DeutschlandGptProvider(
        KEY, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    provider.client = provider.client.with_options(max_retries=0)
    with pytest.raises(ProviderError) as exc:
        provider.verdict("x", [LINE], model="claude-haiku-5.5")
    assert exc.value.kind == kind and KEY not in exc.value.message


def test_make_provider_uses_the_base_url():
    provider = make_provider("deutschlandgpt", KEY)
    assert isinstance(provider, DeutschlandGptProvider)
    assert str(provider.client.base_url).rstrip("/") == BASE_URL


# ------------------------------------------------------------------ thinking


@pytest.mark.parametrize(
    ("effort", "max_tokens", "timeout"),
    [("low", 8000, 60.0), ("medium", 12000, 120.0), ("high", 16000, 180.0), ("bogus", 8000, 60.0)],
)
def test_anthropic_effort_sets_thinking_tokens_and_time(effort, max_tokens, timeout):
    sent: list[httpx2.Request] = []

    def handler(request):
        sent.append(request)
        answer = {"objects": [{"label_en": "hat", "label_de": "Hut", "score": 0.9, "box": None}]}
        return httpx2.Response(200, json=reply(json.dumps(answer), model="claude-haiku-5-5"))

    provider = AnthropicProvider(
        KEY, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    objs, usage = provider.detect(b"jpeg", model="claude-haiku-5-5", effort=effort)
    assert [o.label for o in objs] == ["hat"] and usage.output_tokens == 500
    body = json.loads(sent[0].content)
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"]["effort"] == ("low" if effort == "bogus" else effort)
    assert body["output_config"]["format"]["schema"] == prompts.DETECT_SCHEMA
    assert body["max_tokens"] == max_tokens
    assert sent[0].extensions["timeout"]["read"] == timeout


def test_the_configured_effort_reaches_every_call(core):
    fake = FakeProvider()
    svc = setup_llm(core, fake, effort="high", detect={"external": True})
    add_property(core)
    add_photo(core, add_guest(core), ai_detect=True)
    from virtubooth.extensions.wall.llm.detect import DetectionRunner
    from virtubooth.extensions.wall.llm.poller import poll_once

    assert DetectionRunner(svc).run_once() == "done"
    assert poll_once(svc) is not None
    assert fake.efforts and set(fake.efforts) == {"high"}


def test_effort_is_validated():
    with pytest.raises(ValueError):
        config.merged(config.LlmConfig(), config.LlmConfigIn.model_validate({"effort": "max"}))


# ------------------------------------------------------------------- pricing


def test_eur_prices_are_converted_for_the_usd_meter():
    info = pricing.BY_ID["claude-haiku-5.5"]
    assert (info.provider, info.currency, info.in_mtok, info.out_mtok) == (
        "deutschlandgpt",
        "EUR",
        0.83,
        4.13,
    )
    # 1M in + 100k out (thinking included in output) at 1 € = 1.10 $
    eur = 0.83 + 0.1 * 4.13
    assert pricing.cost_micro_usd("claude-haiku-5.5", 1_000_000, 100_000) == pytest.approx(
        eur * pricing.EUR_USD * 1e6, abs=1
    )
    # USD models are unchanged
    assert pricing.cost_micro_usd("claude-haiku-5-5", 10_000, 0) == 1000
    assert pricing.DEFAULT_BY_PROVIDER["deutschlandgpt"] == "claude-haiku-5.5"
    assert {m.id for m in pricing.models_of("deutschlandgpt")} == {
        "claude-haiku-5.5",
        "claude-sonnet-5.5",
        "claude-opus-5.5",
    }


def test_a_dgpt_call_is_metered_in_usd(core):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx2.Response(200, json=reply('{"photos": []}', usage=(1_000_000, 0)))

    svc = setup_llm(core, provider="deutschlandgpt", model="claude-haiku-5.5")
    svc.keys.put("deutschlandgpt", KEY, by="t", at="x")
    svc.provider_factory = lambda _pid, key: DeutschlandGptProvider(
        key, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    svc.forget_provider()
    svc.call("property", "cool", lambda p, m: p.score("x", [LINE], model=m))
    row = core.db.one("SELECT provider, model, cost_micro_usd, ms FROM llm_usage")
    assert (row["provider"], row["model"]) == ("deutschlandgpt", "claude-haiku-5.5")
    assert row["cost_micro_usd"] == round(0.83 * 1.10 * 1e6) and row["ms"] is not None


# ------------------------------------------------------------ privacy text


@pytest.mark.parametrize(
    ("provider", "model", "named", "photos"),
    [
        ("anthropic", "claude-haiku-5-5", "(Anthropic, USA)", True),
        ("mistral", "mistral-small-2506", "(Mistral AI, EU)", True),
        ("deutschlandgpt", "claude-haiku-5.5", "(DeutschlandGPT, Deutschland)", False),
    ],
)
def test_guest_privacy_text_per_provider(client, core, provider, model, named, photos):
    from ..conftest import ORIGIN, scan

    cfg = config.LlmConfig(provider=provider, model=model)
    config.save_config(core.repos.app_settings, cfg, by="t")
    scan(client)
    body = client.post("/api/identify", json={}, headers=ORIGIN).json()
    info = body["consent"] if body["state"] == "needs_consent" else body["join_text"]
    text = " ".join(info["paragraphs"])
    assert named in text
    assert ("Fotos und erkannte Dinge" in text) is photos
    assert external_ai_text(named.strip("()"), photos=photos) in info["paragraphs"]
