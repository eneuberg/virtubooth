"""„Keine Weitergabe an externe KI“ (PLAN-NIGHT N5): chosen at join, changed
under „Du“ (PUT /api/me/external-ai), shown to the admin; the join texts
explain it always; the switch is offered while the host has external AI on."""

from __future__ import annotations

import json

from virtubooth.services.identity import EXTERNAL_AI_TEXT, external_ai_active

from ..conftest import ORIGIN, fp, scan

LLM_KEY = "x.llm.config"


def join(client, **extra):
    r = client.post(
        "/api/join",
        json={"accept": True, "version": "1", "fp": fp(), **extra},
        headers=ORIGIN,
    )
    assert r.status_code == 201, r.text
    return r.json()


def consent(client) -> dict:
    r = client.post("/api/identify", json={}, headers=ORIGIN)
    body: dict = r.json()
    return body["consent"] if body["state"] == "needs_consent" else body["join_text"]


def test_join_with_the_opt_out(client, admin, core):
    scan(client)
    user = join(client, ai_opt_out=True)["user"]
    assert user["ai_opt_out"] is True and user["analysis_opt_out"] is False
    listed = admin.get("/api/admin/users").json()["users"][0]
    assert listed["ai_opt_out"] is True and listed["analysis_opt_out"] is False


def test_default_is_off_and_du_switches_it(guest, admin):
    g = guest()
    r = g.put("/api/me/external-ai", json={"opt_out": True}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["ai_opt_out"] is True
    assert admin.get("/api/admin/users").json()["users"][0]["ai_opt_out"] is True
    r = g.put("/api/me/external-ai", json={"opt_out": False}, headers=ORIGIN)
    assert r.json()["user"]["ai_opt_out"] is False
    assert g.put("/api/me/external-ai", json={}, headers=ORIGIN).status_code == 422


def test_needs_a_joined_guest(client):
    scan(client)
    r = client.put("/api/me/external-ai", json={"opt_out": True}, headers=ORIGIN)
    assert r.status_code in (401, 403)


def test_the_text_is_always_there(client, core):
    scan(client)
    info = consent(client)
    assert info["external_ai"] is False
    assert EXTERNAL_AI_TEXT in info["paragraphs"]
    # „Mehr dazu“ = everything between the first and the last paragraph
    assert info["paragraphs"].index(EXTERNAL_AI_TEXT) not in (0, len(info["paragraphs"]) - 1)
    assert "Anthropic" in EXTERNAL_AI_TEXT and "Keine Weitergabe an externe KI" in EXTERNAL_AI_TEXT
    # the old promise is gone (security review 3, consent and privacy)
    assert not any("verlässt den Server" in p for p in info["paragraphs"])


def put_config(core, **config) -> None:
    core.repos.app_settings.put(LLM_KEY, config, at="2026-10-15T20:00:00.000+00:00")


def test_external_ai_active(core):
    repos = core.repos
    assert external_ai_active(repos) is False
    put_config(core, enabled=False, detect={"external": True})
    assert external_ai_active(repos) is False
    put_config(core, enabled=True, detect={"local": True, "external": False})
    assert external_ai_active(repos) is False  # on, but nothing would be sent
    put_config(core, enabled=True, detect={"external": True})
    assert external_ai_active(repos) is True
    # an active property
    put_config(core, enabled=True, detect={"external": False})
    core.db.one(
        "INSERT INTO llm_properties (name, prompt, created_at) VALUES ('coolness', 'p', 'x') "
        "RETURNING id"
    )
    assert external_ai_active(repos) is True
    core.db.one("UPDATE llm_properties SET archived_at='y' RETURNING id")
    assert external_ai_active(repos) is False
    # an enabled category with a verdict
    spec = {"title": "Coolstes", "verdict": {"prompt": "Wer?"}}
    core.db.one(
        "INSERT INTO wall_categories (id, position, enabled, spec, updated_at) "
        "VALUES ('cool', 1, 1, ?, 'x') RETURNING id",
        (json.dumps(spec),),
    )
    assert external_ai_active(repos) is True
    core.db.one("UPDATE wall_categories SET enabled=0 RETURNING id")
    assert external_ai_active(repos) is False


def test_join_sheet_offers_the_switch_while_active(client, core):
    put_config(core, enabled=True, detect={"external": True})
    scan(client)
    assert consent(client)["external_ai"] is True


def test_the_text_names_the_configured_provider(client, core):
    """„Mehr dazu“ names who would get the data: Anthropic by default, Mistral
    when the host picked the EU provider (with a real x.llm.config)."""
    from virtubooth.extensions.wall.llm import config as llm_config

    scan(client)
    assert "(Anthropic, USA)" in " ".join(consent(client)["paragraphs"])
    cfg = llm_config.load_config(core.repos.app_settings).model_dump()
    cfg.update(provider="mistral", model="mistral-small-2506")
    llm_config.save_config(
        core.repos.app_settings, llm_config.LlmConfig.model_validate(cfg), by="test"
    )
    text = " ".join(consent(client)["paragraphs"])
    assert "(Mistral AI, EU)" in text and "Anthropic" not in text
    assert consent(client)["external_ai"] is False  # switched off: no switch at join
