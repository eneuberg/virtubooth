"""`x.llm.config`: defaults, validation, the PUT route, the local-detector
switch and `external_ai_active`."""

from __future__ import annotations

import pytest

from virtubooth.extensions.wall.enrich import jobs
from virtubooth.extensions.wall.llm import admin_api, config, flags

from ..conftest import ORIGIN
from ..llm_fakes import COOLEST_SPEC, add_category, add_property

BASE = "/api/x/wall/admin/llm"


@pytest.fixture(autouse=True)
def mounted(app):
    app.include_router(admin_api.router, prefix="/api/x/wall")


def test_defaults(core):
    cfg = config.load_config(core.repos.app_settings)
    assert cfg.model_dump() == {
        "enabled": False,
        "provider": "anthropic",
        "model": "claude-haiku-5-5",
        "poll": True,
        "poll_interval_s": 180,
        "detect": {"external": False},
        "effort": "low",
        "image_max_px": 1024,
        "budget": {"party_usd": 5.0, "party_calls": None, "daily_usd": 2.0, "daily_calls": None},
        "rev": 0,
        "updated_at": None,
        "by": None,
    }


def test_invalid_stored_value_reads_as_defaults(core):
    core.repos.app_settings.put(config.CONFIG_KEY, {"poll_interval_s": 5}, at="x")
    assert config.load_config(core.repos.app_settings) == config.LlmConfig()


def test_merge():
    cur = config.LlmConfig()
    new = config.merged(cur, config.LlmConfigIn(enabled=True, budget={"party_usd": None}))
    assert new.enabled is True and new.budget.party_usd is None and new.budget.daily_usd == 2.0
    # switching the provider picks its default model
    eu = config.merged(cur, config.LlmConfigIn(provider="mistral"))
    assert eu.model == "mistral-small-2506"
    for bad in (
        config.LlmConfigIn(poll_interval_s=59),
        config.LlmConfigIn(poll_interval_s=3601),
        config.LlmConfigIn(model="claude-opus-4-1"),
        config.LlmConfigIn(provider="mistral", model="claude-haiku-5-5"),
        config.LlmConfigIn(budget={"daily_usd": -1}),
        config.LlmConfigIn(image_max_px=4000),
    ):
        with pytest.raises(ValueError):
            config.merged(cur, bad)


def test_put_config(admin, core):
    r = admin.put(
        f"{BASE}/config",
        json={"enabled": True, "model": "claude-sonnet-5-5", "poll_interval_s": 600},
        headers=ORIGIN,
    )
    assert r.status_code == 200, r.text
    cfg = r.json()["config"]
    assert cfg["enabled"] is True and cfg["model"] == "claude-sonnet-5-5"
    assert cfg["poll_interval_s"] == 600 and cfg["rev"] == 1 and cfg["by"].startswith("admin:")
    entry = core.repos.audit.list(1)[0]
    assert entry.action == "llm.config"
    assert entry.details == {"changed": ["enabled", "model", "poll_interval_s"]}

    r = admin.put(f"{BASE}/config", json={"poll_interval_s": 10}, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["error"] == "invalid_llm_config"
    assert "Minuten" in r.json()["message"]
    r = admin.put(f"{BASE}/config", json={"nonsense": 1}, headers=ORIGIN)
    assert r.status_code == 422


def test_ai_detection_on_switches_the_local_detector_off(admin, core):
    # an older client still sends `local`: ignored, the either/or decides
    r = admin.put(
        f"{BASE}/config", json={"detect": {"local": True, "external": True}}, headers=ORIGIN
    )
    assert r.status_code == 200, r.text
    assert "objects" in jobs.disabled_analyzers(core.repos.app_settings)
    assert r.json()["detection"]["mode"] == "ai"
    # switching it off again does not switch the local one back on by itself
    r = admin.put(f"{BASE}/config", json={"detect": {"external": False}}, headers=ORIGIN)
    assert r.json()["detection"]["mode"] == "off"
    assert "objects" in jobs.disabled_analyzers(core.repos.app_settings)


def test_external_ai_active(core):
    repos = core.repos
    assert flags.external_ai_active(repos) is False
    cfg = config.LlmConfig(enabled=True)
    config.save_config(repos.app_settings, cfg, by="t")
    assert flags.external_ai_active(repos) is False  # on, but nothing would be sent
    add_category(core, "coolstes_objekt", COOLEST_SPEC, enabled=False)
    assert flags.external_ai_active(repos) is False
    add_category(core, "coolstes_objekt_2", COOLEST_SPEC)
    assert flags.external_ai_active(repos) is True
    with core.db.tx() as c:
        c.execute("DELETE FROM wall_categories")
    add_property(core)
    assert flags.external_ai_active(repos) is True
    config.save_config(repos.app_settings, cfg.model_copy(update={"enabled": False}), by="t")
    assert flags.external_ai_active(repos) is False
    config.save_config(
        repos.app_settings,
        cfg.model_copy(update={"detect": config.DetectConfig(local=True, external=True)}),
        by="t",
    )
    assert flags.external_ai_active(repos) is True
