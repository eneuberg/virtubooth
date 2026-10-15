"""Object detection is either/or (local OR external AI) and only for new photos:
the config migration, the switches, the worker's marking (no backfill sweep),
the merged list of new photos and legacy rows."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from virtubooth.extensions.wall.enrich import jobs, objects
from virtubooth.extensions.wall.enrich.analyzers.basic import BasicAnalyzer
from virtubooth.extensions.wall.enrich.objects import DetectedObject
from virtubooth.extensions.wall.enrich.pipeline import AnalyzerInfo, Frame, Result
from virtubooth.extensions.wall.enrich.service import EnrichmentService
from virtubooth.extensions.wall.enrich.worker import Worker
from virtubooth.extensions.wall.llm import admin_api, config, ports
from virtubooth.extensions.wall.llm.detect import DetectionRunner

from ..conftest import ORIGIN
from ..llm_fakes import FakeProvider, add_guest, add_photo, setup_llm

BASE = "/api/x/wall/admin/llm"
AI = [ports.DetectedObject("party hat", "Partyhut", 0.8, (0.1, 0.0, 0.2, 0.2))]


@pytest.fixture(autouse=True)
def mounted(app):
    app.include_router(admin_api.router, prefix="/api/x/wall")


def local_on(core) -> bool:
    return "objects" not in jobs.disabled_analyzers(core.repos.app_settings)


# --------------------------------------------------------------- migration


def store_old(core, **fields):
    """A stored config in the shape from before the either/or (`detect.local`)."""
    old = config.LlmConfig().model_dump(mode="json")
    old.pop("effort")
    old.update(fields)
    core.repos.app_settings.put(config.CONFIG_KEY, old, at="x")


def test_old_config_with_both_on_and_ai_running_becomes_ai(core):
    store_old(core, enabled=True, poll=False, poll_interval_s=600,
              detect={"local": True, "external": True})  # fmt: skip
    assert local_on(core)
    assert config.migrate(core.repos.app_settings) == "ai"
    assert not local_on(core)
    raw = core.repos.app_settings.get(config.CONFIG_KEY)
    assert raw["detect"] == {"external": True}
    cfg = config.load_config(core.repos.app_settings)
    # the poll setting moved in the UI only: same values, same meaning
    assert cfg.enabled and cfg.detect.external and cfg.poll is False
    assert cfg.poll_interval_s == 600 and cfg.effort == "low"
    assert config.migrate(core.repos.app_settings) is None  # idempotent


def test_old_config_with_the_master_switch_off_keeps_the_local_detector(core):
    store_old(core, enabled=False, detect={"local": True, "external": True})
    assert config.migrate(core.repos.app_settings) == "local"
    assert local_on(core)
    cfg = config.load_config(core.repos.app_settings)
    assert not cfg.detect.external and not cfg.enabled


def test_old_config_with_one_detector_only_changes_shape(core):
    store_old(core, enabled=True, poll=True, detect={"local": True, "external": False})
    assert config.migrate(core.repos.app_settings) is None
    assert core.repos.app_settings.get(config.CONFIG_KEY)["detect"] == {"external": False}
    assert local_on(core) and config.load_config(core.repos.app_settings).poll is True
    # nothing stored at all: nothing to do
    core.repos.app_settings.put(config.CONFIG_KEY, {}, at="x")
    assert config.migrate(core.repos.app_settings) is None


def test_the_service_migrates_at_start(core):
    store_old(core, enabled=True, detect={"local": True, "external": True})
    svc = setup_llm(core, FakeProvider())  # writes the new shape: store the old one again
    store_old(core, enabled=True, detect={"local": True, "external": True})
    svc.start()
    try:
        assert not local_on(core) and svc.config().detect.external
    finally:
        svc.stop()


# ---------------------------------------------------------------- switching


def test_mode_route_switches_either_or(admin, core):
    def put(mode):
        r = admin.put(f"{BASE}/object-detection", json={"mode": mode}, headers=ORIGIN)
        assert r.status_code == 200, r.text
        return r.json()

    assert admin.get(BASE).json()["detection"]["mode"] == "local"
    body = put("ai")
    assert body["detection"]["mode"] == "ai" and body["config"]["detect"]["external"]
    assert not local_on(core)
    body = put("local")
    assert body["detection"]["mode"] == "local" and not body["config"]["detect"]["external"]
    assert local_on(core)
    body = put("off")
    assert body["detection"]["mode"] == "off" and not local_on(core)
    r = admin.put(f"{BASE}/object-detection", json={"mode": "both"}, headers=ORIGIN)
    assert r.status_code == 422


def test_local_switch_on_switches_the_ai_off(core):
    config.set_ai_detection(core.repos.app_settings, True, by="t")
    ports.set_local_objects(core, False, by="t")
    service = EnrichmentService.of(core)
    service.set_analyzer("objects", enabled=True, settings=None, actor="t")
    assert local_on(core) and not config.load_config(core.repos.app_settings).detect.external
    config.set_ai_detection(core.repos.app_settings, True, by="t")
    service.set_disabled(set(), actor="t")  # „everything on“ includes the local detector
    assert not config.load_config(core.repos.app_settings).detect.external


def test_a_provider_without_vision_cannot_detect(core):
    cur = config.LlmConfig(enabled=True, detect=config.DetectConfig(external=True))
    with pytest.raises(ValueError, match="keine Fotos"):
        config.merged(cur, config.LlmConfigIn(provider="deutschlandgpt"))
    ok = config.merged(
        cur, config.LlmConfigIn(provider="deutschlandgpt", detect=config.DetectConfig())
    )
    assert ok.model == "claude-haiku-5.5" and not ok.detect.external


# ------------------------------------------------- new photos only, no sweep


class FakeDetector:
    info = AnalyzerInfo(name="objects", title="Objekte", version="2", kind="basic",
                        facts=("people",))  # fmt: skip
    model_id = "fake-detector@2"

    def load(self, models: Mapping[str, Path]) -> None:
        pass

    def run(self, frame: Frame, prior: Mapping[str, Result]) -> Result:
        return Result(
            facts={"people": 1.0},
            objects=[DetectedObject("person", "Person", 0.9, (0.1, 0.1, 0.3, 0.8))],
        )


def analyse(core, uid) -> int:
    """Upload a photo and let the worker analyse it (one pass)."""
    pid, _ = add_photo(core, uid, state="pending", labels=())
    claimed = jobs.claim(core.db)
    assert claimed is not None and claimed.id == pid
    worker = Worker(core.settings.data_dir, analyzers=[BasicAnalyzer(), FakeDetector()],
                    watch_parent=False)  # fmt: skip
    assert worker.process(core.repos, claimed) == "done"
    return pid


def ai_flag(core, pid) -> int:
    return int(core.db.one("SELECT ai_detect FROM wall_analysis WHERE photo_id=?", (pid,))[0])


def test_only_photos_analysed_while_the_ai_is_active_are_sent(core):
    fake = FakeProvider(objects=AI)
    svc = setup_llm(core, fake)
    uid = add_guest(core)
    # before: the local detector is active
    old = analyse(core, uid)
    assert ai_flag(core, old) == 0
    assert [o.source for o in ports.objects_of(core.db, [old])[old]] == ["local"]
    # legacy photos from before v15 (finished, never queued) too
    legacy, _ = add_photo(core, uid, labels=("person",))

    # switching the AI detector on sends NONE of them (no backfill sweep)
    config.set_ai_detection(core.repos.app_settings, True, by="t")
    ports.set_local_objects(core, False, by="t")
    runner = DetectionRunner(svc)
    assert objects.count_eligible_for_external(core.db, "claude") == 0
    assert runner.run_once() == "idle" and fake.detected == []

    # a new photo: the worker skips the local detector and queues it for the AI
    new = analyse(core, uid)
    assert ai_flag(core, new) == 1
    local_run = core.db.one(
        "SELECT state, error FROM photo_detection_runs WHERE photo_id=? AND source='local'",
        (new,),
    )
    assert local_run["state"] == "skipped"
    assert runner.run_once() == "done" and len(fake.detected) == 1
    assert runner.run_once() == "idle"
    # its merged list is the AI's list only (nothing to merge with)
    merged = ports.objects_of(core.db, [new])[new]
    assert [(o.idx, o.label, o.sources) for o in merged] == [(0, "party hat", ("claude",))]
    assert set(objects.source_objects_of(core.db, new)) == {"claude"}
    # the older photos still have just their local list
    for pid in (old, legacy):
        assert {o.source for o in ports.objects_of(core.db, [pid])[pid]} == {"local"}

    # back to local: new photos are not queued, even with the master switch on
    ports.set_local_objects(core, True, by="t")
    config.set_ai_detection(core.repos.app_settings, False, by="t")
    newest = analyse(core, uid)
    assert ai_flag(core, newest) == 0
    assert [o.source for o in ports.objects_of(core.db, [newest])[newest]] == ["local"]
    config.set_ai_detection(core.repos.app_settings, True, by="t")
    assert runner.run_once() == "idle" and len(fake.detected) == 1


@pytest.mark.parametrize("cause", ["budget", "no_key"])
def test_the_local_detector_takes_over_while_the_ai_cannot(core, cause):
    """AI detection active, but the budget is used up or no key is stored: new
    photos get the local list instead (marked), not an empty one."""
    budget = {"party_calls": 0} if cause == "budget" else {}
    svc = setup_llm(core, FakeProvider(objects=AI), budget=budget)
    if cause == "no_key":
        svc.keys.clear()
    config.set_ai_detection(core.repos.app_settings, True, by="t")
    ports.set_local_objects(core, False, by="t")
    assert jobs.ai_detection_active(core.repos.app_settings)
    pid = analyse(core, add_guest(core))
    assert ai_flag(core, pid) == 0  # never queued for the AI
    assert [o.source for o in ports.objects_of(core.db, [pid])[pid]] == ["local"]
    data = jobs.get(core.db, pid).data
    assert data[jobs.AI_FALLBACK] == (jobs.NO_KEY if cause == "no_key" else data[jobs.AI_FALLBACK])
    assert data[jobs.AI_FALLBACK]
    # the analyzer setting is untouched: the AI stays the chosen detector
    assert not local_on(core)


def test_master_switch_off_queues_nothing(core):
    setup_llm(core, FakeProvider(), enabled=False, detect={"external": True})
    ports.set_local_objects(core, False, by="t")
    pid = analyse(core, add_guest(core))
    assert ai_flag(core, pid) == 0
    assert not jobs.ai_detection_active(core.repos.app_settings)


def test_legacy_rows_with_both_lists_stay_as_they_are(core):
    """A photo from before the either/or with the local and the AI list keeps its
    merged list (and the idx the property scores point at)."""
    pid, _ = add_photo(core, add_guest(core), labels=())
    ports.append(core.db, pid, "local", "det@1", [
        DetectedObject("person", "Person", 0.9, (0.1, 0.1, 0.3, 0.8)),
        DetectedObject("cup", "Tasse", 0.6, (0.6, 0.6, 0.1, 0.1)),
    ])  # fmt: skip
    ports.append(core.db, pid, "claude", "claude-haiku-5-5", [
        DetectedObject("woman", "Frau", 0.9, (0.1, 0.1, 0.3, 0.8)),
        DetectedObject("party hat", "Partyhut", 0.8, None),
    ])  # fmt: skip
    before = [(o.idx, o.label, o.sources) for o in ports.objects_of(core.db, [pid])[pid]]
    assert before == [
        (0, "person", ("local", "claude")),
        (1, "cup", ("local",)),
        (2, "party hat", ("claude",)),
    ]
    config.set_ai_detection(core.repos.app_settings, True, by="t")
    config.migrate(core.repos.app_settings)
    after = [(o.idx, o.label, o.sources) for o in ports.objects_of(core.db, [pid])[pid]]
    assert after == before


# -------------------------------------------------------------- the row's numbers


def test_detection_stats_and_cost_in_the_status(admin, core):
    fake = FakeProvider(objects=AI)
    svc = setup_llm(core, fake, detect={"external": True})
    add_photo(core, add_guest(core), labels=(), ai_detect=True)
    assert DetectionRunner(svc).run_once() == "done"
    det = admin.get(BASE).json()["detection"]
    assert det["mode"] == "ai" and det["done"] == 1 and det["pending"] == 0
    assert det["stats"]["processed"] == 1 and det["stats"]["errors"] == 0
    assert det["stats"]["last_ms"] is not None and det["stats"]["avg_ms"] is not None
    # FakeProvider's usage: 1000 in / 200 out on Claude Haiku 5.5
    assert det["cost_usd"] == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6)
    assert fake.efforts == ["low"]
